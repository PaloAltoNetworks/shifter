#!/usr/bin/env python3
"""Exercise the deployed GCP range-secret IAM boundary with real identities.

The probe is inert unless ``--execute`` is supplied. It never prints secret
payloads or provider stderr, and it uses the caller's operator identity only to
seed/clean an out-of-prefix secret that runtime identities must not read.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess  # nosec B404 -- the probe executes closed, shell-free gcloud argv only
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProbeConfig:
    platform_project: str
    dynamic_project: str
    unrelated_project: str
    environment: str
    provisioner_service_account: str
    portal_service_account: str
    range_host_service_account: str
    peer_range_host_service_account: str
    gateway_service_account: str
    peer_gateway_service_account: str
    workers_service_account: str
    launcher_service_account: str
    node_service_account: str


@dataclass(frozen=True)
class ProbeStep:
    name: str
    command: tuple[str, ...]
    expect_success: bool
    attempts: int = 1


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class ProbeCleanupError(RuntimeError):
    """One or more probe canaries could not be removed."""


def _impersonate(command: list[str], service_account: str) -> tuple[str, ...]:
    return (*command, f"--impersonate-service-account={service_account}", "--quiet")


def build_probe_steps(config: ProbeConfig, payload_path: Path, suffix: str) -> list[ProbeStep]:
    """Return the positive/negative command matrix without executing it."""
    canonical_root = f"shifter-{config.environment}-dynamic"
    participant = f"{canonical_root}-participant-probe-range-{suffix}-credential"
    host_secret = f"{canonical_root}-workload-probe-host-range-{suffix}-credential"
    gateway_secret = f"{canonical_root}-workload-probe-vpn-range-{suffix}-server"
    unrelated = f"shifter-permission-probe-unrelated-{suffix}"
    platform_unrelated = f"shifter-permission-probe-platform-{suffix}"
    external_unrelated = f"shifter-permission-probe-external-{suffix}"
    external_create = f"{canonical_root}-workload-probe-external-range-{suffix}-credential"

    def secret(command: str, secret_id: str, project: str, *args: str) -> list[str]:
        return ["gcloud", "secrets", command, secret_id, f"--project={project}", *args]

    def version(command: str, secret_id: str, project: str, *args: str) -> list[str]:
        return ["gcloud", "secrets", "versions", command, *args, f"--secret={secret_id}", f"--project={project}"]

    provisioner = config.provisioner_service_account
    portal = config.portal_service_account
    steps = [
        ProbeStep(
            "operator-seed-unrelated-secret",
            tuple(
                secret(
                    "create",
                    unrelated,
                    config.dynamic_project,
                    "--replication-policy=automatic",
                    f"--data-file={payload_path}",
                    "--quiet",
                )
            ),
            True,
        ),
        ProbeStep(
            "operator-seed-platform-secret",
            tuple(
                secret(
                    "create",
                    platform_unrelated,
                    config.platform_project,
                    "--replication-policy=automatic",
                    f"--data-file={payload_path}",
                    "--quiet",
                )
            ),
            True,
        ),
        ProbeStep(
            "operator-seed-external-secret",
            tuple(
                secret(
                    "create",
                    external_unrelated,
                    config.unrelated_project,
                    "--replication-policy=automatic",
                    f"--data-file={payload_path}",
                    "--quiet",
                )
            ),
            True,
        ),
        ProbeStep(
            "provisioner-create-participant",
            _impersonate(
                secret("create", participant, config.dynamic_project, "--replication-policy=automatic"), provisioner
            ),
            True,
        ),
        ProbeStep(
            "provisioner-add-participant-version",
            _impersonate(
                version("add", participant, config.dynamic_project, f"--data-file={payload_path}"), provisioner
            ),
            True,
        ),
        ProbeStep(
            "provisioner-read-participant",
            _impersonate(version("access", participant, config.dynamic_project, "latest"), provisioner),
            True,
        ),
        ProbeStep(
            "provisioner-update-participant",
            _impersonate(
                secret("update", participant, config.dynamic_project, "--update-labels=shifter-permission-probe=true"),
                provisioner,
            ),
            True,
        ),
        ProbeStep(
            "portal-read-participant",
            _impersonate(version("access", participant, config.dynamic_project, "latest"), portal),
            True,
        ),
        ProbeStep(
            "portal-create-denied",
            _impersonate(
                secret(
                    "create",
                    f"{canonical_root}-participant-probe-range-{suffix}-portal-create",
                    config.dynamic_project,
                    "--replication-policy=automatic",
                ),
                portal,
            ),
            False,
        ),
        ProbeStep(
            "provisioner-create-platform-denied",
            _impersonate(
                secret("create", host_secret, config.platform_project, "--replication-policy=automatic"), provisioner
            ),
            False,
        ),
        ProbeStep(
            "provisioner-create-external-denied",
            _impersonate(
                secret(
                    "create",
                    external_create,
                    config.unrelated_project,
                    "--replication-policy=automatic",
                ),
                provisioner,
            ),
            False,
        ),
        ProbeStep(
            "provisioner-read-unrelated-denied",
            _impersonate(version("access", unrelated, config.dynamic_project, "latest"), provisioner),
            False,
        ),
        ProbeStep(
            "provisioner-read-platform-denied",
            _impersonate(version("access", platform_unrelated, config.platform_project, "latest"), provisioner),
            False,
        ),
        ProbeStep(
            "provisioner-read-external-denied",
            _impersonate(version("access", external_unrelated, config.unrelated_project, "latest"), provisioner),
            False,
        ),
        ProbeStep(
            "portal-read-unrelated-denied",
            _impersonate(version("access", unrelated, config.dynamic_project, "latest"), portal),
            False,
        ),
        ProbeStep(
            "portal-read-platform-denied",
            _impersonate(version("access", platform_unrelated, config.platform_project, "latest"), portal),
            False,
        ),
        ProbeStep(
            "portal-read-external-denied",
            _impersonate(version("access", external_unrelated, config.unrelated_project, "latest"), portal),
            False,
        ),
        ProbeStep(
            "provisioner-add-unrelated-version-denied",
            _impersonate(version("add", unrelated, config.dynamic_project, f"--data-file={payload_path}"), provisioner),
            False,
        ),
        ProbeStep(
            "provisioner-update-unrelated-denied",
            _impersonate(
                secret(
                    "update",
                    unrelated,
                    config.dynamic_project,
                    "--update-labels=shifter-permission-probe=true",
                ),
                provisioner,
            ),
            False,
        ),
        ProbeStep(
            "provisioner-set-iam-unrelated-denied",
            _impersonate(
                secret(
                    "add-iam-policy-binding",
                    unrelated,
                    config.dynamic_project,
                    f"--member=serviceAccount:{config.range_host_service_account}",
                    "--role=roles/secretmanager.secretAccessor",
                ),
                provisioner,
            ),
            False,
        ),
        ProbeStep(
            "provisioner-delete-unrelated-denied",
            _impersonate(secret("delete", unrelated, config.dynamic_project), provisioner),
            False,
        ),
        ProbeStep(
            "portal-add-participant-version-denied",
            _impersonate(version("add", participant, config.dynamic_project, f"--data-file={payload_path}"), portal),
            False,
        ),
        ProbeStep(
            "portal-update-participant-denied",
            _impersonate(
                secret(
                    "update",
                    participant,
                    config.dynamic_project,
                    "--update-labels=shifter-permission-probe=portal",
                ),
                portal,
            ),
            False,
        ),
        ProbeStep(
            "provisioner-create-host-secret",
            _impersonate(
                secret("create", host_secret, config.dynamic_project, "--replication-policy=automatic"), provisioner
            ),
            True,
        ),
        ProbeStep(
            "provisioner-add-host-version",
            _impersonate(
                version("add", host_secret, config.dynamic_project, f"--data-file={payload_path}"), provisioner
            ),
            True,
        ),
        ProbeStep(
            "portal-read-workload-denied",
            _impersonate(version("access", host_secret, config.dynamic_project, "latest"), portal),
            False,
        ),
    ]
    steps.extend(
        [
            ProbeStep(
                "range-host-read-before-grant-denied",
                _impersonate(
                    version("access", host_secret, config.dynamic_project, "latest"),
                    config.range_host_service_account,
                ),
                False,
            ),
            ProbeStep(
                "provisioner-grant-range-host",
                _impersonate(
                    secret(
                        "add-iam-policy-binding",
                        host_secret,
                        config.dynamic_project,
                        f"--member=serviceAccount:{config.range_host_service_account}",
                        "--role=roles/secretmanager.secretAccessor",
                    ),
                    provisioner,
                ),
                True,
            ),
            ProbeStep(
                "range-host-read-after-grant",
                _impersonate(
                    version("access", host_secret, config.dynamic_project, "latest"),
                    config.range_host_service_account,
                ),
                True,
                attempts=5,
            ),
            ProbeStep(
                "peer-range-host-read-denied",
                _impersonate(
                    version("access", host_secret, config.dynamic_project, "latest"),
                    config.peer_range_host_service_account,
                ),
                False,
            ),
            ProbeStep(
                "range-host-project-wide-read-denied",
                _impersonate(
                    version("access", unrelated, config.dynamic_project, "latest"),
                    config.range_host_service_account,
                ),
                False,
            ),
            ProbeStep(
                "provisioner-create-gateway-secret",
                _impersonate(
                    secret("create", gateway_secret, config.dynamic_project, "--replication-policy=automatic"),
                    provisioner,
                ),
                True,
            ),
            ProbeStep(
                "provisioner-add-gateway-version",
                _impersonate(
                    version("add", gateway_secret, config.dynamic_project, f"--data-file={payload_path}"),
                    provisioner,
                ),
                True,
            ),
            ProbeStep(
                "range-host-read-gateway-denied",
                _impersonate(
                    version("access", gateway_secret, config.dynamic_project, "latest"),
                    config.range_host_service_account,
                ),
                False,
            ),
            ProbeStep(
                "gateway-read-before-grant-denied",
                _impersonate(
                    version("access", gateway_secret, config.dynamic_project, "latest"),
                    config.gateway_service_account,
                ),
                False,
            ),
            ProbeStep(
                "provisioner-grant-gateway",
                _impersonate(
                    secret(
                        "add-iam-policy-binding",
                        gateway_secret,
                        config.dynamic_project,
                        f"--member=serviceAccount:{config.gateway_service_account}",
                        "--role=roles/secretmanager.secretAccessor",
                    ),
                    provisioner,
                ),
                True,
            ),
            ProbeStep(
                "gateway-read-after-grant",
                _impersonate(
                    version("access", gateway_secret, config.dynamic_project, "latest"),
                    config.gateway_service_account,
                ),
                True,
                attempts=5,
            ),
            ProbeStep(
                "gateway-read-host-denied",
                _impersonate(
                    version("access", host_secret, config.dynamic_project, "latest"),
                    config.gateway_service_account,
                ),
                False,
            ),
            ProbeStep(
                "peer-gateway-read-denied",
                _impersonate(
                    version("access", gateway_secret, config.dynamic_project, "latest"),
                    config.peer_gateway_service_account,
                ),
                False,
            ),
            ProbeStep(
                "gateway-project-wide-read-denied",
                _impersonate(
                    version("access", unrelated, config.dynamic_project, "latest"),
                    config.gateway_service_account,
                ),
                False,
            ),
        ]
    )
    for role, service_account in (
        ("workers", config.workers_service_account),
        ("launcher", config.launcher_service_account),
        ("node", config.node_service_account),
    ):
        steps.append(
            ProbeStep(
                f"{role}-read-participant-denied",
                _impersonate(version("access", participant, config.dynamic_project, "latest"), service_account),
                False,
            )
        )
    steps.extend(
        [
            ProbeStep(
                "portal-delete-participant-denied",
                _impersonate(secret("delete", participant, config.dynamic_project), portal),
                False,
            ),
            ProbeStep(
                "provisioner-delete-participant",
                _impersonate(secret("delete", participant, config.dynamic_project), provisioner),
                True,
            ),
            ProbeStep(
                "provisioner-delete-host-secret",
                _impersonate(secret("delete", host_secret, config.dynamic_project), provisioner),
                True,
            ),
            ProbeStep(
                "provisioner-delete-gateway-secret",
                _impersonate(secret("delete", gateway_secret, config.dynamic_project), provisioner),
                True,
            ),
        ]
    )
    return steps


def _subprocess_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    # Every command is assembled internally as a shell-free argv sequence;
    # deployment values remain individual arguments and cannot add commands.
    return subprocess.run(command, check=False, capture_output=True, text=True)  # nosec B603


def _is_boundary_denial(result: subprocess.CompletedProcess[str]) -> bool:
    """Accept only an authorization denial, never missing state or failed impersonation."""
    detail = f"{result.stdout}\n{result.stderr}".lower()
    authorization_denial = any(
        marker in detail
        for marker in (
            "permission_denied",
            "permission denied",
            "does not have permission",
            "not authorized",
        )
    )
    invalid_probe = any(
        marker in detail
        for marker in (
            "iam.serviceaccounts.getaccesstoken",
            "unable to acquire impersonated credentials",
            "not_found",
            "not found",
            "already_exists",
            "already exists",
        )
    )
    return result.returncode != 0 and authorization_denial and not invalid_probe


def _step_evidence(step: ProbeStep, correlation_id: str, elapsed_seconds: float, passed: bool) -> str:
    """Render one payload-free, resource-fingerprinted permission result."""
    command = step.command
    principal = "operator"
    for part in command:
        if part.startswith("--impersonate-service-account="):
            principal = part.split("=", 1)[1]
            break

    action = command[2] if len(command) > 2 else "unknown"
    secret_id = command[3] if len(command) > 3 else "unknown"
    if action == "versions":
        action = command[3] if len(command) > 3 else "unknown"
        secret_id = next((part.split("=", 1)[1] for part in command if part.startswith("--secret=")), "unknown")
    permission = {
        "create": "secretmanager.secrets.create",
        "update": "secretmanager.secrets.update",
        "delete": "secretmanager.secrets.delete",
        "add-iam-policy-binding": "secretmanager.secrets.setIamPolicy",
        "add": "secretmanager.versions.add",
        "access": "secretmanager.versions.access",
    }.get(action, "unknown")
    project = next((part.split("=", 1)[1] for part in command if part.startswith("--project=")), "unknown")
    if "participant" in secret_id:
        resource_class = "participant"
    elif "probe-host" in secret_id:
        resource_class = "host-workload"
    elif "probe-vpn" in secret_id:
        resource_class = "gateway-workload"
    else:
        resource_class = "unrelated"
    resource_fingerprint = hashlib.sha256(f"{project}/{secret_id}".encode()).hexdigest()[:16]
    expected = "ALLOW" if step.expect_success else "DENY"
    status = "PASS" if passed else "FAIL"
    return (
        f"{status} correlation={correlation_id} principal={principal} permission={permission} "
        f"resource_class={resource_class} resource_fp={resource_fingerprint} "
        f"expected={expected} elapsed_ms={elapsed_seconds * 1000:.0f}"
    )


def _is_cleanup_not_found(result: subprocess.CompletedProcess[str]) -> bool:
    """Treat only a genuine absent-resource response as idempotent cleanup."""
    detail = f"{result.stdout}\n{result.stderr}".lower()
    not_found = "not_found" in detail or "not found" in detail
    authorization_failure = any(
        marker in detail
        for marker in (
            "permission_denied",
            "permission denied",
            "does not have permission",
            "not authorized",
        )
    )
    return result.returncode != 0 and not_found and not authorization_failure


def _cleanup(config: ProbeConfig, suffix: str, runner: Runner) -> None:
    """Delete all canaries and fail with payload-free evidence on any residue."""
    root = f"shifter-{config.environment}-dynamic"
    commands = [
        (
            "gcloud",
            "secrets",
            "delete",
            secret_id,
            f"--project={config.dynamic_project}",
            "--quiet",
        )
        for secret_id in (
            f"{root}-participant-probe-range-{suffix}-credential",
            f"{root}-participant-probe-range-{suffix}-portal-create",
            f"{root}-workload-probe-host-range-{suffix}-credential",
            f"{root}-workload-probe-vpn-range-{suffix}-server",
            f"shifter-permission-probe-unrelated-{suffix}",
        )
    ]
    commands.extend(
        (
            "gcloud",
            "secrets",
            "delete",
            secret_id,
            f"--project={project}",
            "--quiet",
        )
        for project, secret_id in (
            (
                config.platform_project,
                f"{root}-workload-probe-host-range-{suffix}-credential",
            ),
            (
                config.unrelated_project,
                f"{root}-workload-probe-external-range-{suffix}-credential",
            ),
            (
                config.platform_project,
                f"shifter-permission-probe-platform-{suffix}",
            ),
            (
                config.unrelated_project,
                f"shifter-permission-probe-external-{suffix}",
            ),
        )
    )

    failures: list[str] = []
    for command in commands:
        result = runner(command)
        if result.returncode == 0 or _is_cleanup_not_found(result):
            continue
        project = next(part.split("=", 1)[1] for part in command if part.startswith("--project="))
        resource_fingerprint = hashlib.sha256(f"{project}/{command[3]}".encode()).hexdigest()[:16]
        project_fingerprint = hashlib.sha256(project.encode()).hexdigest()[:12]
        failures.append(f"project_fp={project_fingerprint} resource_fp={resource_fingerprint} exit={result.returncode}")
    if failures:
        raise ProbeCleanupError("permission probe cleanup failed: " + "; ".join(failures))


def run_probe(config: ProbeConfig, *, runner: Runner = _subprocess_runner) -> None:
    """Run the matrix and fail on either an unexpected grant or denial."""
    if config.dynamic_project == config.platform_project:
        raise ValueError(
            "live boundary probing requires a dedicated dynamic project distinct from the platform project"
        )
    if config.unrelated_project in {config.platform_project, config.dynamic_project}:
        raise ValueError("unrelated project must differ from both platform and dynamic projects")
    if not re.fullmatch(r"[a-z0-9-]+", config.environment):
        raise ValueError("environment must contain only lowercase letters, digits, and hyphens")
    identities = {
        "provisioner": config.provisioner_service_account,
        "portal": config.portal_service_account,
        "range host": config.range_host_service_account,
        "peer range host": config.peer_range_host_service_account,
        "gateway": config.gateway_service_account,
        "peer gateway": config.peer_gateway_service_account,
        "workers": config.workers_service_account,
        "launcher": config.launcher_service_account,
        "node": config.node_service_account,
    }
    missing = [name for name, email in identities.items() if not email.strip()]
    if missing:
        raise ValueError("live boundary probing requires every workload identity: " + ", ".join(missing))

    suffix = uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="shifter-gcp-secret-probe-") as directory:
        payload_path = Path(directory) / "payload"
        payload_path.write_text(uuid.uuid4().hex, encoding="utf-8")
        payload_path.chmod(0o600)
        try:
            for step in build_probe_steps(config, payload_path, suffix):
                started = time.monotonic()
                result = runner(step.command)
                for _attempt in range(1, step.attempts):
                    if result.returncode == 0:
                        break
                    time.sleep(2)
                    result = runner(step.command)
                passed = result.returncode == 0 if step.expect_success else _is_boundary_denial(result)
                print(_step_evidence(step, suffix, time.monotonic() - started, passed))
                if not passed:
                    expected = "success" if step.expect_success else "denial"
                    raise RuntimeError(f"permission probe {step.name!r} expected {expected}")
        except Exception as probe_error:
            try:
                _cleanup(config, suffix, runner)
            except ProbeCleanupError as cleanup_error:
                raise ExceptionGroup(
                    "permission boundary probe and cleanup both failed",
                    [probe_error, cleanup_error],
                ) from None
            raise
        else:
            _cleanup(config, suffix, runner)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform-project", required=True)
    parser.add_argument("--dynamic-project", required=True)
    parser.add_argument("--unrelated-project", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--provisioner-service-account", required=True)
    parser.add_argument("--portal-service-account", required=True)
    parser.add_argument("--range-host-service-account", required=True)
    parser.add_argument("--peer-range-host-service-account", required=True)
    parser.add_argument("--gateway-service-account", required=True)
    parser.add_argument("--peer-gateway-service-account", required=True)
    parser.add_argument("--workers-service-account", required=True)
    parser.add_argument("--launcher-service-account", required=True)
    parser.add_argument("--node-service-account", required=True)
    parser.add_argument("--execute", action="store_true", help="Run live gcloud operations; omitted means plan-only.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = ProbeConfig(
        platform_project=args.platform_project,
        dynamic_project=args.dynamic_project,
        unrelated_project=args.unrelated_project,
        environment=args.environment,
        provisioner_service_account=args.provisioner_service_account,
        portal_service_account=args.portal_service_account,
        range_host_service_account=args.range_host_service_account,
        peer_range_host_service_account=args.peer_range_host_service_account,
        gateway_service_account=args.gateway_service_account,
        peer_gateway_service_account=args.peer_gateway_service_account,
        workers_service_account=args.workers_service_account,
        launcher_service_account=args.launcher_service_account,
        node_service_account=args.node_service_account,
    )
    if not args.execute:
        for step in build_probe_steps(config, Path("<temporary-payload>"), "<random>"):
            expectation = "ALLOW" if step.expect_success else "DENY"
            print(f"{expectation} {step.name}")
        return 0
    run_probe(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
