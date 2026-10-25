#!/usr/bin/env python3
"""Project feature-artifact acquisition from the canonical chart into the GCP lane (#2479).

Bootstrap renders acquisition through Helm. The release workflow applies the
Kustomize base instead, so without this projection a CI-deployed tenant never
gets the acquisition namespace, identity, admission policy or the launcher's
``FEATURE_ARTIFACT_JOB_IMAGE``, and every pack-declared feature artifact stays
acquiring until its lease expires.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - required CLI adapter; calls below use argv without a shell.
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = "shifter-acquisition"
POLICY = "restrict-feature-artifact-jobs"
JOB_IMAGE_KEY = "FEATURE_ARTIFACT_JOB_IMAGE"


def _owned(document: dict) -> bool:
    metadata = document.get("metadata", {})
    if document.get("kind") == "Namespace":
        return metadata.get("name") == NAMESPACE
    if document.get("kind") in {"ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding"}:
        return metadata.get("name") == POLICY
    return metadata.get("namespace") == NAMESPACE


def render_resources(acquisition: Mapping[str, object], *, image: str) -> list[dict]:
    """Render the actual chart and select only the acquisition resources."""
    values = {
        "provider": {"name": "gcp"},
        "capabilities": {"kubernetesJobLauncher": True, "featureArtifactAcquisition": True},
        "featureArtifactAcquisition": dict(acquisition),
        "images": {"platform": image},
    }
    with tempfile.TemporaryDirectory(prefix="feature-artifact-render-") as directory:
        path = Path(directory) / "values.json"
        path.write_text(json.dumps(values), encoding="utf-8")
        # Fixed Helm template command and chart; deployment values travel through a generated file, never shell text.
        result = subprocess.run(  # nosec B603 B607 - fixed CLI from the operator/CI toolchain.
            ["helm", "template", "shifter", str(_ROOT / "platform/charts/shifter"), "-f", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    selected = [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict) and _owned(doc)]
    if not any(doc.get("kind") == "ValidatingAdmissionPolicy" for doc in selected):
        raise ValueError("chart rendered no acquisition admission policy")
    return selected


def add_acquisition(manifest: str, resources: list[dict], *, image: str) -> str:
    """Add the acquisition resources and point the launcher at the admitted Job image."""
    documents = [document for document in yaml.safe_load_all(manifest) if document]
    runtime = [
        document
        for document in documents
        if document.get("kind") == "ConfigMap"
        and document.get("metadata", {}).get("name") == "platform-runtime"
        and document.get("metadata", {}).get("namespace") == "shifter-platform"
    ]
    if len(runtime) != 1:
        raise ValueError("acquisition requires exactly one platform-runtime ConfigMap")
    # The Job image must equal the image the admission policy pins.
    runtime[0].setdefault("data", {})[JOB_IMAGE_KEY] = image
    return yaml.safe_dump_all(documents + resources, sort_keys=False)


def main(argv: list[str] | None = None) -> int:
    """Enable acquisition exactly when Terraform defines the artifact-acquirer identity."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terraform-output", required=True)
    parser.add_argument("--platform-image", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    outputs = json.loads(Path(args.terraform_output).read_text(encoding="utf-8"))
    accounts = outputs.get("workload_service_accounts", {}).get("value")
    acquirer = accounts.get("artifact-acquirer") if isinstance(accounts, Mapping) else None
    manifest = Path(args.manifest).read_text(encoding="utf-8")
    if acquirer:
        # The bootstrap renderer owns the acquisition identity and egress values.
        sys.path.insert(0, str(_ROOT / "scripts/bootstrap"))
        from gcp_control_plane import _gcp_feature_artifact_acquisition_values

        resources = render_resources(_gcp_feature_artifact_acquisition_values(acquirer), image=args.platform_image)
        manifest = add_acquisition(manifest, resources, image=args.platform_image)
    Path(args.output).write_text(manifest, encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError):
        sys.stderr.write("feature-artifact acquisition rendering failed\n")
        raise SystemExit(1) from None
