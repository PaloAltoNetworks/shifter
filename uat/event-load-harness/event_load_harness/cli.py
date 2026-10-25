"""One-command entrypoint: orchestrate load -> metrics -> report.

The operator-facing contract is a single bounded run against one explicit target
environment. ``build_parser`` / ``config_from_args`` are the deterministic,
unit-tested part; ``main`` wires the live components together and is exercised by
operator runs against a deployed environment.

Secrets never appear on argv: credentials come from the 0600 actor manifest, and
only non-secret paths/labels/numbers are passed as flags.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import subprocess
import sys
import tomllib
from pathlib import Path

from installation.capacity_profiles_gcp import resolve_capacity_profile

from event_load_harness import auth as auth_mod
from event_load_harness.auth_http import make_authenticator
from event_load_harness.capacity_gate import (
    CapacityGateBudget,
    evaluate_capacity_gate,
    render_capacity_gate_section,
)
from event_load_harness.config import ConfigError, RunConfig
from event_load_harness.guacamole_gate import GuacamoleGateExecutor, run_guacamole_gate
from event_load_harness.metrics import build_adapter
from event_load_harness.profiles import get_profile, list_profiles
from event_load_harness.report import (
    DeploymentShape,
    RunMeta,
    derive_conclusion,
    render_envelope,
)
from event_load_harness.routes import LiveRouteExecutor
from event_load_harness.runner import run_load

_STR_OPTS = (
    "target_url",
    "environment",
    "profile",
    "actor_source",
    "actor_manifest_path",
    "metric_source",
    "region",
    "report_path",
    "confirm_host",
    "capacity_profile_id",
)
_NUM_OPTS = ("concurrency", "ramp_seconds", "duration_seconds")
_AWS_TARGET_OPTS = (
    ("alb", "aws_alb"),
    ("target_group", "aws_target_group"),
    ("asg", "aws_asg"),
    ("rds_instance", "aws_rds"),
    ("redis_cluster", "aws_redis"),
    ("name_prefix", "aws_name_prefix"),
)
_GCP_TARGET_OPTS = (
    ("project_id", "gcp_project"),
    ("cluster", "gcp_cluster"),
    ("namespace", "gcp_namespace"),
    ("sql_instance", "gcp_sql_instance"),
    ("redis_instance", "gcp_redis_instance"),
    ("backend_name", "gcp_backend_name"),
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="event-load-harness",
        description="Drive a deployed Shifter portal and render a concurrency-envelope report (#926).",
    )
    p.add_argument("--config", help="Path to a TOML run-config file (flags override its values).")
    p.add_argument("--target-url", dest="target_url", help="Deployed target base URL (https required).")
    p.add_argument(
        "--confirm-host",
        dest="confirm_host",
        help="Acknowledge the exact target host (must match the target URL host) for any non-localhost target.",
    )
    p.add_argument("--environment", help="Environment label, e.g. 'dev'.")
    p.add_argument("--profile", help="Traffic profile name (default: portal-core).")
    p.add_argument(
        "--capacity-profile-id",
        dest="capacity_profile_id",
        help="Versioned shared-service capacity identity; the strict gate runs that tier's authored budget.",
    )
    p.add_argument("--concurrency", type=int, help="Number of concurrent virtual users.")
    p.add_argument("--ramp-seconds", dest="ramp_seconds", type=float, help="Linear ramp-up window.")
    p.add_argument("--duration-seconds", dest="duration_seconds", type=float, help="Steady-state duration.")
    p.add_argument(
        "--actor-source",
        dest="actor_source",
        choices=("dev-login", "manifest", "ctfd-csv"),
        help="How to obtain identities.",
    )
    p.add_argument(
        "--actor-manifest",
        dest="actor_manifest_path",
        help="Path to a 0600 TOML actor manifest (for actor-source=manifest).",
    )
    p.add_argument(
        "--actor-count",
        dest="actor_count",
        type=int,
        help="Number of dev-login actors to generate (default: concurrency).",
    )
    p.add_argument(
        "--metric-source",
        dest="metric_source",
        choices=("client-only", "aws", "gcp"),
        help="Provider metric adapter (default: client-only).",
    )
    p.add_argument("--region", help="Cloud region for the provider metric adapter.")
    p.add_argument("--report-path", dest="report_path", help="Where to write the envelope markdown.")
    p.add_argument("--aws-alb", dest="aws_alb", help="ALB LoadBalancer dimension (aws metric source).")
    p.add_argument(
        "--aws-target-group",
        dest="aws_target_group",
        help="ALB TargetGroup dimension for RequestCountPerTarget, the portal scale-out signal (aws metric source).",
    )
    p.add_argument("--aws-asg", dest="aws_asg", help="AutoScalingGroupName (aws metric source).")
    p.add_argument("--aws-rds", dest="aws_rds", help="DBInstanceIdentifier (aws metric source).")
    p.add_argument("--aws-redis", dest="aws_redis", help="CacheClusterId (aws metric source).")
    p.add_argument(
        "--aws-name-prefix",
        dest="aws_name_prefix",
        help="Portal NamePrefix dimension for Shifter/PortalCapacity worker/terminal gauges (aws metric source).",
    )
    p.add_argument("--gcp-project", dest="gcp_project", help="GCP project id for Cloud Monitoring reads.")
    p.add_argument("--gcp-cluster", dest="gcp_cluster", help="GKE cluster name for workload metrics.")
    p.add_argument("--gcp-namespace", dest="gcp_namespace", help="Kubernetes namespace (default shifter-platform).")
    p.add_argument("--gcp-sql-instance", dest="gcp_sql_instance", help="Cloud SQL instance id.")
    p.add_argument("--gcp-redis-instance", dest="gcp_redis_instance", help="Memorystore instance id.")
    p.add_argument("--gcp-backend-name", dest="gcp_backend_name", help="GCLB backend service name.")
    p.add_argument(
        "--allow-insecure-localhost",
        dest="allow_insecure_localhost",
        action="store_true",
        help="Permit http://localhost targets (tunnel profile).",
    )
    p.add_argument(
        "--allow-production",
        dest="allow_production",
        action="store_true",
        help="Explicitly permit a production-looking target (intentional opt-in).",
    )
    p.add_argument(
        "--list-profiles", dest="list_profiles", action="store_true", help="List available traffic profiles and exit."
    )
    return p


def config_from_args(args: argparse.Namespace) -> RunConfig:
    base: dict = {}
    if args.config:
        with open(args.config, "rb") as handle:
            base = tomllib.load(handle)

    overlay: dict = {}
    for name in (*_STR_OPTS, *_NUM_OPTS):
        value = getattr(args, name, None)
        if value is not None:
            overlay[name] = value
    if getattr(args, "actor_count", None) is not None:
        overlay["actor_count"] = args.actor_count
    if getattr(args, "allow_insecure_localhost", False):
        overlay["allow_insecure_localhost"] = True
    if getattr(args, "allow_production", False):
        overlay["allow_production"] = True

    aws_targets = {field: getattr(args, opt) for field, opt in _AWS_TARGET_OPTS if getattr(args, opt, None)}
    if aws_targets:
        overlay["aws_targets"] = aws_targets
    gcp_targets = {field: getattr(args, opt) for field, opt in _GCP_TARGET_OPTS if getattr(args, opt, None)}
    if gcp_targets:
        gcp_targets.setdefault("namespace", "shifter-platform")
        overlay["gcp_targets"] = gcp_targets

    merged = {**base, **overlay}
    merged.setdefault("profile", "portal-core")
    merged.setdefault("metric_source", "client-only")
    return RunConfig.from_dict(merged)


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha or None


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_actors(config: RunConfig) -> list:
    if config.actor_source == "manifest":
        return auth_mod.load_actor_manifest(config.actor_manifest_path)
    if config.actor_source == "dev-login":
        count = config.extra.get("actor_count") or config.concurrency
        return auth_mod.dev_login_actors(count)
    if config.actor_source == "ctfd-csv":
        return auth_mod.ctfd_csv_actors(config.actor_manifest_path)
    raise ConfigError(f"unsupported actor_source {config.actor_source!r}")


async def _run(config: RunConfig) -> int:
    profile = get_profile(config.profile)
    actors = _build_actors(config)
    strict_gate = profile.name == "guacamole-event-gate"
    strict_capacity = resolve_capacity_profile(str(config.capacity_profile_id)) if strict_gate else None
    executor = (
        GuacamoleGateExecutor(
            config.target_url,
            hold_seconds=config.duration_seconds,
            bootstrap_timeout=strict_capacity.gate.bootstrap_timeout_seconds,
            connect_timeout=strict_capacity.gate.bootstrap_timeout_seconds,
        )
        if strict_gate
        else LiveRouteExecutor(config.target_url)
    )
    try:
        print(f"Authenticating {len(actors)} actor(s) and discovering range targets ...")
        await executor.setup(actors, make_authenticator(require_identity_platform=strict_gate))

        started = _now()
        print(
            f"Running profile '{profile.name}' at concurrency {config.concurrency} "
            f"for {config.duration_seconds}s (ramp {config.ramp_seconds}s) ..."
        )
        aggregator = (
            await run_guacamole_gate(config, actors, executor)
            if strict_gate
            else await run_load(config, profile, actors, executor)
        )
        ended = _now()
    finally:
        await executor.aclose()

    metric_targets = _metric_targets(config)
    if strict_gate:
        settle_seconds = strict_capacity.gate.telemetry_settle_seconds
        if settle_seconds:
            print(f"Waiting {settle_seconds}s for bounded Cloud Monitoring ingestion ...")
            await asyncio.sleep(settle_seconds)
    adapter = build_adapter(config.metric_source, config.region, metric_targets)
    metrics = adapter.collect(started, ended)
    summary = aggregator.summary()
    gate_verdict = None
    if strict_gate:
        capacity_profile_id = str(config.capacity_profile_id)
        gate_verdict = evaluate_capacity_gate(CapacityGateBudget.from_profile_id(capacity_profile_id), summary, metrics)
    report = render_envelope(
        config=config,
        run_meta=RunMeta(started_at=started, ended_at=ended, git_sha=_git_sha()),
        deployment=DeploymentShape(),  # operator fills via the report or a future discovery probe
        stats_summary=summary,
        metrics=metrics,
        conclusion=derive_conclusion(config, summary),
    )
    if gate_verdict is not None:
        report += "\n" + render_capacity_gate_section(str(config.capacity_profile_id), gate_verdict)

    out_path = Path(config.report_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Wrote envelope report to {out_path}")
    print(f"Totals: {summary['totals']}")
    return 0 if gate_verdict is None or gate_verdict.passed else 1


def _metric_targets(config: RunConfig) -> dict[str, str]:
    if config.metric_source == "aws":
        return dict(config.extra.get("aws_targets", {}))
    if config.metric_source == "gcp":
        targets = dict(config.extra.get("gcp_targets", {}))
        if config.profile == "guacamole-event-gate":
            capacity = resolve_capacity_profile(str(config.capacity_profile_id))
            targets.setdefault("sql_connection_budget", str(capacity.cloud_sql.connection_budget))
            targets.setdefault("redis_connection_budget", str(capacity.redis.connection_budget))
        return targets
    return {}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_profiles:
        for name in list_profiles():
            print(name)
        return 0
    try:
        config = config_from_args(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_run(config))
    except (auth_mod.AuthError, NotImplementedError) as exc:
        print(f"run error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
