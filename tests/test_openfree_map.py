import pytest

from vogelvrij.openfree_map import render_openfree_html


def test_openfree_map_renderer_embeds_safe_data_and_map_features():
    page = render_openfree_html(
        {
            "aircraft": [{"flight": "</script><script>alert(1)</script>"}],
            "approaches": [],
        },
        nonce="test-nonce",
    )

    assert "<script>alert(1)</script>" not in page
    assert "\\u003c/script\\u003e" in page
    assert 'nonce="test-nonce"' in page
    assert "https://tiles.openfreemap.org/styles/liberty" in page
    assert 'geometry: { type: "LineString", coordinates: path }' in page
    assert 'geometry: { type: "Polygon", coordinates: [coordinates] }' in page
    assert 'rotation: last.track_degrees ?? 0' in page
    assert 'triangle.setAttribute("points", "5,0 10,14 0,14")' in page
    assert 'id="refresh-map" type="button">Kaart vernieuwen</button>' in page
    assert "window.location.reload()" in page
    assert "OpenFreeMap © OpenMapTiles" in page


def test_openfree_map_renderer_rejects_non_json_numbers():
    with pytest.raises(ValueError):
        render_openfree_html({"value": float("nan")}, nonce="test-nonce")
