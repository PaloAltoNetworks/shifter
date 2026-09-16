"""Tests for the RAES participant-runtime Mission Control presentation projection (#1290).

Drives real ``RaesParticipantRuntimeRecord`` rows through
``shared.raes.presentation.build_range_participant_runtime_projection`` and
asserts: ``None`` for ranges with zero participant-runtime rows (non-RAES
ranges stay boring), only allowlisted implementation/runtime fields surface
per participant, latest-per-``participant_ref`` grouping, and access-channel
derivation as a pure function of ``InstanceContext`` instances keyed on
``os_type`` (Windows -> Guacamole RDP; Linux -> browser terminal + Guacamole
range SSH; PAN-OS -> Guacamole NGFW SSH; exactly one range-level
backend-command channel) -- mirrors ``tests/shared/raes/test_presentation.py``
for the existing #1276 ``raes_projection`` slice.
"""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from shared.models import RaesParticipantRuntimeRecord
from shared.raes.contracts import SHIFTER_BACKEND_PROFILE
from shared.raes.presentation import (
    ACCESS_CHANNEL_BACKEND_COMMAND,
    ACCESS_CHANNEL_BROWSER_TERMINAL,
    ACCESS_CHANNEL_GUACAMOLE_NGFW_SSH,
    ACCESS_CHANNEL_GUACAMOLE_RANGE_SSH,
    ACCESS_CHANNEL_GUACAMOLE_RDP,
    build_range_participant_runtime_projection,
)
from shared.schemas.raes_participant_runtime import canonical_raes_payload_digest
from shared.schemas.range import InstanceContext

pytestmark = pytest.mark.django_db

_CONTRACT_VERSION = {
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION: "participant-implementation-v1",
    RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME: "participant-runtime-v1",
}


def _record(request_id, *, participant_ref, record_kind, payload, source_timestamp=None):
    """Persist one valid sidecar row through the model's validating save()."""
    ts = source_timestamp or timezone.now()
    return RaesParticipantRuntimeRecord.objects.create(
        request_id=request_id,
        participant_ref=participant_ref,
        idempotency_key=f"{record_kind}:{participant_ref}:{ts.isoformat()}",
        contract_kind=RaesParticipantRuntimeRecord.ContractKind.RAES,
        contract_version=_CONTRACT_VERSION[record_kind],
        contract_profile=SHIFTER_BACKEND_PROFILE,
        participant_runtime_profile="shifter-provisioning",
        record_kind=record_kind,
        source_timestamp=ts,
        payload_digest=canonical_raes_payload_digest(payload),
        payload=payload,
    )


def _kali_instance(uuid: str = "instance-attacker") -> InstanceContext:
    return InstanceContext(uuid=uuid, name="Attacker", role="attacker", os_type="kali")


def _windows_instance(uuid: str = "instance-target") -> InstanceContext:
    return InstanceContext(uuid=uuid, name="Target", role="victim", os_type="windows")


def _ngfw_instance(uuid: str = "instance-ngfw") -> InstanceContext:
    return InstanceContext(uuid=uuid, name="NGFW", role="ngfw", os_type="panos")


class TestBuildRangeParticipantRuntimeProjection:
    def test_none_when_no_participant_rows(self):
        assert build_range_participant_runtime_projection(uuid4(), [_kali_instance()]) is None

    def test_none_even_with_instances_and_no_rows(self):
        """Non-RAES ranges with real instances stay boring (projection absent)."""
        assert build_range_participant_runtime_projection(uuid4(), [_kali_instance(), _windows_instance()]) is None

    def test_participant_summary_allowlisted_fields_only(self):
        request_id = uuid4()
        now = timezone.now()
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION,
            source_timestamp=now,
            payload={
                "participant_ref": "ctf-participant-1",
                "implementation_ref": "impl-1",
                "backend_name": "shifter-provisioning",
                "status": "provisioned",
                "implementation_digest": "sha256:should-not-leak",
                "capability_refs": ["cap-1"],
            },
        )
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            source_timestamp=now,
            payload={
                "participant_ref": "ctf-participant-1",
                "status": "running",
                "status_reason": "healthy",
                "runtime_ref": "runtime-1",
                "runtime_digest": "sha256:should-not-leak-either",
            },
        )

        projection = build_range_participant_runtime_projection(request_id, [])
        assert projection is not None
        [participant] = projection.participants
        assert participant.participant_ref == "ctf-participant-1"
        assert set(participant.implementation) == {"status", "backend_name", "implementation_ref", "observed_at"}
        assert participant.implementation["status"] == "provisioned"
        assert participant.implementation["backend_name"] == "shifter-provisioning"
        assert participant.implementation["implementation_ref"] == "impl-1"
        assert set(participant.runtime) == {"status", "status_reason", "runtime_ref", "observed_at"}
        assert participant.runtime["status"] == "running"
        assert participant.runtime["status_reason"] == "healthy"
        assert participant.runtime["runtime_ref"] == "runtime-1"

        encoded = json.dumps(projection.to_payload())
        assert "should-not-leak" not in encoded
        assert "cap-1" not in encoded

    def test_groups_latest_per_participant_ref(self):
        request_id = uuid4()
        now = timezone.now()
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            source_timestamp=now - timedelta(minutes=5),
            payload={"participant_ref": "ctf-participant-1", "status": "accepted"},
        )
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            source_timestamp=now,
            payload={"participant_ref": "ctf-participant-1", "status": "running"},
        )
        _record(
            request_id,
            participant_ref="ctf-participant-2",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            source_timestamp=now,
            payload={"participant_ref": "ctf-participant-2", "status": "provisioning"},
        )

        projection = build_range_participant_runtime_projection(request_id, [])
        assert projection is not None
        by_ref = {p.participant_ref: p for p in projection.participants}
        assert set(by_ref) == {"ctf-participant-1", "ctf-participant-2"}
        assert by_ref["ctf-participant-1"].runtime["status"] == "running"
        assert by_ref["ctf-participant-2"].runtime["status"] == "provisioning"

    def test_participant_with_only_implementation_record_has_null_runtime(self):
        request_id = uuid4()
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_IMPLEMENTATION,
            payload={"participant_ref": "ctf-participant-1", "implementation_ref": "impl-1"},
        )
        projection = build_range_participant_runtime_projection(request_id, [])
        assert projection is not None
        [participant] = projection.participants
        assert participant.implementation is not None
        assert participant.runtime is None

    def test_access_channels_keyed_on_os_type(self):
        """Channels are derived from os_type, not role: no RDP on Linux, no SSH/terminal on Windows."""
        request_id = uuid4()
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            payload={"participant_ref": "ctf-participant-1", "status": "running"},
        )
        instances = [_kali_instance(uuid="attacker-uuid"), _windows_instance(uuid="target-uuid")]

        projection = build_range_participant_runtime_projection(request_id, instances)
        assert projection is not None
        channels = {(c.channel, c.target_ref) for c in projection.access_channels}

        # Linux (kali): browser terminal + Guacamole range SSH, but NOT RDP.
        assert (ACCESS_CHANNEL_BROWSER_TERMINAL, "attacker-uuid") in channels
        assert (ACCESS_CHANNEL_GUACAMOLE_RANGE_SSH, "attacker-uuid") in channels
        assert (ACCESS_CHANNEL_GUACAMOLE_RDP, "attacker-uuid") not in channels

        # Windows: Guacamole RDP only, NOT browser terminal / range SSH.
        assert (ACCESS_CHANNEL_GUACAMOLE_RDP, "target-uuid") in channels
        assert (ACCESS_CHANNEL_BROWSER_TERMINAL, "target-uuid") not in channels
        assert (ACCESS_CHANNEL_GUACAMOLE_RANGE_SSH, "target-uuid") not in channels

        assert not any(c.channel == ACCESS_CHANNEL_GUACAMOLE_NGFW_SSH for c in projection.access_channels)

    def test_access_channels_for_ngfw_instance(self):
        request_id = uuid4()
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            payload={"participant_ref": "ctf-participant-1", "status": "running"},
        )
        instances = [_ngfw_instance(uuid="ngfw-uuid")]

        projection = build_range_participant_runtime_projection(request_id, instances)
        assert projection is not None
        channels = [(c.channel, c.target_ref) for c in projection.access_channels]
        assert (ACCESS_CHANNEL_GUACAMOLE_NGFW_SSH, "ngfw-uuid") in channels
        assert not any(c[0] == ACCESS_CHANNEL_BROWSER_TERMINAL for c in channels)
        assert not any(c[0] == ACCESS_CHANNEL_GUACAMOLE_RDP for c in channels)
        assert not any(c[0] == ACCESS_CHANNEL_GUACAMOLE_RANGE_SSH for c in channels)

    def test_exactly_one_backend_command_channel(self):
        request_id = uuid4()
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            payload={"participant_ref": "ctf-participant-1", "status": "running"},
        )
        instances = [_kali_instance(uuid="a"), _windows_instance(uuid="b"), _ngfw_instance(uuid="c")]

        projection = build_range_participant_runtime_projection(request_id, instances)
        assert projection is not None
        backend_commands = [c for c in projection.access_channels if c.channel == ACCESS_CHANNEL_BACKEND_COMMAND]
        assert len(backend_commands) == 1
        assert backend_commands[0].target_ref == str(request_id)

    def test_to_payload_shape(self):
        request_id = uuid4()
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            payload={"participant_ref": "ctf-participant-1", "status": "running"},
        )
        projection = build_range_participant_runtime_projection(request_id, [_kali_instance(uuid="a")])
        assert projection is not None
        payload = projection.to_payload()
        assert set(payload) == {"participants", "access_channels"}
        assert payload["participants"][0]["participant_ref"] == "ctf-participant-1"
        # Single Kali (Linux) instance -> browser terminal + range SSH, plus the
        # range-level backend command channel; no RDP (Windows-only).
        assert {c["channel"] for c in payload["access_channels"]} == {
            ACCESS_CHANNEL_BROWSER_TERMINAL,
            ACCESS_CHANNEL_GUACAMOLE_RANGE_SSH,
            ACCESS_CHANNEL_BACKEND_COMMAND,
        }
        json.dumps(payload)  # must not raise (datetimes serialized)

    def test_filters_by_contract_profile(self):
        request_id = uuid4()
        _record(
            request_id,
            participant_ref="ctf-participant-1",
            record_kind=RaesParticipantRuntimeRecord.RecordKind.PARTICIPANT_RUNTIME,
            payload={"participant_ref": "ctf-participant-1", "status": "running"},
        )
        assert build_range_participant_runtime_projection(request_id, [], contract_profile="other-profile") is None
