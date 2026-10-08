from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from vogelvrij.articles import (
    Article,
    home_articles_markup,
    load_articles,
    news_articles_markup,
    resolve_article_asset,
)
from vogelvrij.web import make_handler, render_news_page, render_page


def write_article(
    directory: Path, name: str, *, published: str, extra: str = "", body: str = "Tekst"
):
    (directory / name).write_text(
        "---\n"
        f'title: "Titel {name}"\n'
        f'published: "{published}"\n'
        'summary: "Korte samenvatting"\n'
        f"{extra}"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )


def test_articles_are_reloaded_sorted_and_drafts_are_hidden(tmp_path):
    write_article(tmp_path, "ouder.md", published="2026-10-01T10:00:00+02:00")
    write_article(
        tmp_path,
        "concept.md",
        published="2026-10-03T10:00:00+02:00",
        extra="draft: true\n",
    )
    assert [article.slug for article in load_articles(tmp_path)] == ["ouder"]

    write_article(tmp_path, "nieuwer.md", published="2026-10-02T10:00:00+02:00")
    assert [article.slug for article in load_articles(tmp_path)] == ["nieuwer", "ouder"]


def test_article_filename_may_contain_underscores(tmp_path):
    write_article(
        tmp_path,
        "liveinfo_website.md",
        published="2026-10-08T10:00:00+02:00",
    )
    articles = load_articles(tmp_path)
    assert [article.slug for article in articles] == ["liveinfo_website"]


def test_markdown_is_sanitized_and_local_images_are_rewritten(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "foto.png").write_bytes(b"png")
    write_article(
        tmp_path,
        "veilig.md",
        published="2026-10-01T10:00:00+02:00",
        extra='image: "images/foto.png"\nimage_alt: "Beschrijving"\n',
        body=(
            "# Niet toegestaan\n\n"
            "![Lokaal](images/foto.png)\n\n"
            "![Extern](https://example.com/tracker.png)\n\n"
            '<script>alert("x")</script> [klik](javascript:alert(1))'
        ),
    )
    article = load_articles(tmp_path)[0]
    assert article.image_url == "/article-assets/images/foto.png"
    assert 'src="/article-assets/images/foto.png"' in article.body_html
    assert "example.com" not in article.body_html
    assert "<script" not in article.body_html
    assert "javascript:" not in article.body_html


def test_missing_bad_and_escaping_assets_are_not_served(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    good = images / "foto.webp"
    good.write_bytes(b"webp")
    assert resolve_article_asset(tmp_path, "images/foto.webp") == good
    with pytest.raises((FileNotFoundError, ValueError)):
        resolve_article_asset(tmp_path, "../secret.jpg")
    with pytest.raises((FileNotFoundError, ValueError)):
        resolve_article_asset(tmp_path, "images/missing.png")
    with pytest.raises(ValueError):
        resolve_article_asset(tmp_path, "images/file.svg")


def test_hidden_articles_and_markdown_symlink_escapes_are_ignored(tmp_path):
    write_article(tmp_path, ".hidden.md", published="2026-10-03T10:00:00+02:00")
    outside = tmp_path.parent / "outside.md"
    write_article(tmp_path.parent, "outside.md", published="2026-10-02T10:00:00+02:00")
    (tmp_path / "linked.md").symlink_to(outside)
    write_article(tmp_path, "visible.md", published="2026-10-01T10:00:00+02:00")
    assert [article.slug for article in load_articles(tmp_path)] == ["visible"]


def test_invalid_articles_are_skipped_without_hiding_valid_articles(tmp_path, caplog):
    (tmp_path / "broken.md").write_text("No front matter", encoding="utf-8")
    write_article(tmp_path, "valid.md", published="2026-10-01T10:00:00+02:00")
    articles = load_articles(tmp_path)
    assert [article.slug for article in articles] == ["valid"]
    assert "Skipping invalid article broken.md" in caplog.text


def test_home_and_news_markup_have_expected_links_and_controls():
    article = Article(
        slug="voorbeeld",
        title="Voorbeeld",
        published=datetime(2026, 10, 8, 8, tzinfo=timezone.utc),
        summary="Samenvatting",
        body_html="<p>Volledige tekst.</p>",
        image_url="/article-assets/images/foto.jpg",
        image_alt="Alternatieve tekst",
    )
    home = home_articles_markup([article])
    assert 'href="/nieuws#voorbeeld"' in home
    assert "Samenvatting" in home
    news = news_articles_markup([article])
    assert 'id="voorbeeld"' in news
    assert 'aria-expanded="false"' in news
    assert 'aria-controls="article-body-voorbeeld"' in news
    assert "Volledige tekst" in news
    assert "{{ARTICLES}}" not in render_news_page([article])


def test_homepage_places_latest_articles_before_statistics():
    article = Article(
        slug="voorbeeld",
        title="Voorbeeld",
        published=datetime(2026, 10, 8, 8, tzinfo=timezone.utc),
        summary="Samenvatting",
        body_html="<p>Volledige tekst.</p>",
        image_url=None,
        image_alt="",
    )
    page = render_page(
        {"07LR": 0, "25LR": 0, "01": 0, "19": 0},
        [],
        article.published,
        articles=[article],
    )
    assert page.index('class="contact"') < page.index('class="news-home"')
    assert page.index('class="news-home"') < page.index('class="statistics"')
    assert page.count('class="news-preview"') == 1
    assert 'href="/nieuws">read more</a>' in page


def test_news_and_asset_routes_do_not_require_the_database(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "foto.jpg").write_bytes(b"jpeg-data")
    write_article(
        tmp_path,
        "route-test.md",
        published="2026-10-08T10:00:00+02:00",
        extra='image: "images/foto.jpg"\n',
    )
    handler = object.__new__(make_handler(SimpleNamespace(), tmp_path))
    sent = []
    handler.send_body = lambda body, content_type, **options: sent.append(
        (body, content_type, options)
    )
    handler.path = "/nieuws"
    handler.do_GET()
    assert sent[-1][1] == "text/html; charset=utf-8"
    assert "Titel route-test.md" in sent[-1][0].decode()

    handler.path = "/article-assets/images/foto.jpg"
    handler.do_GET()
    assert sent[-1][:2] == (b"jpeg-data", "image/jpeg")


def test_news_page_script_and_layout_are_present():
    page = render_news_page([])
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr))' in page
    assert 'height: clamp(420px, 52vh, 560px)' in page
    assert '.article-card:not(.article-card-expanded)' in page
    assert '.article-card-expanded { height: auto; min-height: 0; }' in page
    assert '<script src="/news_page.js" defer></script>' in page
    handler = object.__new__(make_handler(SimpleNamespace(), Path("missing")))
    sent = []
    handler.send_body = lambda body, content_type, **options: sent.append((body, content_type))
    handler.path = "/news_page.js"
    handler.do_GET()
    script = sent[0][0].decode()
    assert "scrollHeight > body.clientHeight" in script
    assert 'setAttribute("aria-expanded"' in script
