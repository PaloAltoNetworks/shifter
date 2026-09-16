"""Tests for the CMS warm-pool claim path (#28).

The atomic claim + one-winner concurrency is proven at the Engine layer
(``tests/engine/services/test_warm_pool_claim.py``). These tests pin the CMS
claim path:

- the *decision* gates that cold-fall-back without touching the ledger (disabled
  policy, an unsupported backend, or no bucket serving the backend+scenario);
- the hit path -- an atomic claim commits, the range is rehomed to the claimant,
  activation is enqueued, and the claimed request_id is returned; and
- the fail-closed rollbacks -- a genuine miss and an inconsistent ledger row
  (no CMS range instance) both cold-fall-back and enqueue nothing.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from cms.services._warm_pool_claim import WarmClaimRequest, attempt_warm_claim
from shared.enums import RangeSource
from shared.range_instantiation_policy import InstantiationPurpose
from shared.warm_pool.policy import load_policy_json

_DISABLED = load_policy_json("")
_ENABLED_GCE = load_policy_json(
    '{"enabled": true, "buckets": [{"id": "gce-polaris", "backend": "gce", "scenario": "polaris",'
    ' "capacity_partition": "default", "target": 1, "minimum": 0, "maximum": 2, "idle_ttl_seconds": 3600}]}'
)


def _request(backend: str, scenario: str, *, user=None) -> WarmClaimRequest:
    return WarmClaimRequest(
        user=user,
        scenario=scenario,
        package_digest="sha256:aaa",
        lock_digest="sha256:bbb",
        backend=backend,
        instantiation_purpose=InstantiationPurpose.LIVE_FIRE,
        range_source=RangeSource.MISSION_CONTROL,
        workspace_id=1,
        egress_mode="status-quo",
        request_id=uuid4(),
    )


class TestDecisionGates:
    def test_disabled_policy_cold_falls_back(self, monkeypatch):
        from django.conf import settings

        monkeypatch.setattr(settings, "WARM_POOL_POLICY", _DISABLED, raising=False)
        assert attempt_warm_claim(_request("gce", "polaris")) is None

    def test_unsupported_backend_cold_falls_back(self, monkeypatch):
        from django.conf import settings

        # A bucket may target gdc, but gdc has no warm-activation adapter.
        policy = load_policy_json(
            '{"enabled": true, "buckets": [{"id": "gdc-x", "backend": "gdc", "scenario": "polaris",'
            ' "capacity_partition": "default", "target": 1, "minimum": 0, "maximum": 2, "idle_ttl_seconds": 3600}]}'
        )
        monkeypatch.setattr(settings, "WARM_POOL_POLICY", policy, raising=False)
        assert attempt_warm_claim(_request("gdc", "polaris")) is None

    def test_no_matching_bucket_cold_falls_back(self, monkeypatch):
        from django.conf import settings

        monkeypatch.setattr(settings, "WARM_POOL_POLICY", _ENABLED_GCE, raising=False)
        # Enabled + gce supported, but no bucket serves this scenario.
        assert attempt_warm_claim(_request("gce", "some-other-scenario")) is None


@pytest.mark.django_db
class TestClaimOrchestration:
    """Exercise the claim path with the ledger/rehome/dispatch seams patched.

    The atomic claim and rehome are proven directly elsewhere; here we pin how the
    claim path composes them: a hit commits and enqueues activation, a miss and an
    inconsistent ledger row both cold-fall-back and enqueue nothing.
    """

    @pytest.fixture(autouse=True)
    def _isolate_seams(self, monkeypatch):
        from django.conf import settings

        monkeypatch.setattr(settings, "WARM_POOL_POLICY", _ENABLED_GCE, raising=False)
        # The isolation class is resolved through the workspaces seam elsewhere;
        # pin it so the digest is stable without provisioning a personal workspace.
        monkeypatch.setattr("cms.services._warm_pool_claim.warm_isolation_class", lambda user, ws: "personal")
        self.enqueued: list = []
        self.outcomes: list = []
        monkeypatch.setattr(
            "engine.services.enqueue_range_activation",
            lambda request_id: self.enqueued.append(request_id) or "intent-1",
        )
        monkeypatch.setattr(
            "shared.warm_pool.metrics.emit_claim_outcome",
            lambda **kwargs: self.outcomes.append(kwargs) or True,
        )

    def _patch_claim(self, monkeypatch, generation):
        monkeypatch.setattr(
            "engine.services.claim_ready_generation",
            lambda **kwargs: generation,
        )

    def _unleased_system_range(self, user):
        from cms.models import RangeInstance, Request
        from shared.enums import ResourceStatus

        request = Request.objects.create(workspace_id=1, request_id=uuid4(), request_type="raes-range", user=user)
        return RangeInstance.objects.create(
            workspace_id=1,
            request=request,
            scenario_id="polaris",
            user_id=user.id,
            range_source=RangeSource.MISSION_CONTROL.value,
            status=ResourceStatus.PROVISIONING.value,
        )

    def test_hit_rehomes_enqueues_and_first_assigns_the_user_lease(self, monkeypatch):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group

        from cms.models import MissionControlGroupLeasePolicy

        user = get_user_model().objects.create_user(username="warm-claimant@example.com")
        group = Group.objects.create(name="Warm Claim Policy")
        user.groups.add(group)
        MissionControlGroupLeasePolicy.objects.create(
            group=group,
            initial_days=7,
            extension_days=3,
            maximum_days=90,
            extensions_enabled=True,
        )
        system_row = self._unleased_system_range(user)
        assert system_row.maximum_expires_at is None  # warm-prepared rows are unleased
        claimed_request_id = uuid4()
        generation = SimpleNamespace(request_id=claimed_request_id, uuid=uuid4(), bucket_id="gce-polaris")
        self._patch_claim(monkeypatch, generation)
        monkeypatch.setattr(
            "cms.services._warm_pool_claim._system_range_instance_for",
            lambda request_id: system_row,
        )
        rehomed: list = []
        monkeypatch.setattr(
            "cms.services._range_reassign.reassign_range_owner",
            lambda pk, new_user, *, rehome=False: rehomed.append((pk, new_user, rehome)),
        )

        result = attempt_warm_claim(_request("gce", "polaris", user=user))

        assert result == claimed_request_id
        assert rehomed == [(system_row.pk, user, True)]
        assert self.enqueued == [claimed_request_id]
        assert self.outcomes[-1]["outcome"] == "hit"
        # The warm hit now carries automatic-expiry bounds and the generation increment.
        system_row.refresh_from_db()
        assert system_row.extension_days == 3
        assert system_row.lease_initial_days == 7
        assert system_row.lease_maximum_days == 90
        assert system_row.lease_policy_source == "group"
        assert system_row.lease_policy_group_revisions == [{"group_id": group.pk, "revision": 1}]
        assert (system_row.maximum_expires_at - system_row.expires_at).days == 90 - 7

    def test_hit_does_not_reset_an_already_leased_generation(self, monkeypatch):
        from datetime import timedelta

        from django.contrib.auth import get_user_model
        from django.utils import timezone

        user = get_user_model().objects.create_user(username="warm-preleased@example.com")
        system_row = self._unleased_system_range(user)
        # Simulate a row that already carries a lease (e.g. a handover that is not an
        # unleased warm row); rehoming must not reset its ceiling.
        existing_expires = timezone.now() + timedelta(days=2)
        existing_maximum = timezone.now() + timedelta(days=2)
        system_row.expires_at = existing_expires
        system_row.maximum_expires_at = existing_maximum
        system_row.extension_days = 0
        system_row.save(update_fields=["expires_at", "maximum_expires_at", "extension_days"])
        generation = SimpleNamespace(request_id=uuid4(), uuid=uuid4(), bucket_id="gce-polaris")
        self._patch_claim(monkeypatch, generation)
        monkeypatch.setattr(
            "cms.services._warm_pool_claim._system_range_instance_for",
            lambda request_id: system_row,
        )
        monkeypatch.setattr(
            "cms.services._range_reassign.reassign_range_owner",
            lambda pk, new_user, *, rehome=False: None,
        )

        attempt_warm_claim(_request("gce", "polaris", user=user))

        system_row.refresh_from_db()
        assert system_row.expires_at == existing_expires
        assert system_row.maximum_expires_at == existing_maximum
        assert system_row.extension_days == 0

    def test_miss_cold_falls_back(self, monkeypatch):
        self._patch_claim(monkeypatch, None)
        result = attempt_warm_claim(_request("gce", "polaris", user=SimpleNamespace(id=1)))
        assert result is None
        assert self.enqueued == []
        assert self.outcomes
        assert self.outcomes[-1]["outcome"] == "fallback"

    def test_inconsistent_ledger_row_rolls_back(self, monkeypatch):
        generation = SimpleNamespace(request_id=uuid4(), uuid=uuid4(), bucket_id="gce-polaris")
        self._patch_claim(monkeypatch, generation)
        # A claimed generation with no CMS range instance is inconsistent: roll back.
        monkeypatch.setattr(
            "cms.services._warm_pool_claim._system_range_instance_for",
            lambda request_id: None,
        )
        result = attempt_warm_claim(_request("gce", "polaris", user=SimpleNamespace(id=1)))
        assert result is None
        assert self.enqueued == []


@pytest.mark.django_db
class TestHelpers:
    def test_warm_isolation_class_personal_vs_shared(self):
        from django.contrib.auth import get_user_model

        from cms.services._warm_pool_claim import ISOLATION_PERSONAL, ISOLATION_SHARED, warm_isolation_class
        from workspaces.services import resolve_personal_workspace

        user = get_user_model().objects.create_user(username="claimant@example.com")
        personal = resolve_personal_workspace(user)
        assert warm_isolation_class(user, personal.workspace_id) == ISOLATION_PERSONAL
        assert warm_isolation_class(user, personal.workspace_id + 9999) == ISOLATION_SHARED

    def test_system_range_instance_for_finds_and_misses(self):
        from django.contrib.auth import get_user_model

        from cms.models import RangeInstance, Request
        from cms.services._warm_pool_claim import _system_range_instance_for
        from shared.enums import RangeSource, ResourceStatus

        user = get_user_model().objects.create_user(username="sys@warm-pool.invalid")
        request = Request.objects.create(workspace_id=1, request_id=uuid4(), request_type="raes-range", user=user)
        ri = RangeInstance.objects.create(
            workspace_id=1,
            request=request,
            scenario_id="polaris",
            user_id=user.id,
            range_source=RangeSource.MISSION_CONTROL.value,
            status=ResourceStatus.PROVISIONING.value,
        )
        assert _system_range_instance_for(request.request_id).pk == ri.pk
        assert _system_range_instance_for(uuid4()) is None
