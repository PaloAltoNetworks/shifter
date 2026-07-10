"""Tests for the runtime configuration inventory checker."""

from __future__ import annotations

from pathlib import Path

from installation.runtime_inventory import (
    RUNTIME_SURFACES,
    RuntimeInventoryIssue,
    env_keys_from_file,
    validate_runtime_inventory,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_repo_runtime_inventory_is_current():
    assert validate_runtime_inventory(REPO_ROOT) == []


def test_runtime_surfaces_document_root_and_mcp_policy_boundaries():
    surfaces = {surface.path: surface for surface in RUNTIME_SURFACES}

    assert surfaces["shifter.yaml"].authority == "operator-authored root installation config"
    assert surfaces[".shifter.yaml"].authority == "checked-in MCP ops policy namespace"
    assert "secret" in surfaces[".env"].notes.lower()


def test_env_keys_from_file_returns_names_without_values(tmp_path):
    env_file = tmp_path / "runtime.env"
    env_file.write_text(
        """
        # comment
        FOO=do-not-print
        BAR=another-value
        """,
        encoding="utf-8",
    )

    assert env_keys_from_file(env_file) == ("FOO", "BAR")


def test_runtime_inventory_rejects_checked_in_generated_assignments(tmp_path):
    generated = tmp_path / "platform/k8s/gcp/overlays/gcp-dev/platform-runtime.generated.env"
    static = tmp_path / "platform/k8s/gcp/overlays/gcp-dev/platform-runtime.env"
    secret = tmp_path / "platform/k8s/gcp/overlays/gcp-dev/platform-runtime-secrets.env"
    generated.parent.mkdir(parents=True)
    generated.write_text("STORAGE_BUCKET_NAME=placeholder\n", encoding="utf-8")
    static.write_text("CLOUD_PROVIDER=gcp\n", encoding="utf-8")
    secret.write_text("", encoding="utf-8")

    issues = validate_runtime_inventory(tmp_path)

    assert issues
    rendered = "\n".join(issue.render() for issue in issues)
    assert "comment-only" in rendered
    assert "STORAGE_BUCKET_NAME" in rendered
    assert "placeholder" not in rendered


def test_runtime_inventory_detects_static_renderer_overlap(tmp_path):
    generated = tmp_path / "platform/k8s/gcp/overlays/gcp-dev/platform-runtime.generated.env"
    static = tmp_path / "platform/k8s/gcp/overlays/gcp-dev/platform-runtime.env"
    secret = tmp_path / "platform/k8s/gcp/overlays/gcp-dev/platform-runtime-secrets.env"
    generated.parent.mkdir(parents=True)
    generated.write_text("", encoding="utf-8")
    static.write_text("STORAGE_BUCKET_NAME=also-static\n", encoding="utf-8")
    secret.write_text("", encoding="utf-8")

    issues = validate_runtime_inventory(tmp_path)

    assert (
        RuntimeInventoryIssue(
            "platform/k8s/gcp/overlays/gcp-dev/platform-runtime.generated.env",
            "renderer-owned env keys duplicate keys from "
            "platform/k8s/gcp/overlays/gcp-dev/platform-runtime.env: STORAGE_BUCKET_NAME",
        )
        in issues
    )


def test_runtime_inventory_cli_check_exits_zero(capsys):
    from installation.cli import main

    assert main(["runtime-inventory", "--repo-root", str(REPO_ROOT), "--check"]) == 0

    captured = capsys.readouterr()
    assert "runtime inventory is current" in captured.out


def test_runtime_inventory_cli_lists_surfaces(capsys):
    from installation.cli import main

    assert main(["runtime-inventory"]) == 0

    captured = capsys.readouterr()
    listed_lines = [line for line in captured.out.splitlines() if line.startswith("- ")]
    assert len(listed_lines) == len(RUNTIME_SURFACES)
    assert "shifter.yaml" in captured.out
    assert ".shifter.yaml" in captured.out
    assert "platform-runtime.generated.env" in captured.out
