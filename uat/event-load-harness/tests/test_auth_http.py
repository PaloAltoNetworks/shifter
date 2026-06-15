"""The authenticated client must scope cookies to the host and not chase redirects."""

from event_load_harness.auth_http import _attach_cookies, build_client


def test_build_client_disables_automatic_redirects():
    client = build_client("https://dev.example.com", 10.0)
    assert client.follow_redirects is False


def test_imported_cookies_are_scoped_to_target_host():
    # Hostless cookies could be forwarded to an off-origin redirect target; scoping
    # them to the configured host prevents that leak.
    client = build_client("https://dev.example.com", 10.0)
    _attach_cookies(client, "sessionid=abc; csrftoken=xyz", "https://dev.example.com")
    jar = list(client.cookies.jar)
    assert {c.name for c in jar} == {"sessionid", "csrftoken"}
    assert all(c.domain.lstrip(".") == "dev.example.com" for c in jar)
