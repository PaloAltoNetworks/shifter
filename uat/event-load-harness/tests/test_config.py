"""Run config must validate and FAIL before any load is generated.

This is the harness's first security gate: only explicit https targets, an
intentional refusal for production/unknown hosts, and bounded run parameters.
"""

import pytest

from event_load_harness.config import ConfigError, RunConfig


def _base(**overrides):
    data = {
        "target_url": "https://dev.example.com",
        "environment": "dev",
        "profile": "portal-core",
        "concurrency": 50,
        "ramp_seconds": 30,
        "duration_seconds": 120,
        "actor_source": "manifest",
        "actor_manifest_path": "/tmp/actors.toml",  # noqa: S108 - test value, not a real path
        "metric_source": "client-only",
        "report_path": "out/envelope.md",
        "confirm_host": "dev.example.com",
    }
    data.update(overrides)
    return data


def test_valid_https_config_builds():
    cfg = RunConfig.from_dict(_base())
    assert cfg.target_url == "https://dev.example.com"
    assert cfg.concurrency == 50
    assert cfg.metric_source == "client-only"


def test_http_non_localhost_is_rejected():
    with pytest.raises(ConfigError, match="https"):
        RunConfig.from_dict(_base(target_url="http://dev.example.com"))


def test_http_localhost_allowed_only_with_explicit_tunnel_flag():
    # Rejected by default ...
    with pytest.raises(ConfigError):
        RunConfig.from_dict(_base(target_url="http://localhost:8000"))
    # ... allowed when the operator opts into the tunnel profile.
    cfg = RunConfig.from_dict(_base(target_url="http://localhost:8000", allow_insecure_localhost=True))
    assert cfg.target_url == "http://localhost:8000"


def test_http_insecure_flag_does_not_allow_remote_host():
    with pytest.raises(ConfigError):
        RunConfig.from_dict(_base(target_url="http://dev.example.com", allow_insecure_localhost=True))


def test_unparseable_url_is_rejected():
    with pytest.raises(ConfigError):
        RunConfig.from_dict(_base(target_url="not-a-url"))


def test_production_looking_environment_refused_without_explicit_optin():
    with pytest.raises(ConfigError, match="production"):
        RunConfig.from_dict(_base(environment="production", target_url="https://app.example.com"))
    cfg = RunConfig.from_dict(
        _base(environment="production", target_url="https://app.example.com", allow_production=True)
    )
    assert cfg.environment == "production"


def test_production_host_refused_even_with_nonprod_label():
    # The label-only gate was bypassable by relabeling a prod-host run as 'dev';
    # the gate now also inspects the parsed target host.
    with pytest.raises(ConfigError, match="production"):
        RunConfig.from_dict(_base(environment="dev", target_url="https://portal.prod.example.com"))
    cfg = RunConfig.from_dict(
        _base(environment="dev", target_url="https://portal.prod.example.com", allow_production=True)
    )
    assert cfg.target_url == "https://portal.prod.example.com"


def test_nonlocalhost_host_requires_explicit_confirmation():
    # A real production host need not contain 'prod'; the positive gate refuses any
    # unacknowledged non-localhost target so it can't be hit by accident.
    with pytest.raises(ConfigError, match="not acknowledged"):
        RunConfig.from_dict(_base(target_url="https://app.example.com", confirm_host=None))


def test_confirm_host_must_match_target_host():
    with pytest.raises(ConfigError, match="not acknowledged"):
        RunConfig.from_dict(_base(target_url="https://app.example.com", confirm_host="other.example.com"))
    cfg = RunConfig.from_dict(_base(target_url="https://app.example.com", confirm_host="app.example.com"))
    assert cfg.target_url == "https://app.example.com"


def test_allow_production_satisfies_host_acknowledgement():
    cfg = RunConfig.from_dict(_base(target_url="https://app.example.com", confirm_host=None, allow_production=True))
    assert cfg.allow_production is True


def test_numeric_bounds():
    with pytest.raises(ConfigError):
        RunConfig.from_dict(_base(concurrency=0))
    with pytest.raises(ConfigError):
        RunConfig.from_dict(_base(ramp_seconds=-1))
    with pytest.raises(ConfigError):
        RunConfig.from_dict(_base(duration_seconds=0))


def test_unknown_enums_rejected():
    with pytest.raises(ConfigError):
        RunConfig.from_dict(_base(metric_source="prometheus"))
    with pytest.raises(ConfigError):
        RunConfig.from_dict(_base(actor_source="ldap"))


def test_manifest_source_requires_manifest_path():
    with pytest.raises(ConfigError, match="manifest"):
        RunConfig.from_dict(_base(actor_source="manifest", actor_manifest_path=None))


def test_config_holds_no_secret_fields():
    # Credentials live in the 0600 actor manifest, never in run config; this
    # guards against a future field leaking a secret into argv/TOML/logs.
    cfg = RunConfig.from_dict(_base())
    rendered = repr(cfg).lower()
    for forbidden in ("password", "token", "secret", "cookie"):
        assert forbidden not in rendered
