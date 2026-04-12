#!/usr/bin/env python3
"""Render Workload Identity service account annotations from Terraform outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


_REQUIRED_ROLES = ("portal", "workers", "provisioner")


def _value(outputs: dict[str, object], key: str):
    try:
        return outputs[key]["value"]
    except KeyError as exc:
        raise KeyError(f"Missing Terraform output: {key}") from exc


def render_serviceaccount_patch(workload_service_accounts: dict[str, str]) -> str:
    missing = [role for role in _REQUIRED_ROLES if role not in workload_service_accounts]
    if missing:
        raise ValueError(f"Missing workload service account outputs for: {', '.join(missing)}")

    return (
        "apiVersion: v1\n"
        "kind: ServiceAccount\n"
        "metadata:\n"
        "  name: portal\n"
        "  namespace: shifter-platform\n"
        "  annotations:\n"
        f"    iam.gke.io/gcp-service-account: {workload_service_accounts['portal']}\n"
        "---\n"
        "apiVersion: v1\n"
        "kind: ServiceAccount\n"
        "metadata:\n"
        "  name: workers\n"
        "  namespace: shifter-platform\n"
        "  annotations:\n"
        f"    iam.gke.io/gcp-service-account: {workload_service_accounts['workers']}\n"
        "---\n"
        "apiVersion: v1\n"
        "kind: ServiceAccount\n"
        "metadata:\n"
        "  name: provisioner\n"
        "  namespace: shifter-jobs\n"
        "  annotations:\n"
        f"    iam.gke.io/gcp-service-account: {workload_service_accounts['provisioner']}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terraform-output-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    outputs = json.loads(args.terraform_output_json.read_text())
    rendered = render_serviceaccount_patch(_value(outputs, "workload_service_accounts"))
    args.output.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
