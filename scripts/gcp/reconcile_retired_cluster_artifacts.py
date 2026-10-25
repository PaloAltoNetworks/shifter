#!/usr/bin/env python3
"""Retire explicitly inventoried manual qualification objects after deploy."""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 - fixed kubectl argv, no shell.
from pathlib import Path

MAX_MANIFEST_BYTES = 16 * 1024
NAME_RE = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?\Z")


def _check_name(value: object) -> str:
    if not isinstance(value, str) or len(value) > 253 or not NAME_RE.fullmatch(value):
        raise ValueError("invalid retired resource name")
    return value


def _kubectl(context: str, namespace: str, *args: str, may_be_absent: bool = False) -> bool:
    result = subprocess.run(  # nosec B603 B607 - fixed kubectl argv from the workflow toolchain; no shell.
        ["kubectl", "--context", context, "-n", namespace, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True
    if may_be_absent and "NotFound" in result.stderr:
        return False
    raise RuntimeError("retired resource reconciliation failed")


def _has_deployment_annotation(context: str, namespace: str, name: str, annotation: str) -> bool:
    """Read the current Deployment before removing a one-time manual annotation."""
    result = subprocess.run(  # nosec B603 B607 - fixed kubectl argv from the workflow toolchain; no shell.
        ["kubectl", "--context", context, "-n", namespace, "get", "deployment", name, "-o", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("retired Deployment annotation reconciliation failed")
    deployment = json.loads(result.stdout)
    annotations = deployment.get("metadata", {}).get("annotations") or {}
    if not isinstance(annotations, dict):
        raise ValueError("Deployment annotations are malformed")
    return annotation in annotations


def reconcile(context: str, manifest: Path) -> None:
    raw = manifest.read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("retired resource manifest exceeds its size limit")
    entries = json.loads(raw)
    if set(entries) != {"network_policies", "secrets", "deployment_annotations"}:
        raise ValueError("retired resource manifest has unexpected fields")
    for item in entries["network_policies"]:
        if set(item) != {"namespace", "name", "replacement"}:
            raise ValueError("retired NetworkPolicy entry has unexpected fields")
        namespace, name, replacement = (_check_name(item[key]) for key in ("namespace", "name", "replacement"))
        if not _kubectl(context, namespace, "get", "networkpolicy", replacement):
            raise RuntimeError("replacement NetworkPolicy is missing")
        _kubectl(context, namespace, "delete", "networkpolicy", name, "--ignore-not-found")
    for item in entries["secrets"]:
        if set(item) != {"namespace", "name", "obsolete_job"}:
            raise ValueError("retired Secret entry has unexpected fields")
        namespace, name, job = (_check_name(item[key]) for key in ("namespace", "name", "obsolete_job"))
        if _kubectl(context, namespace, "get", "job", job, may_be_absent=True):
            raise ValueError("obsolete qualification Job is still present")
        _kubectl(context, namespace, "delete", "secret", name, "--ignore-not-found")
    for item in entries["deployment_annotations"]:
        if set(item) != {"namespace", "name", "annotation"}:
            raise ValueError("retired annotation entry has unexpected fields")
        namespace, name = (_check_name(item[key]) for key in ("namespace", "name"))
        annotation = item["annotation"]
        if annotation != "kubectl.kubernetes.io/restartedAt":
            raise ValueError("only the manual rollout annotation may be retired")
        if _has_deployment_annotation(context, namespace, name, annotation):
            _kubectl(context, namespace, "annotate", "deployment", name, f"{annotation}-", "--overwrite")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    reconcile(args.context, args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
