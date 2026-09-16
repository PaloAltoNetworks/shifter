"""Only registered, trusted and accessible pack requirements can request work."""

import json
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from rest_framework.test import APIClient

from cms.models import RaesPackageSource, ScenarioMetadata
from engine.models import PreparationAttempt
from tests.engine.services.test_preparation_operations import administrator, grant, installed, operator
from tests.shared.raes.test_preparation_contract import requirement_payload
from tests.shared.raes.test_preparation_inputs import input_material_fixture

pytestmark = pytest.mark.django_db
__all__ = ["administrator", "grant", "installed", "operator"]
URL = "/api/v1/cms/artifact-preparation/"


@pytest.fixture
def registered_pack(operator, tmp_path, monkeypatch):
    from raes.scenarios import load_scenario
    from raes_env_packs.publication import authored_artifact_requirements

    template = Path(__file__).parents[1] / "shared/raes/fixtures/launchable/shifter-launch-min.sdl.yaml"
    raw = yaml.safe_load(template.read_text())
    raw["nodes"]["web"]["source"]["artifact_requirement"] = requirement_payload()
    (tmp_path / "sdl").mkdir()
    scenario = tmp_path / "sdl/private.sdl.yaml"
    scenario.write_text(yaml.safe_dump(raw))
    _, _, input_manifest, input_descriptor = input_material_fixture()
    (tmp_path / "base-manifest").write_text(json.dumps(input_manifest))
    (tmp_path / "preparation").mkdir()
    (tmp_path / "preparation/base.json").write_bytes(input_descriptor)
    address = next(iter(authored_artifact_requirements([load_scenario(scenario)])))
    source = RaesPackageSource.objects.create(
        scenario_id="private-preparation",
        source_kind="repo",
        contract_kind="raes",
        contract_profile="shifter",
        package_ref="private-preparation",
        package_version="1",
        package_digest="sha256:" + "3" * 64,
        conformance_status="passed",
        registered_by=operator,
    )

    @contextmanager
    def trusted_path(source):
        yield scenario, None

    monkeypatch.setattr("cms.scenarios.preparation._trusted_scenario_path", trusted_path)
    return source, address


def request_body(installed, registered_pack):
    source, address = registered_pack
    return {
        "scenario_id": source.scenario_id,
        "requirement_address": address,
        "adapter_id": str(installed.id),
        "specification_id": "example-image",
    }


def test_registered_private_pack_uses_authored_requirement_and_optional_lock(operator, installed, registered_pack):
    client = APIClient()
    client.force_authenticate(user=operator)
    response = client.post(URL, request_body(installed, registered_pack), format="json")
    assert response.status_code == 202, response.json()
    attempt = PreparationAttempt.objects.get()
    assert attempt.input["package"]["requirement_address"] == registered_pack[1]
    assert attempt.input["package"]["lock_digest"] == ""
    assert attempt.input["package"]["requirement"]["locked_inputs"] == requirement_payload()["locked_inputs"]
    assert attempt.input["package"]["input_bindings"][0]["image_id"] == "12345"
    identity = response.json()["id"]
    assert client.get(f"{URL}{identity}/").status_code == 200
    cancelled = client.post(f"{URL}{identity}/cancel/", {}, format="json")
    assert cancelled.json()["state"] == "cancelled"
    assert client.post(f"{URL}{identity}/retry/", {}, format="json").status_code == 400


@pytest.mark.parametrize("failure", ["pending", "no-digest", "foreign-address", "staff-only", "override"])
def test_untrusted_or_inaccessible_pack_never_creates_worker(operator, installed, registered_pack, failure):
    source, _ = registered_pack
    body = request_body(installed, registered_pack)
    if failure == "pending":
        source.conformance_status = "pending"
        source.save()
    elif failure == "no-digest":
        RaesPackageSource.objects.filter(pk=source.pk).update(package_digest="")
    elif failure == "staff-only":
        ScenarioMetadata.objects.create(scenario_id=source.scenario_id, staff_only=True, updated_by=operator)
    elif failure == "foreign-address":
        body["requirement_address"] = "private-image"
    else:
        body["requirement"] = requirement_payload()
    client = APIClient()
    client.force_authenticate(user=operator)
    response = client.post(URL, body, format="json")
    assert response.status_code in {400, 403}, response.json()
    assert not PreparationAttempt.objects.exists()
