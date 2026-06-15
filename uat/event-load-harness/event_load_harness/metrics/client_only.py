"""Default metrics adapter: client-measured only, with explicit named gaps.

This is the portable, first-class path. It collects nothing provider-side and
instead enumerates exactly which provider signals are absent, so the report
shows honest gaps rather than a green summary that hides missing evidence. The
client-measured latency/error/close-code evidence (from the load run itself)
lives in the stats summary, not here.
"""

from __future__ import annotations

from event_load_harness.metrics.base import MetricsResult

# Provider signals the report wants but client-only mode cannot supply. Named so
# the envelope's "missing metric" list is explicit, per the preflight.
_MISSING_PROVIDER_SIGNALS = [
    "ALB/ingress p95/p99 latency and 5xx counts (no provider adapter)",
    "ALB active/rejected connection counts (no provider adapter)",
    "Portal EC2/pod CPU and memory (no provider adapter)",
    "RDS connections and CPU (no provider adapter)",
    "Redis CPU/memory/connections (no provider adapter)",
    "Guacamole ECS/pod CPU and task/replica health (no provider adapter)",
    "SQS backlog if worker paths were exercised (no provider adapter)",
]


class ClientOnlyAdapter:
    provider = "client-only"

    def collect(self, window_start: str, window_end: str) -> MetricsResult:
        return MetricsResult(
            provider=self.provider,
            window_start=window_start,
            window_end=window_end,
            metrics={},
            gaps=list(_MISSING_PROVIDER_SIGNALS),
        )
