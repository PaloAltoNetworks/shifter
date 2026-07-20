"""Run the live-fire escape-validation suite against one or more GCP ranges (#1347).

Operator/CI entrypoint. Resolves the target range (and any peer ranges) from
portal state, builds the boundary-target inventory from an operator-supplied
deployment config, launches the bounded probes from participant context via the
selected adapter, and writes the closed machine-readable report. Exits non-zero
when the verdict is ``failed`` so CI/operator gates can block a range that leaks.

The suite is read-only against the range: it never provisions, destroys, or mutates
network state. See ``docs/`` for the operator runbook and config format.
"""

from __future__ import annotations

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cms.range_escape.adapters import NativeVmProbeLauncher, PolarisContainerProbeLauncher
from cms.range_escape.resolve import (
    RangeResolutionError,
    egress_policy_from_config,
    platform_inventory_from_config,
    resolve_range_under_test,
)
from cms.range_escape.runner import ProbeLauncher, RunOptions, run_escape_validation
from shared.range_escape import Verdict


def build_launcher(adapter: str) -> ProbeLauncher:
    """Return the probe-launch adapter for ``adapter`` (default native VM SSH).

    The participant container name for the Polaris adapter travels on each
    ParticipantContext, so it is not a build-time argument here.
    """
    if adapter == "polaris":
        return PolarisContainerProbeLauncher()
    return NativeVmProbeLauncher()


class Command(BaseCommand):
    """Run the escape-validation suite and emit its closed report."""

    help = "Validate that a GCP range cell's outer boundary fails closed (issue #1347)"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--request-id", required=True, help="Request id of the range under test")
        parser.add_argument(
            "--peer-request-id",
            action="append",
            default=[],
            help="Request id of a peer range used as a negative target (repeatable; enables the multi-range gate)",
        )
        parser.add_argument("--adapter", default="native", choices=["native", "polaris"], help="Probe-launch adapter")
        parser.add_argument("--container", default="", help="Participant container name (polaris adapter)")
        parser.add_argument("--config", required=True, help="Path to the deployment config JSON (platform + egress)")
        parser.add_argument("--output", default="", help="Path to write the JSON report (default: stdout)")
        parser.add_argument(
            "--timeout",
            type=int,
            default=4,
            help="Per-probe attempt timeout in seconds (the SSH transport budget is derived from this)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        config = _load_config(str(options["config"]))
        adapter = str(options["adapter"])
        container = str(options["container"])
        per_target_timeout_s = int(options["timeout"])

        try:
            platform = platform_inventory_from_config(config)
            egress = egress_policy_from_config(config)
            subject = resolve_range_under_test(
                request_id=str(options["request_id"]), adapter=adapter, container=container
            )
            peers = tuple(
                resolve_range_under_test(request_id=str(peer), adapter=adapter, container=container)
                for peer in options["peer_request_id"]
            )
        except RangeResolutionError as exc:
            raise CommandError(str(exc)) from exc

        started_at = timezone.now().isoformat()
        run_options = RunOptions(
            suite_id=f"escape-{subject.range_id}-{subject.request_id[:8]}",
            started_at=started_at,
            ended_at=timezone.now().isoformat(),
            policy_inputs={"egress_mode": egress.mode, "adapter": adapter},
            per_target_timeout_s=per_target_timeout_s,
        )
        report = run_escape_validation(
            subject=subject,
            peers=peers,
            platform=platform,
            egress=egress,
            launcher=build_launcher(adapter),
            options=run_options,
        )

        payload = report.to_json()
        output = str(options["output"])
        if output:
            Path(output).write_text(payload + "\n")
            self.stdout.write(f"wrote escape report to {output}")
        else:
            self.stdout.write(payload)

        failed = [c for c in report.checks if c.status.value == "fail"]
        summary = f"verdict={report.verdict.value} checks={len(report.checks)} failed={len(failed)}"
        if report.verdict is Verdict.FAILED:
            leaked = sorted({c.boundary_code.value for c in failed})
            raise CommandError(f"escape validation FAILED ({summary}); leaked boundaries: {', '.join(leaked)}")
        self.stdout.write(self.style.SUCCESS(f"escape validation passed ({summary})"))


def _load_config(path: str) -> dict[str, Any]:
    """Read and parse the operator deployment config JSON, or raise CommandError."""
    try:
        raw = Path(path).read_text()
    except OSError as exc:
        raise CommandError(f"cannot read config {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CommandError(f"config {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CommandError("config must be a JSON object with 'platform' and 'egress'")
    return data
