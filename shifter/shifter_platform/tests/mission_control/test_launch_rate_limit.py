"""Behavior tests for launch-endpoint rate limiting (issue #322).

These drive the real Mission Control launch endpoints (``LaunchRangeView`` and
``NGFWCreateView``) through the DRF throttle layer and assert observable HTTP
behavior: 429 on budget exhaustion, ``Retry-After``, canonical vs legacy error
envelopes, fail-closed 503 on an admission-backend outage, and that a rejected
request never reaches CMS. The admission counters run against the
``launch_rate_limit`` cache, which is a process-local LocMemCache under the test
settings, so no real Redis is required.

The feature defaults OFF under test runs (``LAUNCH_RATE_LIMIT_ENABLED`` =
``not IS_TEST_RUN``) so the process-global fleet counter cannot accumulate across
unrelated launch tests; every test here opts in with ``override_settings``.

A separate group unit-tests the ``launch_rate_limit`` cache CONFIG builder
(``config._redis.build_launch_rate_limit_cache``) for the LocMem / plaintext /
TLS-pem / TLS-system postures without needing a live Redis, mirroring
``tests/config/test_channel_layers.py``.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.core.cache import caches
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from engine.models import Range
from risk_register.models import AuditLog
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.audit import AuditAction

pytestmark = pytest.mark.django_db

LEGACY_LAUNCH_URL = reverse("v1:mission_control:range-launch")
CANONICAL_LAUNCH_URL = "/api/v1/mission-control/range/launch/"
CANONICAL_NGFW_URL = "/api/v1/mission-control/ngfw/"
LEGACY_DESTROY_URL = reverse("v1:mission_control:range-destroy")
LEGACY_GET_RANGE_URL = reverse("v1:mission_control:range-current")

# Small deterministic budgets so exhaustion is reachable in a handful of POSTs.
SMALL_LIMITS = {
    "range": {"actor": {"max": 1, "window": 60}, "fleet": {"max": 2, "window": 60}},
    "ngfw": {"actor": {"max": 1, "window": 60}, "fleet": {"max": 2, "window": 60}},
}


def _enabled(limits=None):
    """Return an override_settings enabling the limiter with the given budgets."""
    return override_settings(LAUNCH_RATE_LIMIT_ENABLED=True, LAUNCH_RATE_LIMITS=limits or SMALL_LIMITS)


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    """Isolate the process-global LocMem admission counter between tests."""
    caches["launch_rate_limit"].clear()
    yield
    caches["launch_rate_limit"].clear()


def _json(response):
    return json.loads(response.content)


def _post_launch(client, url=LEGACY_LAUNCH_URL, body=None):
    return client.post(url, data=json.dumps(body or {}), content_type="application/json")


def _token_client(user, *granted):
    _, raw = ApiToken.create_token(name="rl-test", created_by=user, scopes=list(granted))
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return api


class TestActorBudget:
    """Per-actor budget: one user cannot exceed its own launch allowance."""

    def test_second_launch_by_same_actor_is_throttled_legacy(self, authenticated_client):
        client, _ = authenticated_client(email="rl-actor-legacy@example.com")
        with _enabled():
            first = _post_launch(client)
            second = _post_launch(client)

        # First POST is admitted (reaches the serializer, which rejects the
        # empty body with 400 — proving the token was charged pre-validation).
        assert first.status_code == 400
        # Second POST exceeds the actor budget and is throttled before the view.
        assert second.status_code == 429
        # Legacy route flattens the throttle envelope to a plain string.
        assert "throttl" in _json(second)["error"]["message"].lower()
        assert second.headers.get("Retry-After") is not None

    def test_second_launch_by_same_actor_is_throttled_canonical(self, authenticated_client):
        _, user = authenticated_client(email="rl-actor-canonical@example.com")
        token = _token_client(user, scopes.MISSION_CONTROL_RANGE_READ, scopes.MISSION_CONTROL_RANGE_WRITE)
        with _enabled():
            first = token.post(CANONICAL_LAUNCH_URL, {}, format="json")
            second = token.post(CANONICAL_LAUNCH_URL, {}, format="json")

        assert first.status_code == 400
        assert second.status_code == 429
        # Canonical route keeps the structured error envelope.
        body = second.json()
        assert body["error"]["code"] == "throttled"
        assert second.headers.get("Retry-After") is not None

    def test_session_and_token_share_one_actor_budget(self, authenticated_client):
        # The API-token actor resolves to token.created_by, so session + token
        # traffic for the same owner MUST draw from one budget (preflight).
        session_client, user = authenticated_client(email="rl-shared@example.com")
        token = _token_client(user, scopes.MISSION_CONTROL_RANGE_READ, scopes.MISSION_CONTROL_RANGE_WRITE)
        with _enabled():
            via_session = _post_launch(session_client)
            via_token = token.post(CANONICAL_LAUNCH_URL, {}, format="json")

        assert via_session.status_code == 400
        assert via_token.status_code == 429


class TestFleetBudget:
    """Fleet budget: distinct users each within their actor budget still hit a
    shared system-wide cap (the actual cascade guard)."""

    def test_distinct_actors_exhaust_fleet_budget(self, authenticated_client):
        # actor max=1, fleet max=2: three different users, each within its own
        # actor budget, exhaust the fleet on the third.
        clients = [authenticated_client(email=f"rl-fleet-{i}@example.com")[0] for i in range(3)]
        with _enabled():
            statuses = [_post_launch(c).status_code for c in clients]

        assert statuses[0] == 400  # admitted (empty body -> serializer 400)
        assert statuses[1] == 400  # admitted
        assert statuses[2] == 429  # fleet budget exhausted


class TestBudgetIndependence:
    def test_range_and_ngfw_budgets_are_independent(self, authenticated_client):
        # Exhaust the range fleet, then NGFW is still admitted (separate counter).
        range_clients = [authenticated_client(email=f"rl-indep-r{i}@example.com")[0] for i in range(3)]
        _, ngfw_user = authenticated_client(email="rl-indep-ngfw@example.com")
        ngfw_token = _token_client(ngfw_user, scopes.MISSION_CONTROL_NGFW_READ, scopes.MISSION_CONTROL_NGFW_WRITE)
        with _enabled():
            range_statuses = [_post_launch(c).status_code for c in range_clients]
            ngfw_status = ngfw_token.post(CANONICAL_NGFW_URL, {}, format="json").status_code

        assert range_statuses[2] == 429  # range fleet exhausted
        # NGFW draws on its own budget: not throttled (a serializer/validation
        # rejection is fine; the point is it is NOT 429).
        assert ngfw_status != 429


class TestRejectedRequestSideEffects:
    def test_throttled_launch_never_reaches_cms(self, authenticated_client, make_agent, hydratable_scenario):
        # actor max=1: the first VALID launch creates a real range; the second
        # is throttled (429) BEFORE CMS — proven by 429 (not the 400 "active
        # range" that only CMS raises) and by no second range row.
        client, user = authenticated_client(email="rl-nocms@example.com")
        agent = make_agent(user)
        body = {"agent_id": agent.id, "scenario": hydratable_scenario.scenario_id}
        with _enabled():
            first = _post_launch(client, body=body)
            assert first.status_code == 200
            provisions_after_first = AuditLog.objects.filter(action=AuditAction.PROVISION).count()
            second = _post_launch(client, body=body)

        # 429 (NOT the 400 "active range" that only cms_create_range raises)
        # proves the throttle short-circuits before CMS; no second range row and
        # no new provision audit confirm the rejected request had no side effects.
        assert second.status_code == 429
        assert Range.objects.count() == 1
        assert AuditLog.objects.filter(action=AuditAction.PROVISION).count() == provisions_after_first


class TestBackendFailureFailsClosed:
    def test_admission_backend_error_fails_closed_with_503(self, authenticated_client):
        client, _ = authenticated_client(email="rl-503@example.com")
        cache = caches["launch_rate_limit"]
        with _enabled(), patch.object(cache, "incr", side_effect=RuntimeError("redis down")):
            response = _post_launch(client)

        # A limiter-backend outage must fail closed for launch, not silently
        # admit. 503 (not 429) with a bounded Retry-After.
        assert response.status_code == 503
        assert response.headers.get("Retry-After") is not None


class TestRecoveryAndDisable:
    def test_counter_reset_readmits(self, authenticated_client):
        client, _ = authenticated_client(email="rl-recover@example.com")
        with _enabled():
            assert _post_launch(client).status_code == 400  # admitted
            assert _post_launch(client).status_code == 429  # exhausted
            caches["launch_rate_limit"].clear()  # simulate window expiry
            assert _post_launch(client).status_code == 400  # readmitted

    def test_disabled_flag_bypasses_limiter(self, authenticated_client):
        client, _ = authenticated_client(email="rl-disabled@example.com")
        with override_settings(LAUNCH_RATE_LIMIT_ENABLED=False, LAUNCH_RATE_LIMITS=SMALL_LIMITS):
            statuses = [_post_launch(client).status_code for _ in range(5)]

        assert 429 not in statuses


class TestUnthrottledEndpoints:
    """Only the two launch endpoints are throttled; lifecycle/read endpoints are
    not (preflight: destroy/cancel/read must stay available)."""

    def test_destroy_is_not_throttled(self, authenticated_client):
        client, _ = authenticated_client(email="rl-destroy@example.com")
        body = {"request_id": "00000000-0000-0000-0000-000000000000"}
        with _enabled():
            statuses = [
                client.post(LEGACY_DESTROY_URL, data=json.dumps(body), content_type="application/json").status_code
                for _ in range(4)
            ]
        assert 429 not in statuses

    def test_read_range_is_not_throttled(self, authenticated_client):
        client, _ = authenticated_client(email="rl-read@example.com")
        with _enabled():
            statuses = [client.get(LEGACY_GET_RANGE_URL).status_code for _ in range(4)]
        assert 429 not in statuses


class TestCacheConfigBuilder:
    """Unit tests for the launch_rate_limit cache CONFIG (no live Redis)."""

    def test_locmem_when_redis_host_unset(self):
        from config._redis import build_launch_rate_limit_cache

        cfg = build_launch_rate_limit_cache({})
        assert cfg["BACKEND"] == "django.core.cache.backends.locmem.LocMemCache"

    def test_plaintext_redis_uses_distinct_db(self):
        from config._redis import build_launch_rate_limit_cache

        cfg = build_launch_rate_limit_cache({"REDIS_HOST": "10.0.0.20", "REDIS_PORT": "6379"})
        assert cfg["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
        # Distinct logical DB from the Channels layer (which uses /0).
        assert cfg["LOCATION"] == "redis://10.0.0.20:6379/1"
        assert cfg["KEY_PREFIX"]

    def test_tls_pem_carries_ca_data(self):
        from config._redis import build_launch_rate_limit_cache

        ca_pem = "-----BEGIN CERTIFICATE-----\nMIIBfake==\n-----END CERTIFICATE-----\n"
        cfg = build_launch_rate_limit_cache(
            {
                "REDIS_HOST": "10.0.0.20",
                "REDIS_PORT": "6378",
                "REDIS_TLS": "true",
                "REDIS_PASSWORD": "tok",
                "REDIS_CA_PEM": ca_pem,
            }
        )
        assert cfg["LOCATION"] == "rediss://:tok@10.0.0.20:6378/1"
        assert cfg["OPTIONS"]["ssl_cert_reqs"] == "required"
        assert cfg["OPTIONS"]["ssl_ca_data"] == ca_pem

    def test_tls_system_verifies_hostname_without_ca(self):
        from config._redis import build_launch_rate_limit_cache

        cfg = build_launch_rate_limit_cache(
            {
                "REDIS_HOST": "10.0.0.20",
                "REDIS_TLS": "true",
                "REDIS_CA_MODE": "system",
                "REDIS_PASSWORD": "tok",
            }
        )
        assert cfg["LOCATION"].startswith("rediss://:tok@10.0.0.20:6379/1")
        assert cfg["OPTIONS"]["ssl_cert_reqs"] == "required"
        assert cfg["OPTIONS"]["ssl_check_hostname"] is True
        assert "ssl_ca_data" not in cfg["OPTIONS"]

    def test_tls_without_password_fails_closed(self):
        from django.core.exceptions import ImproperlyConfigured

        from config._redis import build_launch_rate_limit_cache

        with pytest.raises(ImproperlyConfigured, match="REDIS_PASSWORD"):
            build_launch_rate_limit_cache({"REDIS_HOST": "10.0.0.20", "REDIS_TLS": "true"})


class _FakeRedisClient:
    def __init__(self) -> None:
        self.eval_calls: list[tuple] = []

    def eval(self, script, numkeys, *args):
        self.eval_calls.append((script, numkeys, args))
        return 1


class _FakeRedisCache:
    """Minimal stand-in for Django's RedisCache: exposes a raw client via
    ``_cache.get_client`` and forbids the portable add()/incr() path."""

    version = 1

    def __init__(self, client: _FakeRedisClient) -> None:
        self._cache = type("Inner", (), {"get_client": staticmethod(lambda key, write=False: client)})()

    def make_key(self, key, version=None):
        return f"px:{version}:{key}"

    def add(self, *args, **kwargs):
        raise AssertionError("Redis-backed _consume must not use add()")

    def incr(self, *args, **kwargs):
        raise AssertionError("Redis-backed _consume must not use incr()")


class TestAtomicRedisConsume:
    """The Redis path must consume a token with one atomic INCR+EXPIRE script
    (issue #322 codex finding), never a separate add()+incr() that leaves a
    TTL-less key at the expiry boundary."""

    def test_redis_backed_consume_uses_atomic_lua_with_ttl(self):
        from shared.rate_limit import _LUA_INCR_EXPIRE, consume_fixed_window

        client = _FakeRedisClient()
        count = consume_fixed_window(_FakeRedisCache(client), "launch-rl:range:fleet", 60)

        assert count == 1
        assert len(client.eval_calls) == 1
        script, numkeys, args = client.eval_calls[0]
        assert script == _LUA_INCR_EXPIRE
        assert numkeys == 1
        # Made key (prefix-applied) + the window TTL are passed to the script,
        # so every counter creation carries the configured expiry.
        assert args == ("px:1:launch-rl:range:fleet", 60)
        # The EXPIRE guard covers both first-write and a TTL-less key (self-heal).
        assert "EXPIRE" in _LUA_INCR_EXPIRE
        assert "TTL" in _LUA_INCR_EXPIRE
