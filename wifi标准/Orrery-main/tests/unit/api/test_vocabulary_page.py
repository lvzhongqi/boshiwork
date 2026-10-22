"""GET /vocabulary — the assumption vocabulary page the console links to.

One renderer serves both surfaces: ``orrery kb <path>.html`` writes it to a
file and this route serves the same bytes, differing only in the theme stamp.
"""

from fastapi.testclient import TestClient

from orrery.web import server
from orrery.nodes.apply.realizers import VOCAB


def test_the_page_is_served_whole_and_self_contained():
    r = TestClient(server.app).get("/vocabulary")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    # complete: every axis and subtype the build declares is on the page
    for axis in VOCAB.axes():
        assert f'id="ax-{axis}"' in body, axis
        for sub in VOCAB.dimension_values(axis):
            assert f'id="st-{axis}-{sub}"' in body, (axis, sub)
    # self-contained: no request leaves the page, so it renders with the
    # console offline
    assert "<style>" in body and "<script>" in body
    assert "src=" not in body


def test_the_page_matches_the_console_theme():
    """The console is unconditionally dark, so the route asks for dark. The
    CLI's own file passes no theme and follows the OS instead."""
    from orrery.api.kb_graph import render_kb_html

    roots = server.vocabulary_corpus_roots()
    body = TestClient(server.app).get("/vocabulary").text
    assert '<html lang="en" data-theme="dark">' in body
    assert 'data-theme' not in render_kb_html().splitlines()[1]
    # Same renderer both ways, theme stamp aside. The roots come from the
    # route's own helper, so restating them here cannot hide a drift.
    assert render_kb_html(theme="dark", corpus_roots=roots) == body


def test_it_is_not_cached_into_staleness():
    """Rendered per request: a cached copy would outlive the declarations it
    reports."""
    r = TestClient(server.app).get("/vocabulary")
    assert "no-cache" in r.headers.get("cache-control", "")
