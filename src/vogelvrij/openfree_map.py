"""Render recent aircraft tracks with MapLibre and OpenFreeMap."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

TEMPLATE = Path(__file__).parent / "templates" / "aircraft_history_openfree_map.html"


def render_openfree_html(data: Dict[str, Any], *, nonce: str) -> str:
    """Embed map data safely in the OpenFreeMap history page."""
    safe_json = (
        json.dumps(data, ensure_ascii=False, allow_nan=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("__MAP_DATA__", safe_json)
        .replace("__CSP_NONCE__", nonce)
    )
