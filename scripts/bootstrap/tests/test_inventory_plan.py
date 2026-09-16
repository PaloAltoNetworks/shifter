"""Operator-visible plan evidence survives temporary Terraform execution trees."""

import json

import pytest
from installation.errors import InstallationConfigError

from inventory_plan import create_plan_directory, publish_plan


@pytest.mark.parametrize("actions", [["no-op"], ["update"], ["delete"], ["create", "delete"]])
def test_private_plan_evidence_distinguishes_drift_without_printing_values(tmp_path, capsys, actions):
    destination = create_plan_directory(tmp_path / "review")
    binary = tmp_path / "identity.plan"
    binary.write_bytes(b"private-binary-plan")
    plan = {
        "resource_changes": [
            {
                "address": "google_service_account_iam_member.old_caller",
                "type": "google_service_account_iam_member",
                "change": {
                    "actions": actions,
                    "before": {"member": "PRIVATE-OLD-PRINCIPAL"},
                    "after": {"member": "PRIVATE-NEW-PRINCIPAL"},
                },
            }
        ],
    }
    summary = publish_plan("identity", plan, binary, destination)
    binary.unlink()
    assert summary["has_changes"] is (actions != ["no-op"])
    assert summary["resources"][0]["actions"] == actions
    assert summary["resources"][0]["address"] == "google_service_account_iam_member.old_caller"
    output = capsys.readouterr().out
    assert "PRIVATE-" not in output and "private-binary-plan" not in output
    assert json.loads(output)["plan"]["has_changes"] is summary["has_changes"]
    saved = json.loads((destination / "identity.plan.json").read_text())
    assert saved == plan
    assert (destination / "identity.plan").read_bytes() == b"private-binary-plan"
    assert (destination.stat().st_mode & 0o777) == 0o700
    assert all((path.stat().st_mode & 0o777) == 0o600 for path in destination.iterdir())


def test_plan_destination_cannot_overwrite_existing_evidence_or_follow_symlink(tmp_path):
    destination = create_plan_directory(tmp_path / "review")
    (destination / "prior").write_text("preserve")
    (tmp_path / "link").symlink_to(destination)
    for path in (destination, tmp_path / "link"):
        with pytest.raises(InstallationConfigError):
            create_plan_directory(path)
    assert (destination / "prior").read_text() == "preserve"
