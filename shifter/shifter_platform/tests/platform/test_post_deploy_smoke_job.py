"""Workflow invariants for post-deploy range smoke (#218)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PLATFORM_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "_shifter-platform.yml"
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "smoke-test.sh"
WINDOWS_SCRIPT = REPO_ROOT / "scripts" / "smoke-test-windows.sh"


def test_platform_workflow_declares_post_deploy_smoke_job() -> None:
    text = PLATFORM_WORKFLOW.read_text(encoding="utf-8")
    assert "post-deploy-smoke:" in text
    assert "continue-on-error: true" in text
    assert "scripts/smoke-test.sh" in text
    start = text.index("post-deploy-smoke:")
    block = text[start : start + 800]
    assert "needs: verify" in block or "needs: [verify]" in block


def test_post_deploy_smoke_job_is_dev_only() -> None:
    text = PLATFORM_WORKFLOW.read_text(encoding="utf-8")
    assert "inputs.is_dev" in text
    start = text.index("post-deploy-smoke:")
    assert "inputs.is_dev" in text[start : start + 800]


def test_smoke_entrypoints_exist() -> None:
    assert SMOKE_SCRIPT.is_file()
    assert WINDOWS_SCRIPT.is_file()
    assert "run_post_deploy_smoke" in SMOKE_SCRIPT.read_text(encoding="utf-8")
