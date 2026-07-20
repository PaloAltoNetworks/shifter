"""End-to-end hydrator tests for CTF scenario templates."""

import pytest
from django.contrib.auth import get_user_model

from cms.exceptions import CMSError
from cms.scenarios.hydrator import hydrate_ctf
from shared.schemas import CTFRangeSpec

pytestmark = pytest.mark.django_db

User = get_user_model()

# Minimal CTF/hospital contract fixture (range section only), aligned with
# penumbra-scenarios/scenarios/hospital/sdl/ctf-min-fixture.yaml.
AURORA_MIN_CTF_DEF = {
    "scenario_type": "ctf",
    "cyberscript_version": "v1",
    "zones": [
        {
            "name": "clinical",
            "kind": "clinical",
            "description": "Clinical-floor zone (minimal fixture)",
            "networks": ["clinical-core"],
        }
    ],
    "networks": [
        {
            "name": "clinical-core",
            "zone": "clinical",
            "isolation": "default_deny",
            "gdc": {
                "nad_name": "nad-clinical-core",
                "vlan_id": 30,
                "cidr": "10.20.30.0/24",
                "gateway": "10.20.30.1",
            },
        }
    ],
    "assets": [
        {
            "name": "ehr-app",
            "asset_type": "scenario_pod",
            "role": "victim",
            "os_type": "ubuntu",
            "zone": "clinical",
            "scope": "shared",
            "image": "aurora-openemr:7.0",
            "networks": [{"network": "clinical-core", "primary": True}],
            "services": ["ehr"],
        }
    ],
    "services": [
        {
            "name": "ehr",
            "service_type": "ehr",
            "primary_asset": "ehr-app",
            "exposed_endpoints": [{"name": "web", "proto": "https", "port": 443, "path": "/"}],
        }
    ],
    "forests": [],
    "flags": [],
    "data_seeds": [
        {
            "seed_type": "synthea",
            "population_size": 200,
            "state": "Massachusetts",
            "formats": ["fhir_r4"],
            "into_service": "ehr",
        }
    ],
    "detection": {
        "enabled": True,
        "siem": "wazuh",
        "ids": "suricata",
        "runtime": "falco",
        "soc_zone": "clinical",
        "participant_visible": False,
    },
    "participant_access": {
        "kali_image": "aurora-kali:latest",
        "kali_networks": ["clinical-core"],
        "guacamole_enabled": True,
        "terminal_type": "xterm.js",
    },
}


def _db_ctf_scenario(scenario_id: str):
    from cms.models import Scenario

    staff = User.objects.create_user(
        username=f"ctf-author-{scenario_id}@example.com",
        email=f"ctf-author-{scenario_id}@example.com",
        is_staff=True,
    )
    return Scenario.objects.create(
        scenario_id=scenario_id,
        name="AURORA-MIN",
        description="Minimal CTF/hospital contract fixture",
        definition=AURORA_MIN_CTF_DEF,
        created_by=staff,
        updated_by=staff,
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(username="ctf-hydrator@example.com", email="ctf-hydrator@example.com")


@pytest.fixture
def aurora_min_scenario(db):
    return _db_ctf_scenario("aurora-min")


class TestHydrateCtf:
    def test_hydrates_valid_ctf_range_spec(self, user, aurora_min_scenario):
        result = hydrate_ctf(aurora_min_scenario.scenario_id, user.id)
        assert isinstance(result, CTFRangeSpec)
        assert result.range_type == "ctf"
        assert result.cyberscript_version == "v1"
        assert result.scenario_id == "aurora-min"
        assert result.user_id == user.id
        assert result.subnets == []
        assert len(result.zones) == 1
        assert len(result.assets) == 1
        assert result.flags == []

    def test_raises_for_unknown_scenario(self, user):
        with pytest.raises(CMSError, match="not found"):
            hydrate_ctf("missing-ctf-scenario", user.id)

    def test_raises_for_demo_scenario(self, user, db):
        from cms.models import Scenario

        staff = User.objects.create_user(
            username="demo-author@example.com",
            email="demo-author@example.com",
            is_staff=True,
        )
        demo = Scenario.objects.create(
            scenario_id="hydrator-demo-only",
            name="Demo",
            description="Demo scenario",
            definition={
                "instances": [
                    {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
                ],
                "subnets": [{"name": "core", "instances": ["Attacker"]}],
                "ngfw": False,
            },
            created_by=staff,
            updated_by=staff,
        )
        with pytest.raises(CMSError, match="not a CTF scenario"):
            hydrate_ctf(demo.scenario_id, user.id)
