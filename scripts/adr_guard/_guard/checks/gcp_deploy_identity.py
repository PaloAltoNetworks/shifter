"""GCP deploy-identity hygiene in the committed Kustomize overlays (ADR-004-R14, ADR-011)."""
from __future__ import annotations

import re
from pathlib import Path

from .._common import Violation, _read_text_safe
from .cloud_identifiers import _IDENTIFIER_RULE_ID, _identifier_skip, _iter_identifier_candidates


# ---------------------------------------------------------------------------
# ADR-004-R14 / ADR-011: GCP deploy-identity hygiene in Kustomize overlays.
#
# The committed GCP tenant overlays must never carry real deploy identity - the
# GCP project, Artifact Registry roots, or workload service-account emails. Real
# identity is reconnaissance-sensitive and tenant-specific; the CI deploy renders
# it in from Terraform outputs at deploy time
# (scripts/gcp/render_overlay_identity.py), so the committed source must stay on
# the tenant-neutral `shifter-<environment>` placeholder (or the Kustomize base's
# shared `placeholder-project`). This is the GCP complement to the AWS-shaped
# `no-live-cloud-identifiers` scan in cloud_identifiers.py.
#
# Detection is GCP-context anchored: a project id is only inspected when it sits
# in a container-registry root (`...docker.pkg.dev/<project>/`, `gcr.io/<project>/`)
# or a service-account email (`<sa>@<project>.iam.gserviceaccount.com`). Anchoring
# on GCP syntax - not a bare `prod-*` word pattern - avoids colliding with the
# many legitimate `prod-<word>` strings elsewhere in the repo. The allowed project
# is derived from the overlay directory name, never a denylist of real values.
_GCP_DEPLOY_IDENTITY_CHECK = "no-live-gcp-deploy-identity"
_GCP_OVERLAY_ROOT = "platform/k8s/gcp/overlays/"
# The Kustomize base's universal placeholder; it appears in each overlay's image
# `name:` lines (the pre-rename source refs) and is always safe.
_GCP_SHARED_PLACEHOLDER_PROJECT = "placeholder-project"
# A GCP project id (6-30 chars: lowercase letter, then letters/digits/hyphens, no
# trailing hyphen) embedded in a container-registry root or a service-account
# email. `docker.pkg.dev` matches as a substring of `<region>-docker.pkg.dev`.
_GCP_PROJECT = r"[a-z][a-z0-9-]{4,28}[a-z0-9]"
_GCP_REGISTRY_PROJECT_RE = re.compile(
    r"(?:docker\.pkg\.dev|gcr\.io)/(?P<project>" + _GCP_PROJECT + r")/"
)
_GCP_SA_PROJECT_RE = re.compile(
    r"@(?P<project>" + _GCP_PROJECT + r")\.iam\.gserviceaccount\.com"
)


def _gcp_overlay_environment(rel: str) -> str | None:
    """Return the overlay environment name for a path under the overlay root, else None."""
    if not rel.startswith(_GCP_OVERLAY_ROOT):
        return None
    environment = rel[len(_GCP_OVERLAY_ROOT):].split("/", 1)[0]
    return environment or None


def _allowed_overlay_projects(environment: str) -> frozenset[str]:
    """Projects that may legitimately appear in environment `environment`'s overlay."""
    return frozenset({_GCP_SHARED_PLACEHOLDER_PROJECT, f"shifter-{environment}"})


def _scan_gcp_identity_line(line: str, allowed: frozenset[str]) -> list[str]:
    """Return the GCP deploy-identity KINDs on a line whose project is not allowed."""
    kinds: list[str] = []
    for match in _GCP_REGISTRY_PROJECT_RE.finditer(line):
        if match.group("project") not in allowed:
            kinds.append("GCP Artifact Registry project")
    for match in _GCP_SA_PROJECT_RE.finditer(line):
        if match.group("project") not in allowed:
            kinds.append("GCP service-account project")
    return kinds


def check_no_live_gcp_deploy_identity(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid real GCP deploy identity in committed Kustomize overlays (ADR-004-R14).

    Scans tracked files under ``platform/k8s/gcp/overlays/<environment>/`` for a
    GCP project id embedded in a container-registry root or a service-account
    email whose project is neither the tenant-neutral ``shifter-<environment>``
    placeholder nor the shared ``placeholder-project``. Real identity must be
    rendered at deploy time (``scripts/gcp/render_overlay_identity.py``), never
    committed. Detection is by GCP-context pattern; messages redact the value.
    """
    violations: list[Violation] = []
    for rel in _iter_identifier_candidates(repo_root, files):
        environment = _gcp_overlay_environment(rel)
        if environment is None or _identifier_skip(rel):
            continue
        path = repo_root / rel
        if not path.is_file():
            continue
        text = _read_text_safe(path)
        if text is None:
            continue
        allowed = _allowed_overlay_projects(environment)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for kind in _scan_gcp_identity_line(line, allowed):
                violations.append(
                    Violation(
                        check=_GCP_DEPLOY_IDENTITY_CHECK,
                        rule_id=_IDENTIFIER_RULE_ID,
                        path=rel,
                        message=(
                            f"line {lineno}: live {kind} in a committed GCP overlay "
                            "(value redacted); keep the tenant-neutral "
                            "`shifter-<environment>` placeholder - real deploy identity "
                            "is rendered at deploy time by "
                            "scripts/gcp/render_overlay_identity.py"
                        ),
                    )
                )
    return violations
