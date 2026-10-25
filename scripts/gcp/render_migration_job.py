#!/usr/bin/env python3
"""Render the same owner migration Job used by the bootstrap path."""

import argparse
import json
import re
from pathlib import Path

import yaml
from installation.gcp_migrations import render_migration_job
from installation.gcp_native_identity import validate_native_identity


def render(outputs: dict, *, image: str, job_name: str) -> dict:
    if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("Migration requires the attested platform image digest")
    if not re.fullmatch(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?", job_name):
        raise ValueError("Migration Job name must be a bounded DNS label")
    native = validate_native_identity(
        outputs.get("native_identity", {}).get("value"),
        project_id=outputs["identity_platform_project_id"]["value"],
        service_accounts=outputs["workload_service_accounts"]["value"],
    )
    return render_migration_job(
        image, job_name=job_name, instance_connection_name=native.instance_connection_name if native.enabled else ""
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terraform-output", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = render(json.loads(args.terraform_output.read_text()), image=args.image, job_name=args.job_name)
    args.output.write_text(yaml.safe_dump(document, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
