"""RAES operation-input materialization (ADR-043 phase 5, #1837).

Drives what ``engine.launch_intents`` materializes into ``OperationInput`` for an
``raes-range`` generation: the serialized plan, the byte-free delivery bindings,
the plan-scoped image candidates, and the normalized backend ownership the
provisioner used to read straight out of Django tables.

These tests assert the projection through its parser, so a change that widens
what crosses the boundary fails here rather than at the provisioner.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine.launch_intents import enqueue_provisioner_launch
from engine.models import (
    Instance,
    OperationInput,
    RaesArtifactSatisfactionBinding,
    RaesContentDeliveryBinding,
    RaesImageMapping,
    RaesParticipantAccessBinding,
    Range,
    Request,
)
from shared.enums import ResourceStatus
from shared.raes.operation_input import (
    MAX_ACCESS_BINDINGS,
    RaesOperationInputError,
    candidate_key,
    parse_raes_operation_input,
)

# Opaque #1325 workspace scope binding (ADR-046-R3). These suites do not
# exercise tenancy; a fixed scalar stands in for the value the CMS launch
# facade resolves in production.
_WORKSPACE_ID = 1

pytestmark = pytest.mark.django_db

_SHA = "b" * 64


def _plan() -> dict:
    return {
        "kind": "raes_provisioning_plan",
        "contract_version": "raes-provisioning-plan-v1",
        "raes_version": "2.0.0",
        "resources": {
            "net.lan": {
                "address": "net.lan",
                "resource_type": "network",
                "payload": {"name": "lan", "spec": {"infrastructure": {"properties": {"cidr": "10.9.0.0/24"}}}},
            },
            "node.web": {
                "address": "node.web",
                "resource_type": "node",
                "payload": {
                    "name": "web",
                    "os_family": "linux",
                    "spec": {"node": {"source": "kali"}, "infrastructure": {"networks": ["net.lan"]}},
                },
            },
        },
    }


class _RaesRange:
    """An RAES range ready to be launched through the real intent path."""

    def __init__(self, *, status: str = ResourceStatus.PENDING.value, range_backend: str | None = "gce"):
        self.request_id = uuid4()
        self.user = get_user_model().objects.create_user(username=f"{self.request_id}@example.com")
        self.request = Request.objects.create(request_id=self.request_id, request_type="range", user=self.user)
        self.range = Range.objects.create(
            workspace_id=_WORKSPACE_ID,
            request=self.request,
            user=self.user,
            status=status,
            range_config=_plan(),
            range_backend=range_backend,
            instantiation_purpose="training",
        )

    def bind_content(self, address: str = "content.c") -> RaesContentDeliveryBinding:
        return RaesContentDeliveryBinding.objects.create(
            range=self.range,
            content_address=address,
            sha256=_SHA,
            storage_key=f"raes/content-delivery/bb/{_SHA}",
            byte_count=11,
            binding_version=1,
        )

    def bind_access(self, channel: str = "ssh") -> RaesParticipantAccessBinding:
        return RaesParticipantAccessBinding.objects.create(
            range=self.range,
            target_address="node.web",
            channel=channel,
            account_address="acct.analyst",
            binding_version=1,
        )

    def bind_artifact(self, target: str = "node.web") -> RaesArtifactSatisfactionBinding:
        return RaesArtifactSatisfactionBinding.objects.create(
            range=self.range,
            target_address=target,
            requirement_id="req-1",
            artifact_id="img-web",
            artifact_version="1.0.0",
            digest="sha256:" + "a" * 64,
            media_type="application/vnd.raes.image",
            mechanism="exact-artifact",
            acquisition="local-lookup",
            timing="backend-preparation",
            image_ref="projects/p/global/images/web",
            machine_type="e2-medium",
            binding_version=1,
        )

    def launch(self, operation: str = "provision") -> OperationInput:
        enqueue_provisioner_launch(["raes-range", operation, "--request-id", str(self.request_id)])
        return OperationInput.objects.get(request_id=self.request_id, operation=operation)

    def payload(self, operation: str = "provision"):
        return parse_raes_operation_input(self.launch(operation).envelope["payload"])


def _mapping(source_name: str, *, version: str = "", enabled: bool = True, provider: str = "gce") -> RaesImageMapping:
    return RaesImageMapping.objects.create(
        provider=provider,
        source_name=source_name,
        source_version=version,
        image_ref=f"projects/p/global/images/{source_name}",
        machine_type="e2-medium",
        disk_size_gb=40,
        disk_type="pd-balanced",
        enabled=enabled,
    )


class TestArtifactBindings:
    """Persisted artifact-satisfaction bindings cross into the immutable input (#1580)."""

    def test_fenced_binding_round_trips_to_the_provisioner_projection(self):
        fx = _RaesRange()
        fx.bind_artifact(target="node.web")
        binding = fx.payload().artifact_binding_for("node.web")
        assert binding is not None
        assert binding.image_ref == "projects/p/global/images/web"
        assert binding.digest == "sha256:" + "a" * 64
        assert binding.mechanism == "exact-artifact"
        assert binding.machine_type == "e2-medium"

    def test_no_binding_for_an_unbound_node(self):
        fx = _RaesRange()
        assert fx.payload().artifact_binding_for("node.web") is None


class TestPlanAndIdentity:
    def test_the_serialized_plan_crosses_verbatim(self):
        fx = _RaesRange()
        assert fx.payload().plan == _plan()

    def test_the_legacy_naming_key_is_the_range_id(self):
        fx = _RaesRange()
        assert fx.payload().legacy_range_id == fx.range.id

    def test_the_input_is_keyed_by_the_canonical_generation(self):
        fx = _RaesRange()
        row = fx.launch()
        fx.range.refresh_from_db()
        assert row.operation_id == fx.range.provisioner_operation_id

    def test_destroy_materializes_its_own_generation(self):
        fx = _RaesRange(status=ResourceStatus.DESTROYING.value)
        row = fx.launch("destroy")
        assert row.operation == "destroy"
        assert parse_raes_operation_input(row.envelope["payload"]).plan == _plan()


class TestDeliveryBindings:
    def test_bindings_cross_as_byte_free_transport(self):
        fx = _RaesRange()
        fx.bind_content()
        bindings = fx.payload().delivery_bindings
        assert [b.content_address for b in bindings] == ["content.c"]
        assert bindings[0].sha256 == _SHA

    def test_no_bindings_is_an_empty_list_not_an_error(self):
        assert _RaesRange().payload().delivery_bindings == ()

    def test_another_ranges_bindings_do_not_leak(self):
        fx = _RaesRange()
        other = _RaesRange()
        other.bind_content("content.other")
        fx.bind_content("content.mine")
        assert [b.content_address for b in fx.payload().delivery_bindings] == ["content.mine"]


class TestImageCandidates:
    def test_candidates_are_projected_for_plan_referenced_sources(self):
        fx = _RaesRange()
        _mapping("kali", version="2024.1")
        candidates = fx.payload().image_candidates_for("gce", "kali")
        assert [row["image_ref"] for row in candidates] == ["projects/p/global/images/kali"]

    def test_sources_the_plan_never_names_are_not_projected(self):
        # The registry is tenant-wide; only what this plan can ask for crosses.
        fx = _RaesRange()
        _mapping("kali")
        _mapping("windows-server-2022")
        payload = fx.payload()
        assert payload.image_candidates_for("gce", "kali")
        assert payload.image_candidates_for("gce", "windows-server-2022") == []

    def test_disabled_mappings_are_not_projected(self):
        # A retired mapping must make realization fail loud, exactly as the
        # direct SELECT ... WHERE enabled = TRUE did.
        fx = _RaesRange()
        _mapping("kali", enabled=False)
        assert fx.payload().image_candidates_for("gce", "kali") == []

    def test_registry_management_metadata_does_not_cross(self):
        fx = _RaesRange()
        _mapping("kali")
        candidate = fx.payload().image_candidates_for("gce", "kali")[0]
        assert set(candidate) == {"source_version", "image_ref", "machine_type", "disk_size_gb", "disk_type"}

    def test_candidate_keys_are_provider_scoped(self):
        fx = _RaesRange()
        _mapping("kali", provider="aws")
        payload = fx.payload()
        assert payload.image_candidates_for("gce", "kali") == []
        assert payload.image_candidates_for("aws", "kali")
        assert candidate_key("aws", "kali") == "aws:kali"


class TestBackendOwnership:
    def test_a_persisted_binding_crosses_normalized(self):
        assert _RaesRange(range_backend="gce").payload().range_backend == "gce"

    def test_an_unbound_legacy_range_resolves_from_instance_evidence(self):
        # Pre-#1666 ranges carry no binding. The Engine owns engine_instance, so
        # it resolves the backend from durable asset evidence and ships only the
        # normalized outcome.
        fx = _RaesRange(status=ResourceStatus.DESTROYING.value, range_backend=None)
        Instance.objects.create(request=fx.request, role=Instance.Role.VICTIM, state={"asset_type": "gce_vm"})
        assert fx.payload("destroy").range_backend == "gce"

    def test_ambiguous_evidence_never_becomes_a_guessed_backend(self):
        fx = _RaesRange(status=ResourceStatus.DESTROYING.value, range_backend=None)
        Instance.objects.create(request=fx.request, role=Instance.Role.VICTIM, state={"asset_type": "gce_vm"})
        Instance.objects.create(request=fx.request, role=Instance.Role.VICTIM, state={"asset_type": "scenario_pod"})
        assert fx.payload("destroy").range_backend is None

    def test_evidence_free_range_carries_no_backend(self):
        fx = _RaesRange(status=ResourceStatus.DESTROYING.value, range_backend=None)
        assert fx.payload("destroy").range_backend is None

    def test_raw_instance_state_never_crosses_the_boundary(self):
        fx = _RaesRange(status=ResourceStatus.DESTROYING.value, range_backend=None)
        Instance.objects.create(
            request=fx.request,
            role=Instance.Role.VICTIM,
            state={"asset_type": "gce_vm", "internal_ip": "10.0.0.4", "gce_instance_name": "secret-name"},
        )
        serialized = str(fx.launch("destroy").envelope)
        assert "internal_ip" not in serialized
        assert "secret-name" not in serialized


class TestParticipantAccessProjection:
    """The #1710 sidecar crosses the boundary through this one immutable row."""

    def test_a_range_without_declared_access_projects_none(self):
        assert _RaesRange().payload().access_bindings == ()

    def test_declared_access_is_projected_for_the_provisioner(self):
        fixture = _RaesRange()
        fixture.bind_access()
        (binding,) = fixture.payload().access_bindings
        assert (binding.target_address, binding.channel, binding.account_address) == (
            "node.web",
            "ssh",
            "acct.analyst",
        )

    def test_the_transport_carries_identity_only(self):
        """No address, port, login, or credential reference may ride along."""
        fixture = _RaesRange()
        fixture.bind_access()
        (row,) = fixture.payload().access_binding_transport()
        assert set(row) == {"target_address", "channel", "account_address", "binding_version"}

    def test_every_declared_channel_is_projected(self):
        fixture = _RaesRange()
        fixture.bind_access("ssh")
        fixture.bind_access("rdp")
        channels = {binding.channel for binding in fixture.payload().access_bindings}
        assert channels == {"ssh", "rdp"}


class TestParticipantAccessParserFailsClosed:
    def test_a_smuggled_credential_field_is_rejected(self):
        fixture = _RaesRange()
        fixture.bind_access()
        payload = fixture.launch().envelope["payload"]
        payload["access_bindings"][0]["credential_ref"] = "projects/p/secrets/s"
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(payload)

    def test_an_unsupported_channel_is_rejected(self):
        fixture = _RaesRange()
        fixture.bind_access()
        payload = fixture.launch().envelope["payload"]
        payload["access_bindings"][0]["channel"] = "vnc"
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(payload)

    def test_a_duplicate_endpoint_is_rejected(self):
        fixture = _RaesRange()
        fixture.bind_access()
        payload = fixture.launch().envelope["payload"]
        payload["access_bindings"].append(dict(payload["access_bindings"][0]))
        with pytest.raises(RaesOperationInputError, match="duplicates"):
            parse_raes_operation_input(payload)

    def test_an_unbounded_binding_set_is_rejected(self):
        fixture = _RaesRange()
        fixture.bind_access()
        payload = fixture.launch().envelope["payload"]
        row = payload["access_bindings"][0]
        payload["access_bindings"] = [
            {**row, "target_address": f"node.n{index}"} for index in range(MAX_ACCESS_BINDINGS + 1)
        ]
        with pytest.raises(RaesOperationInputError, match="more than"):
            parse_raes_operation_input(payload)

    def test_a_missing_access_bindings_key_is_rejected(self):
        """The projection is exact-key: a dropped field is a contract break."""
        fixture = _RaesRange()
        payload = fixture.launch().envelope["payload"]
        del payload["access_bindings"]
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(payload)
