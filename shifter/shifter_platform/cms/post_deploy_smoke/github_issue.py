"""GitHub issue create/update helpers for failed post-deploy smoke runs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SmokeIssuePayload:
    """Structured fields for a failed post-deploy smoke GitHub issue."""

    environment: str
    provider: str
    variant: str
    commit_sha: str
    workflow_run_url: str
    summary: str
    log_excerpt: str


def issue_title(payload: SmokeIssuePayload) -> str:
    """Build the GitHub issue title for a failed smoke run."""
    short_sha = payload.commit_sha[:12]
    return f"[smoke-test][{payload.environment}][{payload.variant}] {short_sha}"


def issue_body(payload: SmokeIssuePayload) -> str:
    """Render the GitHub issue body for a failed smoke run."""
    return "\n".join(
        [
            "## Post-deploy smoke test failed",
            "",
            f"- Environment: `{payload.environment}`",
            f"- Provider: `{payload.provider}`",
            f"- Variant: `{payload.variant}`",
            f"- Commit: `{payload.commit_sha}`",
            f"- Workflow run: {payload.workflow_run_url}",
            "",
            "### Summary",
            payload.summary.strip() or "_No summary provided._",
            "",
            "### Log excerpt",
            "```text",
            payload.log_excerpt.strip() or "(empty)",
            "```",
        ]
    )


def issue_labels() -> list[str]:
    """Return default labels applied to smoke failure issues."""
    return ["bug", "smoke-test"]
