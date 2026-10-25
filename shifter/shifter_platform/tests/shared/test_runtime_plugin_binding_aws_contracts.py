"""AWS adapter image profiles accept the closed host contracts GCE images do (#2527, #2528)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.runtime_plugin_binding import RuntimeTargetImageProfile

AMI = "ami-0123456789abcdef0"
PRECONFIGURED = {
    "bootstrap_capability": "preconfigured-machine-host",
    "management_ssh_username": "hostadmin",
    "management_ssh_port": 2222,
    "participant_container_name": "workstation",
    "participant_username": "participant",
    "participant_readiness_contract": "participant-readiness/v1",
    "participant_readiness_manifest_sha256": "a" * 64,
}
PREPROMOTED = {
    "bootstrap_capability": "prepromoted-domain-controller",
    "domain_dns_name": "corp.example",
    "domain_netbios_name": "CORP",
}


@pytest.mark.parametrize("fields", [{}, PRECONFIGURED, PREPROMOTED])
def test_aws_profiles_accept_standard_preconfigured_and_prepromoted_contracts(fields):
    profile = RuntimeTargetImageProfile(provider="aws", image_ref=AMI, disk_type="gp3", **fields)
    assert profile.bootstrap_capability == fields.get("bootstrap_capability", "standard")


@pytest.mark.parametrize(
    "fields",
    [
        {**PRECONFIGURED, "participant_readiness_manifest_sha256": "not-a-digest"},
        {**PRECONFIGURED, "management_ssh_username": ""},
        {**PRECONFIGURED, "domain_dns_name": "corp.example"},
        {**PREPROMOTED, "domain_netbios_name": ""},
        {**PREPROMOTED, "participant_container_name": "workstation"},
        {"participant_username": "participant"},
        {"bootstrap_capability": "nested-hypervisor"},
        {**PRECONFIGURED, "disk_type": "io2"},
        {**PRECONFIGURED, "image_kind": "machine-image"},
    ],
)
def test_aws_profiles_refuse_incomplete_or_mixed_contracts(fields):
    with pytest.raises(ValidationError):
        RuntimeTargetImageProfile(provider="aws", image_ref=AMI, **fields)
