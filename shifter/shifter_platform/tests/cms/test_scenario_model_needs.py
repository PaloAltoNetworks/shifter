"""Per-pack scenario→model-need overlay and its projection (PLAT-202, #2119).

The overlay is Shifter-owned, staff-authored, digest-bound metadata that rides
the runtime pack lifecycle (not the deploy-time mounted catalog). The projection
verifies the registered pack's current digest against the digest the need was
authored against so a re-registered pack cannot inherit a stale binding.
"""

from __future__ import annotations

import pytest

from cms.models import RaesPackageSource, ScenarioModelNeeds
from cms.scenarios.model_needs import project_scenario_model_needs
from shared.model_access import ScenarioNeed
from shared.model_access.catalog import ContractError

pytestmark = pytest.mark.django_db

_DIGEST = "sha256:" + "a" * 64
_OTHER = "sha256:" + "b" * 64


def _limits() -> dict:
    return {
        "max_request_seconds": 120,
        "max_request_bytes": 1_000_000,
        "max_input_tokens": 8_000,
        "max_output_tokens": 2_000,
        "max_requests_per_window": 60,
        "request_window_seconds": 60,
        "max_spend_micro_units": 5_000_000,
        "currency": "USD",
        "max_concurrent_requests": 2,
    }


def _need_payload(*, digest: str = _DIGEST, workload: str = "participant", required: bool = True) -> dict:
    return {
        "contract_version": "model-access-scenario/v1",
        "scenario_digest": digest,
        "workload_role": workload,
        "profile_id": "coding",
        "required": required,
        "required_capabilities": ["messages"],
        "allowed_capabilities": ["messages"],
        "allowed_strategies": ["fixed-v1"],
        "data_regions": ["europe-west4"],
        "limits": _limits(),
    }


@pytest.fixture
def actor(django_user_model):
    return django_user_model.objects.create_user(username="model-needs-staff", is_staff=True)


def _register_pack(actor, *, scenario_id="needs-scn", digest=_DIGEST) -> RaesPackageSource:
    return RaesPackageSource.objects.create(
        scenario_id=scenario_id,
        contract_kind="raes",
        contract_profile="shifter",
        package_ref=f"packs/{scenario_id}",
        package_version="1.0.0",
        package_digest=digest,
        conformance_status="passed",
        registered_by=actor,
    )


def _author_needs(actor, *, scenario_id="needs-scn", authored_digest=_DIGEST, needs=None) -> ScenarioModelNeeds:
    row = ScenarioModelNeeds(
        scenario_id=scenario_id,
        authored_package_digest=authored_digest,
        needs=needs if needs is not None else {"participant": _need_payload()},
        updated_by=actor,
    )
    row.save()
    return row


# --- overlay validation -----------------------------------------------------


def test_save_rejects_workload_role_key_mismatch(actor):
    row = ScenarioModelNeeds(
        scenario_id="needs-scn",
        authored_package_digest=_DIGEST,
        needs={"spare": _need_payload(workload="participant")},
        updated_by=actor,
    )
    with pytest.raises(ContractError):
        row.save()


def test_save_rejects_need_digest_not_matching_authored(actor):
    row = ScenarioModelNeeds(
        scenario_id="needs-scn",
        authored_package_digest=_DIGEST,
        needs={"participant": _need_payload(digest=_OTHER)},
        updated_by=actor,
    )
    with pytest.raises(ContractError):
        row.save()


def test_save_accepts_valid_binding(actor):
    row = _author_needs(actor)
    assert row.pk is not None


# --- projection -------------------------------------------------------------


def test_projection_no_binding_yields_absent_need(actor):
    _register_pack(actor)
    projection = project_scenario_model_needs("needs-scn")
    assert projection.for_workload("participant").need is None


def test_projection_verifies_matching_digest(actor):
    _register_pack(actor, digest=_DIGEST)
    _author_needs(actor, authored_digest=_DIGEST)
    result = project_scenario_model_needs("needs-scn").for_workload("participant")
    assert isinstance(result.need, ScenarioNeed)
    assert result.digest_verified is True


def test_projection_flags_stale_digest_when_pack_reregistered(actor):
    _register_pack(actor, digest=_OTHER)  # pack re-registered with new content
    _author_needs(actor, authored_digest=_DIGEST)  # binding authored against old content
    result = project_scenario_model_needs("needs-scn").for_workload("participant")
    assert isinstance(result.need, ScenarioNeed)
    assert result.digest_verified is False


def test_projection_unknown_scenario_is_absent(actor):
    result = project_scenario_model_needs("no-such-scenario").for_workload("participant")
    assert result.need is None


def test_projection_missing_pack_source_is_unverified(actor):
    _author_needs(actor)  # overlay authored but no RaesPackageSource registered
    result = project_scenario_model_needs("needs-scn").for_workload("participant")
    assert result.need is not None
    assert result.digest_verified is False


def test_confirmed_absence_is_not_a_resolution_failure(actor):
    _register_pack(actor)  # pack registered, no overlay authored
    projection = project_scenario_model_needs("needs-scn")
    assert projection.resolution_failed is False
    assert projection.needs == {}


def test_malformed_stored_need_flags_resolution_failure(actor):
    _register_pack(actor)
    _author_needs(actor)
    # Bypass model validation to simulate a corrupted stored payload.
    ScenarioModelNeeds.objects.filter(scenario_id="needs-scn").update(needs={"participant": {"broken": True}})

    projection = project_scenario_model_needs("needs-scn")

    assert projection.resolution_failed is True
    assert projection.needs == {}


def test_expected_digest_verifies_against_the_launched_snapshot_not_the_registration(actor):
    # Overlay authored for snapshot A; the registration has since moved to B.
    _register_pack(actor, digest=_OTHER)  # current registration = B
    _author_needs(actor, authored_digest=_DIGEST)  # overlay authored for A

    # Verifying against the launched snapshot A matches the overlay...
    snapshot = project_scenario_model_needs("needs-scn", expected_digest=_DIGEST)
    assert snapshot.digest_verified is True
    # ...while an independent re-read (current registration B) would not, and
    # verifying against B explicitly also does not.
    assert project_scenario_model_needs("needs-scn").digest_verified is False
    assert project_scenario_model_needs("needs-scn", expected_digest=_OTHER).digest_verified is False


def test_read_error_flags_resolution_failure(actor, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(ScenarioModelNeeds.objects, "filter", _boom)

    projection = project_scenario_model_needs("needs-scn")

    assert projection.resolution_failed is True


def test_admin_form_rejects_malformed_needs_as_field_error(actor):
    import json

    from cms.admin import ScenarioModelNeedsForm

    # Workload-role/key mismatch: syntactically valid JSON, semantically invalid.
    form = ScenarioModelNeedsForm(
        data={
            "scenario_id": "needs-scn",
            "authored_package_digest": _DIGEST,
            "needs": json.dumps({"spare": _need_payload(workload="participant")}),
            "updated_by": actor.pk,
        }
    )
    assert not form.is_valid()


def test_admin_form_accepts_valid_needs(actor):
    import json

    from cms.admin import ScenarioModelNeedsForm

    form = ScenarioModelNeedsForm(
        data={
            "scenario_id": "needs-scn",
            "authored_package_digest": _DIGEST,
            "needs": json.dumps({"participant": _need_payload()}),
            "updated_by": actor.pk,
        }
    )
    assert form.is_valid(), form.errors
