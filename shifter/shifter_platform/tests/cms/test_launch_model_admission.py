"""CMS launch-boundary required-model admission gate (PLAT-202, #2119).

Drives ``assert_launch_model_access`` directly: it is the single fail-closed gate
every launch family funnels through in ``_create_raes_native_range_impl``. If the
enforcement were removed, a required-model scenario would launch without a model
grant — these tests go red on that regression.
"""

from __future__ import annotations

import pytest
from django.conf import settings

from cms.models import RaesPackageSource, ScenarioModelNeeds
from cms.services import create_raes_native_range
from cms.services._model_admission import assert_launch_model_access
from shared.exceptions import CMSError
from shared.model_access import validate_catalog
from shared.model_access.digest import compute_digest

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


def _need_payload(*, digest=_DIGEST, required=True) -> dict:
    return {
        "contract_version": "model-access-scenario/v1",
        "scenario_digest": digest,
        "workload_role": "participant",
        "profile_id": "coding",
        "required": required,
        "required_capabilities": ["messages"],
        "allowed_capabilities": ["messages"],
        "allowed_strategies": ["fixed-v1"],
        "data_regions": ["europe-west4"],
        "limits": _limits(),
    }


def _catalog():
    payload = {
        "contract_version": "model-access-policy/v1",
        "deployment_id": "11111111-1111-4111-8111-111111111111",
        "enabled": True,
        "profiles": [
            {
                "profile_id": "coding",
                "capabilities": ["messages", "token-count"],
                "allowed_strategies": ["fixed-v1", "weighted-rendezvous-v1"],
                "data_regions": ["europe-west4"],
                "limits": _limits(),
            }
        ],
        "quota_pools": [
            {
                "quota_pool_id": "vertex-tokens-eu",
                "provider_adapter_id": "vertex-v1",
                "provider_quota_identity": "project:models-a/region:europe-west4/model:claude",
                "dimension": "input_tokens",
                "unit": "tokens/minute",
                "limit": 1000000,
            }
        ],
        "price_schedules": [
            {
                "price_schedule_id": "vertex-2026-09",
                "currency": "USD",
                "valid_until": "2026-10-01T00:00:00Z",
                "prices": [{"component": "input_tokens", "unit_denominator": 1000000, "price_micro_units": 3000000}],
            }
        ],
        "shards": [
            {
                "shard_id": "vertex-primary",
                "provider_adapter_id": "vertex-v1",
                "compute_target_ref": {"owner": "installation", "reference": "gcp:gce-primary"},
                "model_project_ref": {"owner": "deployment", "reference": "project:models-a"},
                "model_account_ref": {"owner": "deployment", "reference": "billing:models-a"},
                "dynamic_secret_project_ref": {"owner": "deployment", "reference": "project:secrets-a"},
                "broker_workload_identity_ref": {"owner": "deployment", "reference": "gsa:model-broker"},
                "credential_ref": {"owner": "broker", "reference": "impersonate:gsa/model-invoke"},
                "region": "europe-west4",
                "provider_model": "publishers/anthropic/models/claude-sonnet",
                "provider_model_version": "20260901",
                "protocol": "anthropic-messages/2023-06-01",
                "capabilities": ["messages", "token-count"],
                "billing_components": ["input_tokens"],
                "quota_pool_ids": ["vertex-tokens-eu"],
                "weight": 1,
                "enabled": True,
            }
        ],
        "aliases": [
            {
                "logical_alias": "coding-main",
                "profile_id": "coding",
                "strategy": "fixed-v1",
                "affinity": "per_range",
                "eligible_shard_ids": ["vertex-primary"],
                "price_schedule_id": "vertex-2026-09",
            }
        ],
        "sharing_pools": [],
        "sharing_bindings": [],
    }
    payload["digest"] = compute_digest(payload)
    return validate_catalog(payload)


@pytest.fixture
def actor(django_user_model):
    return django_user_model.objects.create_user(username="launch-model-staff", is_staff=True)


def _register(actor, *, digest=_DIGEST, scenario_id="scn"):
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


def _author(actor, *, authored=_DIGEST, needs=None, scenario_id="scn"):
    row = ScenarioModelNeeds(
        scenario_id=scenario_id,
        authored_package_digest=authored,
        needs=needs if needs is not None else {"participant": _need_payload(digest=authored)},
        updated_by=actor,
    )
    row.save()
    return row


def test_scenario_without_authored_need_passes(actor):
    _register(actor)
    assert assert_launch_model_access(user=actor, scenario_id="scn", egress_mode="status-quo") is None


def test_required_need_without_configured_catalog_refuses(actor, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ACCESS_CATALOG", None, raising=False)
    _register(actor)
    _author(actor)
    with pytest.raises(CMSError) as exc:
        assert_launch_model_access(user=actor, scenario_id="scn", egress_mode="status-quo")
    assert exc.value.details["code"] == "model-access-denied"
    assert "policy_unavailable" in exc.value.details["reason_codes"]


def test_required_need_admitted_with_matching_catalog(actor, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ACCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MODEL_ACCESS_CATALOG", _catalog(), raising=False)
    _register(actor)
    _author(actor)
    assert assert_launch_model_access(user=actor, scenario_id="scn", egress_mode="status-quo") is None


def test_zero_egress_refuses_required_external_need(actor, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ACCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MODEL_ACCESS_CATALOG", _catalog(), raising=False)
    _register(actor)
    _author(actor)
    with pytest.raises(CMSError) as exc:
        assert_launch_model_access(user=actor, scenario_id="scn", egress_mode="deny-all")
    assert "egress_incompatible" in exc.value.details["reason_codes"]


def test_stale_pack_digest_refuses_required_need(actor, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ACCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MODEL_ACCESS_CATALOG", _catalog(), raising=False)
    _register(actor, digest=_OTHER)  # pack re-registered with new content
    _author(actor, authored=_DIGEST)  # binding authored against old content
    with pytest.raises(CMSError) as exc:
        assert_launch_model_access(user=actor, scenario_id="scn", egress_mode="status-quo")
    assert "digest_mismatch" in exc.value.details["reason_codes"]


# --- wiring into the authoritative launch path ------------------------------

_DISPATCH = "cms.services._raes_range_create._dispatch_raes_package"


def test_launch_path_refuses_required_need_before_dispatch(actor, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ACCESS_CATALOG", None, raising=False)
    dispatched = {"called": False}
    monkeypatch.setattr(_DISPATCH, lambda *args, **kwargs: dispatched.__setitem__("called", True))
    _register(actor)
    _author(actor)

    with pytest.raises(CMSError):
        create_raes_native_range(actor, "scn")

    assert dispatched["called"] is False


def test_launch_path_dispatches_when_no_model_need(actor, monkeypatch):
    dispatched = {"called": False}
    monkeypatch.setattr(_DISPATCH, lambda *args, **kwargs: dispatched.__setitem__("called", True))
    _register(actor)

    create_raes_native_range(actor, "scn")

    assert dispatched["called"] is True


def test_unresolvable_needs_refuse_launch_closed(actor):
    # A corrupted stored need is a resolution failure, not a confirmed absence:
    # the gate must fail closed rather than proceed as if there were no need.
    _register(actor)
    _author(actor)
    ScenarioModelNeeds.objects.filter(scenario_id="scn").update(needs={"participant": {"broken": True}})

    with pytest.raises(CMSError) as exc:
        assert_launch_model_access(user=actor, scenario_id="scn", egress_mode="status-quo")
    assert "needs_unavailable" in exc.value.details["reason_codes"]


def test_draw_subject_is_forwarded_to_admission(actor, monkeypatch):
    from shared.model_access import OwnedReference

    captured = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return ()

    monkeypatch.setattr("engine.services.admit_range_model_access", _capture)
    _register(actor)
    _author(actor)
    draw = OwnedReference(owner="ctf", reference="draw:42")

    assert_launch_model_access(user=actor, scenario_id="scn", egress_mode="status-quo", subject=draw)

    assert captured["subject"] == draw


def test_absent_subject_falls_back_to_user_reference(actor, monkeypatch):
    from shared.model_access import OwnedReference

    captured = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return ()

    monkeypatch.setattr("engine.services.admit_range_model_access", _capture)
    _register(actor)
    _author(actor)

    assert_launch_model_access(user=actor, scenario_id="scn", egress_mode="status-quo")

    assert captured["subject"] == OwnedReference(owner="management", reference=f"user:{actor.id}")


def test_egress_change_between_admission_and_reservation_refuses(actor, monkeypatch):
    # Preliminary egress is permissive, but the reservation resolves a zero-egress
    # posture under lock — the value dispatch uses. The re-gate must catch this and
    # refuse before dispatch (F4).
    monkeypatch.setattr(settings, "MODEL_ACCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MODEL_ACCESS_CATALOG", _catalog(), raising=False)
    monkeypatch.setattr("cms.services._range_workspace.resolve_effective_egress_mode", lambda _ws: "status-quo")
    monkeypatch.setattr(
        "cms.services._range_launch_common.resolve_effective_egress_mode_locked", lambda _ws: "deny-all"
    )
    dispatched = {"called": False}
    monkeypatch.setattr(_DISPATCH, lambda *args, **kwargs: dispatched.__setitem__("called", True))
    _register(actor)
    _author(actor)

    with pytest.raises(CMSError):
        create_raes_native_range(actor, "scn")

    assert dispatched["called"] is False
