"""The foundation migration must not change unrelated infrastructure."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_image_network_plan import _MODULE_PREFIX, _RESOURCES, validate_plan


def _plan() -> dict:
    resources = [
        {
            "previous_address": name,
            "address": _MODULE_PREFIX + name,
            "change": {"actions": ["no-op"]},
        }
        for name in _RESOURCES
    ]
    firewall = next(resource for resource in resources if "image_build_iap" in resource["address"])
    firewall["change"] = {
        "actions": ["update"],
        "before": {"name": "example-image-build-iap", "allow": [{"protocol": "tcp", "ports": ["22", "5986"]}]},
        "after": {
            "name": "example-image-build-iap",
            "allow": [{"protocol": "tcp", "ports": ["22", "2222", "5986"]}],
        },
    }
    return {"resource_changes": resources, "output_changes": {"network": {"actions": ["no-op"]}}}


class ImageNetworkPlanTests(unittest.TestCase):
    def test_accepts_all_six_moves_and_only_port_2222(self) -> None:
        self.assertEqual(validate_plan(_plan()), (6, 1))

    def test_rejects_partial_move(self) -> None:
        plan = _plan()
        plan["resource_changes"].pop()
        with self.assertRaisesRegex(ValueError, "only part"):
            validate_plan(plan)

    def test_rejects_other_firewall_change(self) -> None:
        plan = copy.deepcopy(_plan())
        plan["resource_changes"][4]["change"]["after"]["name"] = "replacement"
        with self.assertRaisesRegex(ValueError, "Unexpected Terraform resource action"):
            validate_plan(plan)

    def test_rejects_other_resource_action(self) -> None:
        plan = _plan()
        plan["resource_changes"].append(
            {"address": "module.cicd_oidc_identity.google_service_account.deploy", "change": {"actions": ["delete"]}}
        )
        with self.assertRaisesRegex(ValueError, "Unexpected Terraform resource action"):
            validate_plan(plan)

    def test_allows_iam_policy_etag_refresh_only(self) -> None:
        plan = _plan()
        plan["resource_drift"] = [
            {
                "address": "module.cicd_oidc_identity.google_project_iam_member.deploy_roles",
                "change": {
                    "actions": ["update"],
                    "before": {"role": "roles/example", "etag": "old"},
                    "after": {"role": "roles/example", "etag": "new"},
                },
            }
        ]
        self.assertEqual(validate_plan(plan), (6, 1))
        plan["resource_drift"][0]["change"]["after"]["role"] = "roles/changed"
        with self.assertRaisesRegex(ValueError, "resource drift"):
            validate_plan(plan)


if __name__ == "__main__":
    unittest.main()
