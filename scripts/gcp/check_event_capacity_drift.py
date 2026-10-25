#!/usr/bin/env python3
"""Read-only drift inspection for the selected GCP event-capacity profile.

Only allowlisted capacity fields are retained from provider/Kubernetes JSON.
Raw responses, Terraform state, Secrets, environment variables, addresses, and
credentials are never written to the report.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - fixed argv, shell is never used
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DriftInputError(ValueError):
    """Raised when desired or observed evidence is incomplete or malformed."""


@dataclass(frozen=True)
class Drift:
    resource: str
    field: str
    desired: object
    observed: object


_NON_SHRINKING_FLOOR_FIELDS = frozenset({("terraform", "capacity.cloud_sql_disk_size_gb")})
# The shared OpenVPN pool (#2480) exists only where the tenant opted in; an
# installation without it carries no pool evidence to compare.
_VPN_POOL_FIELD_PREFIX = "capacity.vpn_pool_"


def compare_capacity_state(desired: dict[str, object], observed: dict[str, object]) -> list[Drift]:
    """Compare allowlisted desired/observed fields and fail on missing evidence."""
    drifts: list[Drift] = []
    desired_profile = _required(desired, "profile_id", "desired")
    observed_profile = _required(observed, "profile_id", "observed")
    if desired_profile != observed_profile:
        drifts.append(Drift("profile", "profile_id", desired_profile, observed_profile))

    for section in ("terraform", "kubernetes"):
        wanted = _mapping(desired, section, "desired")
        actual = _mapping(observed, section, "observed")
        for field, wanted_value in sorted(wanted.items()):
            if field.startswith(_VPN_POOL_FIELD_PREFIX) and observed.get("vpn_pool") == "absent":
                continue
            if field not in actual:
                raise DriftInputError(f"missing observed field {section}.{field}")
            actual_value = actual[field]
            if not _capacity_value_matches(section, field, wanted_value, actual_value):
                drifts.append(Drift(section, field, wanted_value, actual_value))
    return drifts


def _capacity_value_matches(section: str, field: str, desired: object, observed: object) -> bool:
    if (section, field) in _NON_SHRINKING_FLOOR_FIELDS:
        return (
            isinstance(desired, int)
            and not isinstance(desired, bool)
            and isinstance(observed, int)
            and not isinstance(observed, bool)
            and observed >= desired
        )
    return observed == desired


def render_drift_report(drifts: list[Drift]) -> str:
    if not drifts:
        return "capacity drift: none\n"
    lines = ["capacity drift detected:"]
    for drift in drifts:
        lines.append(
            f"- resource={_safe(drift.resource)} field={_safe(drift.field)} "
            f"desired={_safe(drift.desired)} observed={_safe(drift.observed)}"
        )
    return "\n".join(lines) + "\n"


def collect_live_state(
    desired: dict[str, object],
    *,
    project: str,
    region: str,
    sql_instance: str,
    redis_instance: str,
    cluster: str,
    namespace: str,
    vpn_pool: str | None = None,
) -> dict[str, object]:
    """Read effective provider and Kubernetes state with fixed, read-only argv."""
    sql = _run_json(["gcloud", "sql", "instances", "describe", sql_instance, "--project", project, "--format=json"])
    redis = _run_json(
        [
            "gcloud",
            "redis",
            "instances",
            "describe",
            redis_instance,
            "--project",
            project,
            "--region",
            region,
            "--format=json",
        ]
    )
    access_pool = _run_json(
        [
            "gcloud",
            "container",
            "node-pools",
            "describe",
            "access",
            "--cluster",
            cluster,
            "--project",
            project,
            "--region",
            region,
            "--format=json",
        ]
    )
    workloads = _run_json(
        [
            "kubectl",
            "--namespace",
            namespace,
            "get",
            "deployment/portal-web",
            "deployment/guacd",
            "deployment/guacamole-client",
            "--output=json",
        ]
    )
    autoscalers = _run_json(
        [
            "kubectl",
            "--namespace",
            namespace,
            "get",
            "hpa/portal-web",
            "hpa/guacd",
            "--output=json",
        ]
    )
    backends = _run_json(
        [
            "kubectl",
            "--namespace",
            namespace,
            "get",
            "backendconfig/portal-web",
            "backendconfig/guacamole-client",
            "--output=json",
        ]
    )
    runtime = _run_json(["kubectl", "--namespace", namespace, "get", "configmap/platform-runtime", "--output=json"])

    profile_labels = [
        _dig(sql, "settings", "userLabels", "shifter_capacity_profile"),
        _dig(redis, "labels", "shifter_capacity_profile"),
        _dig(access_pool, "config", "labels", "shifter_capacity_profile"),
    ]
    if any(not isinstance(label, str) or not label for label in profile_labels) or len(set(profile_labels)) != 1:
        raise DriftInputError("provider resources have missing or inconsistent capacity-profile labels")

    terraform = {
        "capacity.cloud_sql_tier": _dig(sql, "settings", "tier"),
        "capacity.cloud_sql_availability_type": _dig(sql, "settings", "availabilityType"),
        "capacity.cloud_sql_disk_size_gb": _as_int(_dig(sql, "settings", "dataDiskSizeGb")),
        "capacity.redis_tier": redis.get("tier"),
        "capacity.redis_memory_size_gb": _as_int(redis.get("memorySizeGb")),
        "capacity.access_machine_type": _dig(access_pool, "config", "machineType"),
        "capacity.access_node_count": _as_int(_dig(access_pool, "autoscaling", "minNodeCount")),
        "capacity.access_node_max_count": _as_int(_dig(access_pool, "autoscaling", "maxNodeCount")),
    }
    if any(value in (None, "") for value in terraform.values()):
        raise DriftInputError("provider resources have incomplete capacity evidence")
    kubernetes = _extract_kubernetes(workloads, autoscalers, backends, runtime)
    observed: dict[str, object] = {"profile_id": profile_labels[0], "terraform": terraform, "kubernetes": kubernetes}
    if vpn_pool:
        terraform.update(_vpn_pool_state(vpn_pool, project=project, region=region))
    else:
        observed["vpn_pool"] = "absent"
    return observed


def _vpn_pool_state(name: str, *, project: str, region: str) -> dict[str, object]:
    """Read the pool autoscaler bounds and server machine type."""
    location = ["--project", project, "--region", region, "--format=json"]
    group = _run_json(["gcloud", "compute", "instance-groups", "managed", "describe", name, *location])
    policy = _run_json(["gcloud", "compute", "autoscalers", "describe", name, *location]).get("autoscalingPolicy", {})
    template = str(group.get("instanceTemplate", "")).rsplit("/", 1)[-1]
    machine = _dig(
        _run_json(["gcloud", "compute", "instance-templates", "describe", template, *location]),
        "properties",
        "machineType",
    )
    target = _dig(policy, "cpuUtilization", "utilizationTarget")
    state = {
        "capacity.vpn_pool_machine_type": str(machine).rsplit("/", 1)[-1] if machine else None,
        "capacity.vpn_pool_min_vms": _as_int(_dig(policy, "minNumReplicas")),
        "capacity.vpn_pool_max_vms": _as_int(_dig(policy, "maxNumReplicas")),
        "capacity.vpn_pool_cpu_target_pct": round(float(target) * 100) if isinstance(target, (int, float)) else None,
    }
    if any(value in (None, "") for value in state.values()):
        raise DriftInputError("the OpenVPN pool has incomplete capacity evidence")
    return state


def _extract_kubernetes(
    workloads: dict[str, Any],
    autoscalers: dict[str, Any],
    backends: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, object]:
    values: dict[str, object] = {}
    for item in workloads.get("items", []):
        name = _dig(item, "metadata", "name")
        if name not in {"portal-web", "guacd", "guacamole-client"}:
            continue
        prefix = f"deployment/{name}"
        values[f"{prefix}.metadata.annotations.shifter.dev/capacity-profile"] = _dig(
            item, "metadata", "annotations", "shifter.dev/capacity-profile"
        )
        values[f"{prefix}.spec.replicas"] = _as_int(_dig(item, "spec", "replicas"))
        values[f"{prefix}.spec.template.spec.terminationGracePeriodSeconds"] = _as_int(
            _dig(item, "spec", "template", "spec", "terminationGracePeriodSeconds")
        )
        container_name = "portal" if name == "portal-web" else name
        container = _named(_dig(item, "spec", "template", "spec", "containers"), container_name)
        for scope in ("requests", "limits"):
            for quantity in ("cpu", "memory"):
                values[f"{prefix}.spec.template.spec.containers.{container_name}.resources.{scope}.{quantity}"] = _dig(
                    container, "resources", scope, quantity
                )
        if name == "guacamole-client":
            env = _named(_dig(container, "env"), "POSTGRESQL_ABSOLUTE_MAX_CONNECTIONS")
            key = f"{prefix}.spec.template.spec.containers.{container_name}.env.POSTGRESQL_ABSOLUTE_MAX_CONNECTIONS"
            values[key] = _dig(env, "value")
    for item in autoscalers.get("items", []):
        name = _dig(item, "metadata", "name")
        if name in {"portal-web", "guacd"}:
            values[f"hpa/{name}.spec.minReplicas"] = _as_int(_dig(item, "spec", "minReplicas"))
            values[f"hpa/{name}.spec.maxReplicas"] = _as_int(_dig(item, "spec", "maxReplicas"))
    for item in backends.get("items", []):
        name = _dig(item, "metadata", "name")
        if name in {"portal-web", "guacamole-client"}:
            values[f"backendconfig/{name}.spec.timeoutSec"] = _as_int(_dig(item, "spec", "timeoutSec"))
            values[f"backendconfig/{name}.spec.connectionDraining.drainingTimeoutSec"] = _as_int(
                _dig(item, "spec", "connectionDraining", "drainingTimeoutSec")
            )
    for key in (
        "SHARED_SERVICE_CAPACITY_PROFILE",
        "PORTAL_WEB_WORKERS",
        "GUACAMOLE_BOOTSTRAP_WORKERS",
        "PORTAL_WEB_WS_PING_INTERVAL",
        "PORTAL_WEB_WS_PING_TIMEOUT",
        "PORTAL_WEB_GRACEFUL_TIMEOUT",
    ):
        values[f"configmap/platform-runtime.data.{key}"] = _dig(runtime, "data", key)
    return values


def _named(items: object, name: object) -> dict[str, Any]:
    if not isinstance(items, list):
        return {}
    return next((item for item in items if isinstance(item, dict) and item.get("name") == name), {})


def _run_json(argv: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(  # nosec B603 - internal callers supply fixed read-only argv; shell is never used
            argv, check=False, capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DriftInputError(f"read-only command failed to run: {argv[0]}") from exc
    if result.returncode != 0:
        raise DriftInputError(f"read-only command failed: {argv[0]} {argv[1]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DriftInputError(f"read-only command returned invalid JSON: {argv[0]} {argv[1]}") from exc
    if not isinstance(payload, dict):
        raise DriftInputError(f"read-only command returned a non-object: {argv[0]} {argv[1]}")
    return payload


def _mapping(data: dict[str, object], key: str, label: str) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise DriftInputError(f"{label} {key} must be an object")
    return value


def _required(data: dict[str, object], key: str, label: str) -> object:
    if key not in data or data[key] in (None, ""):
        raise DriftInputError(f"{label} is missing {key}")
    return data[key]


def _dig(data: object, *parts: str) -> object | None:
    current = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe(value: object) -> str:
    rendered = str(value).replace("\n", " ").replace("\r", " ")
    return rendered[:160]


def _read_object(path: str) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DriftInputError(f"could not read JSON object from {path}") from exc
    if not isinstance(payload, dict):
        raise DriftInputError(f"{path} must contain a JSON object")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report drift from an authored GCP shared-service capacity profile")
    parser.add_argument("--desired", required=True, help="Sanitized desired-state JSON rendered from the catalog")
    parser.add_argument("--observed", help="Offline sanitized observed-state JSON; omit to query live state")
    parser.add_argument("--project")
    parser.add_argument("--region")
    parser.add_argument("--sql-instance")
    parser.add_argument("--redis-instance")
    parser.add_argument("--cluster")
    parser.add_argument("--namespace", default="shifter-platform")
    parser.add_argument("--vpn-pool", help="OpenVPN pool instance group name, when the tenant deploys the pool")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        desired = _read_object(args.desired)
        if args.observed:
            observed = _read_object(args.observed)
        else:
            required = (args.project, args.region, args.sql_instance, args.redis_instance, args.cluster)
            if not all(required):
                raise DriftInputError(
                    "live inspection requires --project, --region, --sql-instance, --redis-instance, and --cluster"
                )
            observed = collect_live_state(
                desired,
                project=args.project,
                region=args.region,
                sql_instance=args.sql_instance,
                redis_instance=args.redis_instance,
                cluster=args.cluster,
                namespace=args.namespace,
                vpn_pool=args.vpn_pool,
            )
        drifts = compare_capacity_state(desired, observed)
    except DriftInputError as exc:
        print(f"capacity drift check failed closed: {exc}", file=sys.stderr)
        return 2
    print(render_drift_report(drifts), end="")
    return 1 if drifts else 0


if __name__ == "__main__":
    raise SystemExit(main())
