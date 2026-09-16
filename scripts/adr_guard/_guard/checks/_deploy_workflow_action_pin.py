"""ADR-037-R1: cloud-credentialed workflows pin every action to an immutable ref.

Every non-local `uses:` action in a cloud-credentialed workflow is an executable
dependency that runs with cloud credentials; a mutable tag can be moved by a
compromised or careless maintainer, so it must resolve to a full 40-hex commit
SHA (supply-chain provenance, issue #1519). This mirrors the `_dw_*`
workflow-as-data model rather than string-matching workflow text, and fails
closed: a workflow that cannot be parsed cannot be classified.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from .._common import (
    Violation,
    is_guard_source_path,
)
from .._workflow_model import (
    _DwShapeError,
    _dw_is_self_hosted,
    _dw_load_workflow,
)


_ACTION_PIN_CHECK = "workflow-action-sha-pinning"
_ACTION_PIN_RULE = "ADR-037-R1"
_ACTION_PIN_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_ACTION_PIN_OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CLOUD_AUTH_ACTIONS = (
    "aws-actions/configure-aws-credentials",
    "google-github-actions/auth",
)


def _action_pin_violation(path: str, message: str) -> Violation:
    """Build an ADR-037-R1 violation for the action-pinning check."""
    return Violation(_ACTION_PIN_CHECK, _ACTION_PIN_RULE, path, message)


def _dw_iter_workflow_files(repo_root: Path) -> list[str]:
    """Repo-relative paths of every GitHub Actions workflow file, sorted."""
    wf_dir = repo_root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return []
    return sorted(
        f".github/workflows/{p.name}"
        for p in wf_dir.iterdir()
        if p.is_file() and p.suffix in (".yml", ".yaml")
    )


def _dw_permissions_grant_id_token(perms: object) -> bool:
    """True when a `permissions:` value grants OIDC `id-token: write`."""
    if isinstance(perms, str):
        return perms.strip().lower() == "write-all"
    if isinstance(perms, dict):
        return str(perms.get("id-token", "")).strip().lower() == "write"
    return False


def _dw_job_steps(job: dict[str, object]) -> list[object]:
    """Return a job's `steps:` list, or [] when it declares none."""
    steps = job.get("steps")
    return steps if isinstance(steps, list) else []


def _dw_step_uses(step: object) -> str | None:
    """Return a step's `uses:` reference, or None when it is not an action step."""
    if isinstance(step, dict):
        uses = step.get("uses")
        if isinstance(uses, str):
            return uses.strip()
    return None


def _dw_step_uses_cloud_auth(step: object) -> bool:
    """True when a step authenticates to AWS or GCP."""
    uses = _dw_step_uses(step)
    if uses and any(
        uses == a or uses.startswith(a + "@") for a in _CLOUD_AUTH_ACTIONS
    ):
        return True
    if isinstance(step, dict):
        with_block = step.get("with")
        if isinstance(with_block, dict) and "workload_identity_provider" in with_block:
            return True
    return False


# A hijacked mutable-tag action can exfiltrate any secret the job holds, not
# only OIDC/self-hosted cloud identity, so a static or inherited secret makes a
# workflow credential-bearing for ADR-037-R1 (issue #998 codex review). Match
# `${{ secrets.X }}` references; GITHUB_TOKEN is excluded because it is present
# by default in nearly every workflow and its elevated (write / id-token) uses
# are already covered by the permission and OIDC markers above, so counting it
# would flag effectively every workflow rather than the genuinely credentialed
# ones this rule targets.
_DW_NAMED_SECRET_RE = re.compile(r"secrets\.([A-Za-z_][A-Za-z0-9_-]*)")


def _dw_iter_strings(node: object) -> Iterator[str]:
    """Yield every string leaf of a parsed-YAML subtree."""
    if isinstance(node, dict):
        for value in node.values():
            yield from _dw_iter_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _dw_iter_strings(item)
    elif isinstance(node, str):
        yield node


def _dw_references_named_secret(node: object) -> bool:
    """True if the YAML subtree references any ``secrets.X`` except GITHUB_TOKEN."""
    return any(
        name != "GITHUB_TOKEN"
        for text in _dw_iter_strings(node)
        for name in _DW_NAMED_SECRET_RE.findall(text)
    )


def _dw_job_forwards_secrets(job: dict[str, object]) -> bool:
    """True if a reusable-workflow-call job forwards secrets to the callee.

    Covers both ``secrets: inherit`` (all secrets forwarded) and an explicit
    ``secrets:`` mapping that passes a named secret.
    """
    secrets = job.get("secrets")
    if isinstance(secrets, str):
        return secrets.strip().lower() == "inherit"
    if isinstance(secrets, dict):
        return _dw_references_named_secret(secrets)
    return False


def _dw_job_is_cloud_credentialed(job: dict[str, object]) -> bool:
    """True when a job holds real credentials in any recognized form."""
    return (
        _dw_permissions_grant_id_token(job.get("permissions"))
        or _dw_is_self_hosted(job)
        or _dw_job_forwards_secrets(job)
        or _dw_references_named_secret(job)
        or any(_dw_step_uses_cloud_auth(step) for step in _dw_job_steps(job))
    )


def _dw_workflow_is_cloud_credentialed(wf: dict[str, object]) -> bool:
    """True when a workflow hands a job real credentials in any form.

    Markers: top-level or job-level ``id-token: write`` (or ``write-all``), a
    self-hosted runner, a cloud-auth action, a ``workload_identity_provider``
    input, a job that references or forwards a named secret (static ``env`` /
    ``with`` secrets, ``secrets:`` mappings, or ``secrets: inherit``), or a
    workflow-level ``env`` that injects a named secret into every job. Any one is
    sufficient; the classifier fails toward "credentialed" so an unpinned action
    is never silently exempted. GITHUB_TOKEN alone does not qualify (see
    ``_DW_NAMED_SECRET_RE``).
    """
    if _dw_permissions_grant_id_token(wf.get("permissions")):
        return True
    jobs = wf.get("jobs")
    if not isinstance(jobs, dict):
        return False
    return any(
        _dw_job_is_cloud_credentialed(job)
        for job in jobs.values()
        if isinstance(job, dict)
    ) or _dw_references_named_secret(wf.get("env"))


def _dw_iter_uses_refs(wf: dict[str, object]) -> Iterator[tuple[str, str]]:
    """Yield ``(job_id, uses_ref)`` for every job- and step-level ``uses:``."""
    jobs = wf.get("jobs")
    if not isinstance(jobs, dict):
        return
    for jid, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_uses = job.get("uses")
        if isinstance(job_uses, str):
            yield jid, job_uses.strip()
        for step in _dw_job_steps(job):
            uses = _dw_step_uses(step)
            if uses:
                yield jid, uses


def _dw_uses_is_sha_pinned(ref: str) -> bool:
    """True when a `uses:` ref pins an immutable commit SHA or OCI digest."""
    parts = ref.rsplit("@", 1)
    if len(parts) != 2:
        return False
    after = parts[1]
    # Repository actions pin a 40-hex git commit SHA; container (`docker://`)
    # actions pin an OCI `sha256:<64 hex>` digest. Both are immutable.
    return bool(_ACTION_PIN_SHA40.match(after) or _ACTION_PIN_OCI_DIGEST.match(after))


def _workflow_action_pin_relevant(files: list[str] | None) -> bool:
    """True when a changed file can affect ADR-037-R1 action pinning."""
    if files is None:
        return True
    return any(
        f.startswith(".github/workflows/") or is_guard_source_path(f)
        for f in files
    )


def _action_pin_hint(ref: str) -> str:
    """Describe the immutable ref form ADR-037-R1 requires for this action."""
    if ref.startswith("docker://"):
        return "an OCI 'sha256:<64 hex>' digest"
    return "a full 40-hex commit SHA (keep a '# <version>' comment for Dependabot)"


def _action_pin_violations_for_workflow(rel: str, wf: dict[str, object]) -> list[Violation]:
    """Unpinned ``uses:`` refs in one cloud-credentialed workflow."""
    violations: list[Violation] = []
    for jid, ref in _dw_iter_uses_refs(wf):
        # Local reusable-workflow refs (`./...`) are first-party and exempt.
        # `docker://` container actions are NOT exempt: they are remote
        # executable dependencies too, so they must pin an OCI digest.
        if ref.startswith("./") or _dw_uses_is_sha_pinned(ref):
            continue
        violations.append(
            _action_pin_violation(
                rel,
                f"job '{jid}' uses '{ref}' with a mutable ref; "
                f"ADR-037-R1 requires {_action_pin_hint(ref)} in cloud-credentialed workflows",
            )
        )
    return violations


def check_workflow_action_sha_pinning(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """Cloud-credentialed workflows pin every action to a full SHA (ADR-037-R1).

    Enumerates every ``.github/workflows/*.yml`` as data, classifies each as
    cloud-credentialed, and requires every non-local ``uses:`` reference in a
    credentialed workflow to be a full 40-hex commit SHA. Fails closed: a
    workflow that cannot be parsed cannot be classified, so it is reported.
    ``actions/*`` is included - GitHub-owned actions are executable dependencies
    too, as are ``docker://`` container actions, which must pin an OCI
    ``sha256:<64 hex>`` digest. Only local reusable-workflow refs (``./...``) are
    exempt.
    """
    # Local import: keeps PyYAML optional for non-workflow checks.
    import yaml

    if not _workflow_action_pin_relevant(files):
        return []

    violations: list[Violation] = []
    for rel in _dw_iter_workflow_files(repo_root):
        try:
            wf = _dw_load_workflow(repo_root, rel)
        except (_DwShapeError, yaml.YAMLError) as exc:
            violations.append(
                _action_pin_violation(
                    rel,
                    "workflow could not be parsed for ADR-037-R1, so its "
                    f"cloud-credential status cannot be verified: {exc}",
                )
            )
            continue
        if _dw_workflow_is_cloud_credentialed(wf):
            violations.extend(_action_pin_violations_for_workflow(rel, wf))
    return violations
