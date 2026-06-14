"""Tests for the portal ``/health`` readiness endpoint (#477).

Per ``docs/architecture/portal-health-readiness-preflight-477.md`` the public
``/health`` surface must reflect the real ``django-health-check`` DB / cache /
storage probes. The ``HealthCheckMiddleware`` may normalize the Host header so
ALB / ingress-IP probes admit, but it must not create the response. The
public body must stay coarse so a real dependency failure does not leak DSNs,
bucket names, secret IDs, or private hostnames.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from django.test import Client
from health_check.exceptions import ServiceUnavailable
from health_check.plugins import plugin_dir

# A non-secret sentinel used as the forced failure reason in probe-patches.
# Tests use it as a positive control: if the public response surfaces *this*
# string, the response is rendering the probe's raw error text (and would
# also surface real DSNs / hostnames in production).
_FORCED_FAILURE_REASON = "shifter-477-forced-probe-failure"

# Substrings that must never appear in the public ``/health`` body. The list
# tracks the Anti-Patterns block of the #477 preflight.
_FORBIDDEN_LEAK_MARKERS = (
    "postgres://",
    "postgresql://",
    "rediss://",
    "redis://",
    "traceback",
    "stack trace",
    "secret_id=",
    "secret_arn=",
    "aws_secret_",
    "s3://",
    "gs://",
    "arn:aws:secretsmanager",
    ".rds.amazonaws.com",
    ".cache.amazonaws.com",
    ".internal:",
    # Per-probe raw error strings must be replaced with a coarse token before
    # they reach the public body.
    _FORCED_FAILURE_REASON,
)


pytestmark = pytest.mark.django_db


def _get_health(path: str = "/health/", **extra) -> tuple[int, str]:
    """Return (status_code, decoded body) for a GET against ``path``.

    Tests intentionally do not follow redirects: ALB does not follow them
    either, so a 301 here is a regression in the no-trailing-slash path.
    """
    response = Client().get(path, **extra)
    body = response.content.decode("utf-8", errors="replace")
    return response.status_code, body


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_health_returns_200_when_probes_pass():
    status, _ = _get_health("/health/")
    assert status == 200


def test_health_runs_the_real_django_health_check_view():
    """The old middleware short-circuited ``/health`` and returned ``b"OK"``.
    The new behavior must run the real ``django-health-check`` view, so the
    body must contain probe labels rather than the synthetic ``OK`` token.
    """
    status, body = _get_health("/health/", HTTP_ACCEPT="application/json")
    assert status == 200
    # The installed probes are db, cache, storage. At least the DB backend
    # label must appear in the response payload.
    assert "DatabaseBackend" in body, f"expected django-health-check probe labels in /health/ body, got: {body!r}"
    # The hard-coded short-circuit body is exactly b"OK"; ensure we are NOT
    # serving that.
    assert body.strip() != "OK"


def test_health_no_trailing_slash_resolves_without_redirect():
    """ALB tfvars currently set ``health_check_path = "/health"`` (no
    trailing slash). ALB does not follow 301 redirects, so the no-slash
    route must resolve directly to the same view.
    """
    response = Client().get("/health")  # follow=False (default)
    assert response.status_code == 200, (
        f"/health (no trailing slash) returned {response.status_code}; "
        "ALB does not follow 3xx so this must be a direct 200."
    )


# ---------------------------------------------------------------------------
# Dependency probe failure paths
# ---------------------------------------------------------------------------


def _force_probe_failure(target: str):
    return patch(target, side_effect=ServiceUnavailable(_FORCED_FAILURE_REASON))


@pytest.fixture
def health_check_registry():
    """Restore the global django-health-check plugin registry after tests."""
    original_registry = list(plugin_dir._registry)
    try:
        yield plugin_dir._registry
    finally:
        plugin_dir._registry = original_registry


def test_health_returns_non_200_when_db_probe_fails():
    with _force_probe_failure("health_check.db.backends.DatabaseBackend.check_status"):
        status, _ = _get_health("/health/")
    assert status != 200, "DB probe failure must surface as a non-200 /health"


def test_health_returns_non_200_when_cache_probe_fails():
    with _force_probe_failure("health_check.cache.backends.CacheBackend.check_status"):
        status, _ = _get_health("/health/")
    assert status != 200, "cache probe failure must surface as a non-200 /health"


def test_health_returns_non_200_when_storage_probe_fails():
    with _force_probe_failure("health_check.storage.backends.DefaultFileStorageHealthCheck.check_status"):
        status, _ = _get_health("/health/")
    assert status != 200, "storage probe failure must surface as a non-200 /health"


def test_in_memory_channel_layer_does_not_register_redis_probe(settings, health_check_registry):
    from config.health_checks import ChannelLayerRedisHealthCheck, register_channel_layer_redis_health_check

    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    health_check_registry.clear()

    register_channel_layer_redis_health_check()

    assert all(plugin is not ChannelLayerRedisHealthCheck for plugin, _ in health_check_registry)


def test_redis_channel_layer_registers_redis_probe(settings, health_check_registry):
    from config.health_checks import ChannelLayerRedisHealthCheck, register_channel_layer_redis_health_check

    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}}
    health_check_registry.clear()

    register_channel_layer_redis_health_check()

    assert any(plugin is ChannelLayerRedisHealthCheck for plugin, _ in health_check_registry)


def test_redis_channel_layer_registration_is_idempotent(settings, health_check_registry):
    from config.health_checks import ChannelLayerRedisHealthCheck, register_channel_layer_redis_health_check

    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}}
    health_check_registry.clear()

    register_channel_layer_redis_health_check()
    register_channel_layer_redis_health_check()

    assert [plugin for plugin, _ in health_check_registry].count(ChannelLayerRedisHealthCheck) == 1


def test_redis_health_check_uses_installed_health_check_plugin_base():
    from health_check.backends import HealthCheck

    from config.health_checks import ChannelLayerRedisHealthCheck

    assert issubclass(ChannelLayerRedisHealthCheck, HealthCheck)


def test_redis_health_check_probe_uses_sync_bridge():
    from config.health_checks import ChannelLayerRedisHealthCheck, _probe_configured_channel_layer

    runner = Mock()
    with patch("config.health_checks.async_to_sync", return_value=runner) as async_to_sync:
        ChannelLayerRedisHealthCheck()._probe()

    async_to_sync.assert_called_once_with(_probe_configured_channel_layer)
    runner.assert_called_once_with()


def test_health_returns_non_200_when_channel_layer_redis_probe_fails(settings, health_check_registry):
    from config.health_checks import ChannelLayerRedisHealthCheck, register_channel_layer_redis_health_check

    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}}
    health_check_registry.clear()
    register_channel_layer_redis_health_check()

    with patch.object(ChannelLayerRedisHealthCheck, "_probe", side_effect=ServiceUnavailable(_FORCED_FAILURE_REASON)):
        status, body = _get_health("/health/", HTTP_ACCEPT="application/json")

    assert status != 200, "Redis channel-layer probe failure must surface as a non-200 /health"
    assert "ChannelLayerRedisHealthCheck" in body, body
    assert '"unavailable"' in body, body
    lowered = body.lower()
    for marker in _FORBIDDEN_LEAK_MARKERS:
        assert marker not in lowered, f"public /health body leaked sensitive marker {marker!r}: {body!r}"


@pytest.mark.asyncio
async def test_channel_layer_probe_round_trip_uses_configured_layer():
    from config.health_checks import _round_trip

    class FakeChannelLayer:
        def __init__(self):
            self.channel_prefix = None
            self.sent_channel = None
            self.sent_message = None

        async def new_channel(self, prefix: str = "specific") -> str:
            self.channel_prefix = prefix
            return "health.check.test!channel"

        async def send(self, channel: str, message: dict[str, str]) -> None:
            self.sent_channel = channel
            self.sent_message = message

        async def receive(self, channel: str) -> dict[str, str]:
            assert channel == self.sent_channel
            assert self.sent_message is not None
            return self.sent_message

    layer = FakeChannelLayer()

    await _round_trip(layer)

    assert layer.channel_prefix == "health.check"
    assert layer.sent_channel == "health.check.test!channel"
    assert layer.sent_message is not None
    assert layer.sent_message["type"] == "health.check"
    assert layer.sent_message["id"]


@pytest.mark.asyncio
async def test_channel_layer_probe_fails_when_default_layer_is_missing():
    from config.health_checks import _probe_configured_channel_layer

    with patch("config.health_checks.get_channel_layer", return_value=None), pytest.raises(ServiceUnavailable):
        await _probe_configured_channel_layer()


@pytest.mark.asyncio
async def test_channel_layer_probe_fails_on_unexpected_round_trip_response():
    from config.health_checks import _round_trip

    class MismatchedChannelLayer:
        async def new_channel(self, prefix: str = "specific") -> str:
            return "health.check.test!channel"

        async def send(self, channel: str, message: dict[str, str]) -> None:
            return None

        async def receive(self, channel: str) -> dict[str, str]:
            return {"type": "health.check", "id": "different"}

    with pytest.raises(ServiceUnavailable):
        await _round_trip(MismatchedChannelLayer())


# ---------------------------------------------------------------------------
# Host-header admission (ALB / ingress-IP) reaches the real view
# ---------------------------------------------------------------------------


def test_health_with_alb_host_header_reaches_real_view():
    """ALB / GCP ingress probes arrive with the load balancer's internal IP
    as the ``Host`` header. The IP is intentionally NOT in
    ``DJANGO_ALLOWED_HOSTS`` (see
    ``scripts/gcp/render_runtime_env.py:101-107``). The middleware must
    normalize the Host so the real django-health-check view runs — without
    raising ``DisallowedHost`` AND without returning a synthetic ``OK``.
    """
    status, body = _get_health(
        "/health/",
        HTTP_HOST="10.0.1.42",
        HTTP_ACCEPT="application/json",
    )
    assert status == 200
    assert "DatabaseBackend" in body, "ALB-IP Host probe must reach the real view (probe labels in body)"


def test_health_with_alb_host_header_no_trailing_slash():
    """Combination of the two regression vectors: ALB tfvars probe (no
    trailing slash, internal-IP Host)."""
    status, body = _get_health(
        "/health",
        HTTP_HOST="10.0.1.42",
        HTTP_ACCEPT="application/json",
    )
    assert status == 200, body
    # Positive structural assertion: the ALB+no-slash path must reach the real
    # django-health-check view, not a synthetic short-circuit. A regression to
    # JsonResponse({"status": "ok"}) would still 200 but would drop the probe
    # labels — guard against that here.
    assert "DatabaseBackend" in body, (
        f"ALB-IP + no-trailing-slash probe must reach the real view (probe labels expected in body), got: {body!r}"
    )


def test_health_is_not_redirected_when_ssl_redirect_enabled(settings):
    """Production enables ``SECURE_SSL_REDIRECT``. ALB health checks are plain
    HTTP and do not send ``X-Forwarded-Proto: https``, so `/health` must be
    exempt from HTTPS redirects and still run the real readiness probes.
    """
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_REDIRECT_EXEMPT = [r"^health/?$"]

    status, body = _get_health(
        "/health",
        HTTP_HOST="10.0.1.42",
        HTTP_ACCEPT="application/json",
    )

    assert status == 200, body
    assert "DatabaseBackend" in body


# ---------------------------------------------------------------------------
# Coarse public body — no DSN / hostname / secret-ID / stack-trace leaks
# ---------------------------------------------------------------------------


def test_health_failure_body_is_coarse_on_db_failure():
    with _force_probe_failure("health_check.db.backends.DatabaseBackend.check_status"):
        _, body = _get_health("/health/", HTTP_ACCEPT="application/json")
    # Positive structural assertion: the body must still expose the probe
    # label paired with the coarse "unavailable" token. Without this, a
    # regression to JsonResponse({"status": "unhealthy"}) would pass the
    # forbidden-marker scan below (no DSNs in {"status": "unhealthy"}) yet
    # silently drop the per-probe surface the #477 preflight requires.
    assert '"DatabaseBackend"' in body, f"expected DatabaseBackend probe label in coarse body, got: {body!r}"
    assert '"unavailable"' in body, f"expected coarse 'unavailable' token in body, got: {body!r}"
    lowered = body.lower()
    for marker in _FORBIDDEN_LEAK_MARKERS:
        assert marker not in lowered, f"public /health body leaked sensitive marker {marker!r}: {body!r}"


def test_health_failure_body_is_coarse_on_cache_failure():
    with _force_probe_failure("health_check.cache.backends.CacheBackend.check_status"):
        _, body = _get_health("/health/", HTTP_ACCEPT="application/json")
    # Positive structural assertion: the cache-failure body must still carry
    # the cache probe label and the coarse "unavailable" token. The label
    # rendered by django-health-check for the legacy CacheBackend plugin is
    # ``Cache(alias='default')``. See the db-failure test's note on why a
    # forbidden-marker-only scan is not sufficient.
    assert "Cache(alias=" in body, f"expected cache probe label in coarse body, got: {body!r}"
    assert '"unavailable"' in body, f"expected coarse 'unavailable' token in body, got: {body!r}"
    lowered = body.lower()
    for marker in _FORBIDDEN_LEAK_MARKERS:
        assert marker not in lowered, body
