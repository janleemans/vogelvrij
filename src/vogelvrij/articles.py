"""Filesystem-backed Markdown news articles for the public site."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import List, Mapping, Optional
from urllib.parse import quote, unquote, urlsplit
from zoneinfo import ZoneInfo

import bleach
import yaml
from markdown import Markdown
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

LOGGER = logging.getLogger(__name__)
BRUSSELS = ZoneInfo("Europe/Brussels")
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
ALLOWED_IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
MAX_ARTICLE_BYTES = 1_000_000
ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "em", "h2", "h3", "h4", "hr", "img",
    "li", "ol", "p", "pre", "strong", "ul",
}


@dataclass(frozen=True)
class Article:
    slug: str
    title: str
    published: datetime
    summary: str
    body_html: str
    image_url: Optional[str]
    image_alt: str

    @property
    def published_label(self) -> str:
        return self.published.astimezone(BRUSSELS).strftime("%d/%m/%Y")


def _relative_asset_path(value: str) -> Optional[PurePosixPath]:
    parsed = urlsplit(value.strip())
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    decoded = unquote(parsed.path)
    path = PurePosixPath(decoded)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        return None
    if path.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
        return None
    return path


def resolve_article_asset(articles_dir: Path, relative_path: str) -> Path:
    """Resolve an approved raster asset without permitting directory or symlink escapes."""
    path = _relative_asset_path(relative_path)
    if path is None:
        raise ValueError("invalid article asset path")
    root = articles_dir.resolve(strict=True)
    candidate = root.joinpath(*path.parts).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("article asset escapes its content directory") from exc
    if not candidate.is_file():
        raise ValueError("article asset is not a file")
    return candidate


def article_asset_url(articles_dir: Path, value: str) -> Optional[str]:
    path = _relative_asset_path(value)
    if path is None:
        return None
    try:
        resolve_article_asset(articles_dir, path.as_posix())
    except (FileNotFoundError, ValueError):
        return None
    return "/article-assets/" + quote(path.as_posix(), safe="/")


class _ArticleImageTreeprocessor(Treeprocessor):
    def __init__(self, markdown: Markdown, articles_dir: Path):
        super().__init__(markdown)
        self.articles_dir = articles_dir

    def run(self, root):
        for element in root.iter("img"):
            source = element.get("src", "")
            safe_url = article_asset_url(self.articles_dir, source)
            if safe_url is None:
                element.tag = "span"
                element.attrib.clear()
                element.text = "[Afbeelding niet beschikbaar]"
            else:
                element.set("src", safe_url)
                element.set("loading", "lazy")
                element.set("decoding", "async")
        return root


class _ArticleImageExtension(Extension):
    def __init__(self, articles_dir: Path):
        self.articles_dir = articles_dir
        super().__init__()

    def extendMarkdown(self, md: Markdown) -> None:
        md.treeprocessors.register(
            _ArticleImageTreeprocessor(md, self.articles_dir), "article_images", 5
        )


def _allowed_attribute(tag: str, name: str, value: str) -> bool:
    if tag == "a":
        return name in {"href", "title"}
    if tag == "img":
        return name in {"alt", "decoding", "loading", "src", "title"} and (
            name != "src" or value.startswith("/article-assets/")
        )
    return False


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _excerpt(body_html: str, limit: int = 220) -> str:
    parser = _TextExtractor()
    parser.feed(body_html)
    text = " ".join(" ".join(parser.parts).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _published(value: object) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("published must be an ISO-8601 date and time") from exc
    else:
        raise ValueError("published must be an ISO-8601 date and time")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("published must include a timezone")
    return result


def _required_text(metadata: Mapping[str, object], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def load_article(path: Path, articles_dir: Path) -> Optional[Article]:
    slug = path.stem
    if not SLUG_PATTERN.fullmatch(slug):
        raise ValueError(
            "filename must contain only lowercase letters, digits, hyphens, and underscores"
        )
    if path.stat().st_size > MAX_ARTICLE_BYTES:
        raise ValueError("article exceeds the 1 MB size limit")
    source = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not source.startswith("---\n") or "\n---\n" not in source[4:]:
        raise ValueError("article must start with YAML front matter")
    raw_metadata, body = source[4:].split("\n---\n", 1)
    metadata = yaml.safe_load(raw_metadata)
    if not isinstance(metadata, dict):
        raise ValueError("article front matter must be a mapping")
    draft = metadata.get("draft", False)
    if not isinstance(draft, bool):
        raise ValueError("draft must be true or false")
    if draft:
        return None
    title = _required_text(metadata, "title")
    published = _published(metadata.get("published"))
    markdown = Markdown(
        extensions=["fenced_code", "sane_lists", _ArticleImageExtension(articles_dir)]
    )
    rendered = markdown.convert(body)
    body_html = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=_allowed_attribute,
        protocols={"http", "https", "mailto"},
        strip=True,
    )
    summary_value = metadata.get("summary")
    if summary_value is not None and not isinstance(summary_value, str):
        raise ValueError("summary must be a string")
    summary = summary_value.strip() if isinstance(summary_value, str) else _excerpt(body_html)
    image_value = metadata.get("image")
    if image_value is not None and not isinstance(image_value, str):
        raise ValueError("image must be a relative path string")
    image_url = article_asset_url(articles_dir, image_value) if image_value else None
    if image_value and image_url is None:
        raise ValueError("image must reference an existing approved local raster image")
    image_alt_value = metadata.get("image_alt", "")
    if not isinstance(image_alt_value, str):
        raise ValueError("image_alt must be a string")
    return Article(
        slug=slug,
        title=title,
        published=published,
        summary=summary,
        body_html=body_html,
        image_url=image_url,
        image_alt=image_alt_value.strip(),
    )


def load_articles(articles_dir: Path) -> List[Article]:
    """Read every article afresh; one bad file must not take down the site."""
    if not articles_dir.is_dir():
        return []
    root = articles_dir.resolve()
    articles = []
    for path in sorted(articles_dir.glob("*.md")):
        if path.name.startswith("."):
            continue
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            article = load_article(resolved, articles_dir)
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            LOGGER.warning("Skipping invalid article %s: %s", path.name, exc)
            continue
        if article is not None:
            articles.append(article)
    return sorted(articles, key=lambda article: (article.published, article.slug), reverse=True)


def _lead_image(article: Article, class_name: str) -> str:
    if not article.image_url:
        return ""
    return (
        f'<img class="{class_name}" src="{escape(article.image_url, quote=True)}" '
        f'alt="{escape(article.image_alt, quote=True)}" loading="lazy" decoding="async">'
    )


def home_articles_markup(articles: List[Article]) -> str:
    if not articles:
        return '<p class="news-empty">Nog geen nieuwsartikelen beschikbaar.</p>'
    return "".join(
        '<article class="news-preview">'
        + _lead_image(article, "news-preview-image")
        + '<div class="news-preview-copy">'
        + f'<time datetime="{escape(article.published.isoformat(), quote=True)}">'
        + escape(article.published_label) + "</time>"
        + f'<h3><a href="/nieuws#{escape(article.slug, quote=True)}">'
        + escape(article.title) + "</a></h3>"
        + f"<p>{escape(article.summary)}</p></div></article>"
        for article in articles[:2]
    )


def news_articles_markup(articles: List[Article]) -> str:
    if not articles:
        return '<p class="news-empty">Nog geen nieuwsartikelen beschikbaar.</p>'
    return "".join(
        f'<article class="article-card" id="{escape(article.slug, quote=True)}">'
        + _lead_image(article, "article-image")
        + '<div class="article-card-header">'
        + f'<time datetime="{escape(article.published.isoformat(), quote=True)}">'
        + escape(article.published_label) + "</time>"
        + f"<h2>{escape(article.title)}</h2></div>"
        + f'<div class="article-body" id="article-body-{escape(article.slug, quote=True)}">'
        + article.body_html + "</div>"
        + '<button class="article-expand" type="button" hidden '
        + f'aria-expanded="false" aria-controls="article-body-{escape(article.slug, quote=True)}">'
        + '<span class="article-expand-icon" aria-hidden="true">⌄</span>'
        + '<span class="article-expand-label">Toon volledig artikel</span></button></article>'
        for article in articles
    )
