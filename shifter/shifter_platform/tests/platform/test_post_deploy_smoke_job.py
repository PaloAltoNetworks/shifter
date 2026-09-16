"""Workflow invariants for post-deploy range smoke (#218)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PLATFORM_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "_shifter-platform.yml"
GCP_DEV_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "_gcp-dev.yml"
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "smoke-test.sh"
GCP_SMOKE_SCRIPT = REPO_ROOT / "scripts" / "smoke-test-gcp.sh"
WINDOWS_SCRIPT = REPO_ROOT / "scripts" / "smoke-test-windows.sh"


def test_platform_workflow_declares_post_deploy_smoke_job() -> None:
    text = PLATFORM_WORKFLOW.read_text(encoding="utf-8")
    assert "post-deploy-smoke:" in text
    assert "continue-on-error: true" in text
    assert "scripts/smoke-test.sh" in text
    start = text.index("post-deploy-smoke:")
    block = text[start : start + 800]
    assert "needs: eks-deploy" in block or "needs: [eks-deploy]" in block
    assert "needs.eks-deploy.result == 'success'" in block
    assert "github.event_name != 'pull_request'" in block


def test_post_deploy_smoke_job_is_dev_only() -> None:
    text = PLATFORM_WORKFLOW.read_text(encoding="utf-8")
    assert "inputs.is_dev" in text
    start = text.index("post-deploy-smoke:")
    block = text[start : start + 800]
    assert "inputs.is_dev" in block
    assert "github.event_name != 'pull_request'" in block


def test_smoke_entrypoints_exist() -> None:
    assert SMOKE_SCRIPT.is_file()
    assert GCP_SMOKE_SCRIPT.is_file()
    assert WINDOWS_SCRIPT.is_file()
    assert "run_post_deploy_smoke" in SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "run_post_deploy_smoke" in GCP_SMOKE_SCRIPT.read_text(encoding="utf-8")


def test_gcp_dev_workflow_declares_post_deploy_smoke_job() -> None:
    text = GCP_DEV_WORKFLOW.read_text(encoding="utf-8")
    assert "post-deploy-smoke:" in text
    assert "continue-on-error: true" in text
    assert "scripts/smoke-test-gcp.sh" in text
    start = text.index("post-deploy-smoke:")
    block = text[start : start + 1200]
    assert "needs: deploy" in block or "needs: [deploy]" in block
    assert "needs.deploy.result == 'success'" in block
    assert "inputs.deploy_changes" in block
    assert "github.event_name != 'pull_request'" in block
    assert "SMOKE_TEST_USER_EMAIL" in block


def test_deploy_workflow_forwards_smoke_secret_to_gcp_dev() -> None:
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    start = text.index("gcp-dev:")
    block = text[start : start + 3200]
    assert "SMOKE_TEST_USER_EMAIL" in block
    assert "issues: write" in block
