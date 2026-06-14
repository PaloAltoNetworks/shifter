"""Route contracts and HTTP status classification (the deterministic parts).

Live HTTP/websocket driving is exercised by operator runs against a deployed
environment, not in CI (the preflight requires driving the *real* path, not a
mock). These tests pin the route->endpoint contract and the error taxonomy so a
contract drift or a misclassified status is caught here.
"""

import types

import pytest

from event_load_harness.routes import (
    HTTP_ROUTES,
    WS_ROUTES,
    classify_http,
    http_method_and_path,
    ws_close_result,
    ws_handshake_headers,
)


def test_ws_handshake_headers_include_origin_and_cookies():
    # Channels' AllowedHostsOriginValidator needs the browser Origin header; without
    # it the handshake is rejected for the wrong reason and stops matching the real path.
    client = types.SimpleNamespace(cookies={"sessionid": "abc"})
    headers = ws_handshake_headers(client, "https://dev.example.com")
    assert ("Origin", "https://dev.example.com") in headers
    assert ("Cookie", "sessionid=abc") in headers


def test_ws_close_result_normal_is_success():
    assert ws_close_result(1000) == (True, None)
    assert ws_close_result(1001) == (True, None)


def test_ws_close_result_application_codes_are_drops():
    # A server close with SERVICE_UNAVAILABLE / SSH-failure must be a drop, never
    # swallowed as a NORMAL success (the harness's core close-code evidence).
    ok, category = ws_close_result(4503)
    assert ok is False
    assert category == "service_unavailable"
    ok, category = ws_close_result(4502)
    assert ok is False
    assert category == "ssh_connection_failed"


def test_ws_close_result_unknown_and_none():
    assert ws_close_result(1006) == (False, "other")
    assert ws_close_result(None) == (False, "none")


def test_active_http_routes_map_to_real_portal_endpoints():
    # The endpoints exist in shifter_platform urls (ctf/urls.py, mission_control/urls.py).
    assert http_method_and_path("page:dashboard") == ("GET", "/ctf/")
    assert http_method_and_path("page:scoreboard") == ("GET", "/ctf/scoreboard/")
    assert http_method_and_path("range:status-poll") == ("GET", "/ctf/api/range/status/")
    method, path = http_method_and_path("guacamole:bootstrap")
    assert method == "POST"
    assert "guacamole" in path


def test_ws_routes_use_the_real_consumer_paths():
    # Mirrors mission_control/routing.py re_path patterns.
    assert "ws/terminal/" in WS_ROUTES["ws:terminal"]
    assert "ws/range-status/" in WS_ROUTES["ws:range-status"]


def test_unknown_http_route_raises():
    with pytest.raises(KeyError):
        http_method_and_path("page:does-not-exist")


def test_classify_http_success():
    assert classify_http(200) == (True, None)
    assert classify_http(302) == (True, None)


def test_classify_http_error_taxonomy():
    assert classify_http(404) == (False, "client_error")
    assert classify_http(429) == (False, "rate_limited")
    assert classify_http(500) == (False, "server_error")
    assert classify_http(503) == (False, "service_unavailable")


def test_route_tables_are_disjoint_and_cover_active_catalog():
    # Every active catalog route has exactly one executor table entry.
    from event_load_harness.profiles import ROUTE_CATALOG

    active = {n for n, s in ROUTE_CATALOG.items() if s.status == "active"}
    covered = set(HTTP_ROUTES) | set(WS_ROUTES)
    assert active == covered
    assert set(HTTP_ROUTES).isdisjoint(WS_ROUTES)
