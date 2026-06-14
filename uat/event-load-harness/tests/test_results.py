"""The RouteResult record is the common unit produced by route executors."""

from event_load_harness.results import RouteResult


def test_http_result_defaults():
    r = RouteResult(route_class="page:dashboard", kind="http", ok=True, status_code=200, latency_ms=42.0)
    assert r.kind == "http"
    assert r.ok is True
    assert r.status_code == 200
    assert r.ws_opened is False
    assert r.ws_dropped is False
    assert r.close_code is None
    assert r.reconnects == 0
    assert r.error_category is None


def test_ws_result_fields():
    r = RouteResult(
        route_class="ws:terminal",
        kind="ws",
        ok=False,
        status_code=None,
        latency_ms=15.0,
        ws_opened=True,
        ws_dropped=True,
        close_code=4503,
        reconnects=2,
        error_category="service_unavailable",
    )
    assert r.ws_opened is True
    assert r.close_code == 4503
    assert r.reconnects == 2
    assert r.error_category == "service_unavailable"


def test_result_is_frozen():
    r = RouteResult(route_class="page:home", kind="http", ok=True, status_code=200, latency_ms=1.0)
    try:
        r.ok = False  # type: ignore[misc]
    except Exception as exc:
        assert "frozen" in str(exc).lower() or exc.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("RouteResult should be immutable")
