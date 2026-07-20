"""Static plan-leak checker for GCE range cells (issue #1347).

These tests render a real range-cell plan, confirm the honest plan trips no
cross-range leak, then inject the exact anti-patterns preflight-1345 warns about
(a broad allow spanning the shared range VPC, a universal egress allow, a peer
range's subnet as an allow source) and confirm the checker names the leaked
boundary. This satisfies issue #1347 acceptance criterion 1 without any cloud
call.
"""

from __future__ import annotations

from copy import deepcopy

from shared.range_cells import build_gcp_vm_range_cell_request, build_scenario_artifact
from shared.range_escape import BoundaryCode

from config import GCERangeCellConfig, GCERangeImageProfile
from gcp_range_cell_escape_checks import find_cross_range_leaks
from gcp_range_cells import render_range_cell_plan

# The shared range VPC base CIDR that per-range /28 subnets are carved from.
RANGE_NETWORK_CIDR = "10.50.0.0/16"


def _shared_vpc_config() -> GCERangeCellConfig:
    profile = GCERangeImageProfile(
        source_image="projects/debian-cloud/global/images/family/debian-12",
        machine_type="e2-standard-2",
        disk_size_gb=50,
    )
    return GCERangeCellConfig(
        project_id="test-project",
        region="us-central1",
        zone="us-central1-b",
        network_mode="shared-vpc",
        network_id="projects/test-project/global/networks/shared-range",
        service_account_email="range-host@test-project.iam.gserviceaccount.com",
        linux=profile,
        kali=profile,
        dc=profile,
        portal_network_cidrs=("10.40.0.0/20",),
        private_google_access=True,
    )


def _variables() -> dict:
    payload = {
        "scenario_id": "scenario-a",
        "user_id": 7,
        "subnets": [
            {
                "name": "polaris",
                "uuid": "subnet-uuid",
                "instances": [
                    {"uuid": "linux-uuid", "name": "kali", "role": "attacker", "os_type": "kali"},
                ],
            }
        ],
        "participant_access": [{"target_ref": "linux-uuid", "channel": "ssh"}],
    }
    bindings = [{"subnet_ref": "subnet-uuid", "cidr": "10.50.2.0/28"}]
    return build_gcp_vm_range_cell_request(
        request_id="req-123",
        range_id=42,
        scenario_artifact=build_scenario_artifact(
            {"spec_schema": "range_spec", "spec_version": "1", "payload": payload}
        ),
        network_bindings=bindings,
        access_declarations=payload["participant_access"],
    )


def _honest_plan() -> dict:
    return render_range_cell_plan("req-123", _variables(), _shared_vpc_config())


def test_honest_plan_has_no_cross_range_leaks() -> None:
    plan = _honest_plan()
    assert find_cross_range_leaks(plan, range_network_cidr=RANGE_NETWORK_CIDR) == []


def test_injected_broad_cross_range_ingress_allow_is_flagged() -> None:
    plan = _honest_plan()
    plan["firewalls"].append(
        {
            "name": "shifter-r-42-oops-cross-range",
            "direction": "INGRESS",
            "priority": 500,
            "target_tags": ["shifter-range-42"],
            "source_ranges": [RANGE_NETWORK_CIDR],
            "allowed": [{"IPProtocol": "all"}],
        }
    )
    leaks = find_cross_range_leaks(plan, range_network_cidr=RANGE_NETWORK_CIDR)
    assert [leak.boundary_code for leak in leaks] == [BoundaryCode.CROSS_RANGE_PRIVATE_IP]
    assert leaks[0].firewall_name == "shifter-r-42-oops-cross-range"
    assert leaks[0].cidr == RANGE_NETWORK_CIDR


def test_peer_range_subnet_source_is_flagged() -> None:
    plan = _honest_plan()
    plan["firewalls"].append(
        {
            "name": "shifter-r-42-peer-leak",
            "direction": "INGRESS",
            "priority": 500,
            "target_tags": ["shifter-range-42"],
            "source_ranges": ["10.50.3.0/28"],  # a different range's subnet
            "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}],
        }
    )
    leaks = find_cross_range_leaks(plan, range_network_cidr=RANGE_NETWORK_CIDR)
    assert len(leaks) == 1
    assert leaks[0].boundary_code is BoundaryCode.CROSS_RANGE_PRIVATE_IP


def test_universal_egress_allow_is_flagged_as_internet_egress() -> None:
    plan = _honest_plan()
    plan["firewalls"].append(
        {
            "name": "shifter-r-42-egress-world",
            "direction": "EGRESS",
            "priority": 500,
            "target_tags": ["shifter-range-42"],
            "destination_ranges": ["0.0.0.0/0"],
            "allowed": [{"IPProtocol": "all"}],
        }
    )
    leaks = find_cross_range_leaks(plan, range_network_cidr=RANGE_NETWORK_CIDR)
    assert [leak.boundary_code for leak in leaks] == [BoundaryCode.INTERNET_EGRESS]


def test_deny_rules_are_not_leaks() -> None:
    # The baseline plan's 0.0.0.0/0 EGRESS deny (priority 65534) must never be a leak.
    plan = _honest_plan()
    deny_names = [fw["name"] for fw in plan["firewalls"] if fw.get("denied")]
    assert deny_names, "expected the baseline egress-deny rule in the rendered plan"
    assert find_cross_range_leaks(plan, range_network_cidr=RANGE_NETWORK_CIDR) == []


def test_checker_does_not_mutate_plan() -> None:
    plan = _honest_plan()
    before = deepcopy(plan["firewalls"])
    find_cross_range_leaks(plan, range_network_cidr=RANGE_NETWORK_CIDR)
    assert plan["firewalls"] == before


def test_ingress_allow_without_source_ranges_is_universal_leak() -> None:
    # GCP defaults a source-less ingress allow to 0.0.0.0/0; the checker must not
    # treat the absent field as "nothing to check".
    plan = _honest_plan()
    plan["firewalls"].append(
        {
            "name": "shifter-r-42-default-ingress",
            "direction": "INGRESS",
            "priority": 500,
            "target_tags": ["shifter-range-42"],
            "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}],
        }
    )
    leaks = find_cross_range_leaks(plan, range_network_cidr=RANGE_NETWORK_CIDR)
    assert [leak.boundary_code for leak in leaks] == [BoundaryCode.CROSS_RANGE_PRIVATE_IP]
    assert leaks[0].cidr == "0.0.0.0/0"


def test_egress_allow_without_destination_ranges_is_universal_leak() -> None:
    plan = _honest_plan()
    plan["firewalls"].append(
        {
            "name": "shifter-r-42-default-egress",
            "direction": "EGRESS",
            "priority": 500,
            "target_tags": ["shifter-range-42"],
            "allowed": [{"IPProtocol": "all"}],
        }
    )
    leaks = find_cross_range_leaks(plan, range_network_cidr=RANGE_NETWORK_CIDR)
    assert [leak.boundary_code for leak in leaks] == [BoundaryCode.INTERNET_EGRESS]
