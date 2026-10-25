#!/usr/bin/env python3
"""Render an ephemeral post-deploy smoke Job from the live portal Deployment."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

_DNS_LABEL = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?")
_DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")


def _name(value: str, field: str) -> str:
    if not _DNS_LABEL.fullmatch(value):
        raise ValueError(f"{field} must be a DNS label")
    return value


def render_smoke_job(
    deployment: dict[str, object],
    *,
    name: str,
    secret_name: str,
    variant: str,
    active_deadline_seconds: int,
) -> dict[str, object]:
    """Keep the live portal identity/runtime while replacing its server command."""
    _name(name, "job name")
    _name(secret_name, "secret name")
    if variant not in {"linux", "windows"}:
        raise ValueError("variant must be linux or windows")
    if not 60 <= active_deadline_seconds <= 7200:
        raise ValueError("active deadline must be between 60 and 7200 seconds")

    metadata = deployment.get("metadata")
    spec = deployment.get("spec")
    if not isinstance(metadata, dict) or not isinstance(spec, dict):
        raise ValueError("deployment metadata or spec is malformed")
    template = spec.get("template")
    if not isinstance(template, dict) or not isinstance(template.get("spec"), dict):
        raise ValueError("deployment pod template is malformed")

    pod_spec = copy.deepcopy(template["spec"])
    containers = pod_spec.get("containers")
    if not isinstance(containers, list) or len(containers) != 1 or not isinstance(containers[0], dict):
        raise ValueError("portal deployment must contain exactly one container")
    portal = containers[0]
    if portal.get("name") != "portal" or not _DIGEST_IMAGE.fullmatch(str(portal.get("image", ""))):
        raise ValueError("portal container must use its exact digest image")

    for field in ("ports", "readinessProbe", "livenessProbe", "startupProbe"):
        portal.pop(field, None)
    # Preserve the image ENTRYPOINT: it hydrates the database, application and
    # Redis secrets before executing these arguments. A Kubernetes ``command``
    # override would bypass that fail-closed startup path.
    portal.pop("command", None)
    portal["args"] = ["python", "manage.py", "run_post_deploy_smoke", "--variant", variant]
    environment = portal.setdefault("env", [])
    if not isinstance(environment, list):
        raise ValueError("portal container environment is malformed")
    if any(isinstance(item, dict) and item.get("name") == "SMOKE_TEST_USER_EMAIL" for item in environment):
        raise ValueError("portal deployment unexpectedly defines the smoke identity")
    environment.append(
        {
            "name": "SMOKE_TEST_USER_EMAIL",
            "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "SMOKE_TEST_USER_EMAIL"}},
        }
    )
    pod_spec["restartPolicy"] = "Never"

    namespace = str(metadata.get("namespace", "shifter-platform"))
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/name": "shifter-post-deploy-smoke",
                "app.kubernetes.io/component": "post-deploy-smoke",
                "shifter.dev/ephemeral": "true",
            },
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": active_deadline_seconds,
            "ttlSecondsAfterFinished": 300,
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/name": "shifter-post-deploy-smoke",
                        "app.kubernetes.io/component": "post-deploy-smoke",
                        "shifter.dev/ephemeral": "true",
                    }
                },
                "spec": pod_spec,
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--secret-name", required=True)
    parser.add_argument("--variant", choices=("linux", "windows"), required=True)
    parser.add_argument("--active-deadline-seconds", type=int, default=3600)
    args = parser.parse_args()
    try:
        deployment = json.loads(args.deployment.read_text(encoding="utf-8"))
        job = render_smoke_job(
            deployment,
            name=args.name,
            secret_name=args.secret_name,
            variant=args.variant,
            active_deadline_seconds=args.active_deadline_seconds,
        )
        args.output.write_text(json.dumps(job, separators=(",", ":")), encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
