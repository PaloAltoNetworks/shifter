"""Validated run configuration for one harness invocation.

This is the harness's first security gate. It is deliberately separate from any
Django settings schema, Terraform variable, or Kubernetes value: it is the
load-client's own contract. Validation runs at startup and raises before any
load is generated, so a misconfigured target or a production host is refused up
front rather than discovered mid-run.

No secret-bearing field lives here. Credentials come from the 0600 actor
manifest (see ``event_load_harness.auth``); run config carries only non-secret
paths, labels, and numbers that are safe to pass on argv and echo in a report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

METRIC_SOURCES = ("client-only", "aws")
ACTOR_SOURCES = ("dev-login", "manifest", "ctfd-csv")
_LOCALHOST_HOSTS = ("localhost", "127.0.0.1", "::1")


class ConfigError(ValueError):
    """Raised when a run configuration is invalid. Fail before generating load."""


@dataclass(frozen=True)
class RunConfig:
    target_url: str
    environment: str
    profile: str
    concurrency: int
    ramp_seconds: float
    duration_seconds: float
    actor_source: str
    metric_source: str
    report_path: str
    actor_manifest_path: str | None = None
    region: str | None = None
    confirm_host: str | None = None
    allow_insecure_localhost: bool = False
    allow_production: bool = False
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> RunConfig:
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        kwargs = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known}
        try:
            cfg = cls(**kwargs, extra=extra)
        except TypeError as exc:  # missing required key
            raise ConfigError(f"invalid run config: {exc}") from exc
        cfg.validate()
        return cfg

    def validate(self) -> None:
        self._validate_target()
        self._validate_environment()
        self._validate_host_acknowledged()
        self._validate_numbers()
        self._validate_enums()

    def _validate_target(self) -> None:
        parsed = urlparse(self.target_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ConfigError(f"target_url must be a parseable http(s) URL, got {self.target_url!r}")
        if parsed.scheme == "http":
            is_localhost = parsed.hostname in _LOCALHOST_HOSTS
            if not (is_localhost and self.allow_insecure_localhost):
                raise ConfigError(
                    "target_url must use https; plain http is allowed only for localhost "
                    "with allow_insecure_localhost=true (tunnel profile)"
                )

    def _validate_environment(self) -> None:
        if not self.environment:
            raise ConfigError("environment label is required")
        # Refuse on a production signal from EITHER the operator-supplied label OR the
        # target host. The label alone is bypassable by relabeling a prod-host run as
        # 'dev'; tying the gate to the parsed host as well closes that bypass.
        host = (urlparse(self.target_url).hostname or "").lower()
        prod_signal = "prod" in self.environment.lower() or "prod" in host
        if prod_signal and not self.allow_production:
            raise ConfigError(
                "target looks like production (environment label or host contains 'prod'); "
                "refusing without allow_production=true. Generating event-scale load against "
                "production is an intentional, explicit opt-in."
            )

    def _validate_host_acknowledged(self) -> None:
        # Positive gate: the harness cannot tell dev from prod by hostname (e.g.
        # `app.example.com` could be production), so a "looks-safe" heuristic is not
        # enough. Any non-localhost target must be explicitly acknowledged — either
        # allow_production for a prod target, or confirm_host matching the exact host.
        # This makes loading an unintended host an intentional refusal, not a default.
        host = (urlparse(self.target_url).hostname or "").lower()
        if host in _LOCALHOST_HOSTS or self.allow_production:
            return
        if not self.confirm_host or self.confirm_host.strip().lower() != host:
            raise ConfigError(
                f"target host {host!r} is not acknowledged; pass confirm_host='{host}' to confirm "
                "the exact target, or allow_production=true for a production target. This positive "
                "gate prevents accidentally load-testing an unintended (e.g. production) host."
            )

    def _validate_numbers(self) -> None:
        if self.concurrency <= 0:
            raise ConfigError("concurrency must be > 0")
        if self.ramp_seconds < 0:
            raise ConfigError("ramp_seconds must be >= 0")
        if self.duration_seconds <= 0:
            raise ConfigError("duration_seconds must be > 0")

    def _validate_enums(self) -> None:
        if self.metric_source not in METRIC_SOURCES:
            raise ConfigError(f"metric_source must be one of {METRIC_SOURCES}, got {self.metric_source!r}")
        if self.actor_source not in ACTOR_SOURCES:
            raise ConfigError(f"actor_source must be one of {ACTOR_SOURCES}, got {self.actor_source!r}")
        if self.actor_source == "manifest" and not self.actor_manifest_path:
            raise ConfigError("actor_source 'manifest' requires actor_manifest_path")
        if self.actor_source == "ctfd-csv" and not self.actor_manifest_path:
            raise ConfigError("actor_source 'ctfd-csv' requires actor_manifest_path (the CSV path)")
