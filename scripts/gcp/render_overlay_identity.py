#!/usr/bin/env python3
"""Render the tenant deploy identity into a GKE overlay from Terraform outputs.

The committed Kustomize overlay ships tenant-neutral ``shifter-<environment>``
placeholders in two files:

* ``kustomization.yaml`` image ``newName``s (the Artifact Registry roots), and
* ``patch-serviceaccounts.patch`` Workload Identity annotations (the GSA emails).

Real deploy identity -- the GCP project, the registry roots, the workload service
account emails -- must never be committed (ADR-004-R14, ADR-011): it is
reconnaissance-sensitive and tenant-specific. This renderer projects it in at
deploy time from the Terraform outputs the deploy workflow already captures,
exactly like ``render_runtime_env.py`` and ``render_edge_manifest.py`` project
the runtime env and edge manifest. It rewrites the two overlay files in place in
the (ephemeral) deploy checkout; the committed source keeps its placeholders.

Both rewrites fail closed: an image component or a service-account localpart that
is not present in the Terraform outputs raises rather than silently leaving a
placeholder that would bind pods to a nonexistent registry/identity.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TERRAFORM_OUTPUT_PATH = Path("/tmp/gcp-terraform-outputs.json")  # noqa: S108 - fixed path the deploy workflow writes
_IMAGE_ROOTS_OUTPUT_KEY = "artifact_registry_image_roots"
_WORKLOAD_SERVICE_ACCOUNTS_OUTPUT_KEY = "workload_service_accounts"

# An image entry in a Kustomize `images:` list:
#     - name: us-docker.pkg.dev/placeholder-project/shifter/<component>
#       newName: <registry-root>
# The component is the last path segment of the `name:` and selects the matching
# Terraform `artifact_registry_image_roots` entry. The `newTag`/`digest` line is
# left untouched (the deploy workflow pins it to the verified @sha256 digest).
_IMAGE_NEWNAME_RE = re.compile(
    r"(?P<pre>^[ \t]*-[ \t]*name:[ \t]*\S*/(?P<component>[a-z0-9][a-z0-9-]*)[ \t]*\n"
    r"[ \t]*newName:[ \t]*)\S+(?P<post>[ \t]*$)",
    re.MULTILINE,
)

# A Workload Identity annotation value: `<localpart>@<project>.iam.gserviceaccount.com`.
# Only the project differs between placeholder and real; the localpart is stable
# and identifies the workload, so it keys the matching Terraform output email.
_SERVICE_ACCOUNT_RE = re.compile(
    r"(?P<pre>iam\.gke\.io/gcp-service-account:[ \t]*)"
    r"(?P<localpart>[a-z][a-z0-9-]*[a-z0-9])@[a-z][a-z0-9.-]+\.iam\.gserviceaccount\.com"
)


def _value(outputs: dict[str, object], key: str):
    try:
        return outputs[key]["value"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise KeyError(f"Missing Terraform output: {key}") from exc


def render_kustomization_images(text: str, image_roots: dict[str, str]) -> str:
    """Return ``text`` with each image ``newName`` set to its Terraform root.

    ``image_roots`` is the ``artifact_registry_image_roots`` output: a map of
    logical component (``portal``, ``guacd``, ``guacamole-client``) to the full
    ``<region>-docker.pkg.dev/<project>/<repo>/<component>`` root. Raises
    ``KeyError`` if the overlay references a component with no Terraform root.
    """

    def _replace(match: re.Match[str]) -> str:
        component = match.group("component")
        try:
            root = image_roots[component]
        except KeyError as exc:
            raise KeyError(f"No artifact_registry_image_roots entry for image component {component!r}") from exc
        return f"{match.group('pre')}{root}{match.group('post')}"

    return _IMAGE_NEWNAME_RE.sub(_replace, text)


def render_service_account_patch(text: str, workload_service_accounts: dict[str, str]) -> str:
    """Return ``text`` with each Workload Identity annotation set to its real GSA.

    ``workload_service_accounts`` is the Terraform output mapping logical role to
    GSA email. Matching is by localpart (identical between placeholder and real),
    so the per-workload account-id suffixes (including the shortened
    ``prov-launcher``) are preserved exactly. Raises ``KeyError`` if the overlay
    names a service-account localpart with no Terraform email.
    """
    by_localpart = {email.split("@", 1)[0]: email for email in workload_service_accounts.values()}

    def _replace(match: re.Match[str]) -> str:
        localpart = match.group("localpart")
        try:
            email = by_localpart[localpart]
        except KeyError as exc:
            raise KeyError(f"No workload_service_accounts entry for service-account localpart {localpart!r}") from exc
        return f"{match.group('pre')}{email}"

    return _SERVICE_ACCOUNT_RE.sub(_replace, text)


def _overlay_dir(environment: str) -> Path:
    # Match the Environment grammar used by render_edge_manifest.py without
    # interpreting the value as a path.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", environment, flags=re.ASCII):
        raise ValueError("Invalid environment name for overlay identity render")
    overlay = (_REPO_ROOT / "platform/k8s/gcp/overlays" / environment).resolve()
    if _REPO_ROOT.resolve() not in overlay.parents:
        raise ValueError(f"Overlay path must stay inside the repository: {overlay}")
    if not overlay.is_dir():
        raise FileNotFoundError(f"Overlay directory not found: {overlay}")
    return overlay


def render_overlay(environment: str, outputs: dict[str, object]) -> None:
    """Rewrite the overlay's kustomization images and SA patch in place."""
    overlay = _overlay_dir(environment)
    image_roots = _value(outputs, _IMAGE_ROOTS_OUTPUT_KEY)
    workload_service_accounts = _value(outputs, _WORKLOAD_SERVICE_ACCOUNTS_OUTPUT_KEY)

    kustomization = overlay / "kustomization.yaml"
    kustomization.write_text(
        render_kustomization_images(kustomization.read_text(encoding="utf-8"), image_roots),
        encoding="utf-8",
    )

    sa_patch = overlay / "patch-serviceaccounts.patch"
    sa_patch.write_text(
        render_service_account_patch(sa_patch.read_text(encoding="utf-8"), workload_service_accounts),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument(
        "--terraform-output-json",
        default=str(_TERRAFORM_OUTPUT_PATH),
        help="Path to `terraform output -json` captured by the deploy workflow.",
    )
    args = parser.parse_args()

    outputs = json.loads(Path(args.terraform_output_json).read_text(encoding="utf-8"))
    render_overlay(args.environment, outputs)
    print(f"Rendered deploy identity into overlay {args.environment!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
