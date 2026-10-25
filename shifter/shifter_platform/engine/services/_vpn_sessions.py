"""Connect-time authorization and session leases for the shared OpenVPN pool (#2480).

Each pool server runs a controller that asks this service before it admits a
client whose certificate OpenVPN has already verified. A grant names the one
target address and ports that client may reach. The controller renews its live
sessions with a heartbeat and disconnects every session this service returns.

PostgreSQL arbitrates the claim: one active session per range, and a newer
connection supersedes the older one. Access is re-validated on every renewal,
so destroy, ownership change, the access deadline, or a newer session ends a
live tunnel within one heartbeat interval.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, audit_log
from shared.remote_access import (
    OpenVpnBindingError,
    is_raes_member_target,
    parse_openvpn_binding,
    parse_openvpn_capability,
)

if TYPE_CHECKING:
    from engine.models import Range, VpnSession

VPN_SESSION_HEARTBEAT_SECONDS = 15
VPN_SESSION_LEASE_SECONDS = 60
MAX_HEARTBEAT_SESSIONS = 1000

_COMMON_NAME = re.compile(r"participant-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.ASCII)
_SERVER_NAME = re.compile(r"[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?", re.ASCII)
_CHANNEL_PORTS = {"ssh": 22, "rdp": 3389}
# Closed refusal codes the pool controller relays to OpenVPN.
_INVALID_REQUEST = "vpn.invalid_request"
_UNKNOWN_CLIENT = "vpn.unknown_client"
_ACCESS_REVOKED = "vpn.access_revoked"
_MAX_CLIENT_ID = 2**63 - 1
_EXPIRY_BATCH = 200


class VpnSessionDenied(ValueError):
    """The connection or request is refused with one closed reason code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class VpnSessionGrant:
    """The single destination one authorized client may reach."""

    session_id: UUID
    target_ip: str
    ports: tuple[int, ...]


def _require_server(server: object) -> str:
    """Accept only a Compute Engine instance name for the reporting server."""
    if not isinstance(server, str) or not _SERVER_NAME.fullmatch(server):
        raise VpnSessionDenied(_INVALID_REQUEST)
    return server


def _require_generation(common_name: object) -> UUID:
    """Return the binding generation a participant certificate was minted for."""
    match = _COMMON_NAME.fullmatch(common_name) if isinstance(common_name, str) else None
    if match is None:
        raise VpnSessionDenied(_UNKNOWN_CLIENT)
    return UUID(match.group(1))


def _require_client_id(client_id: object) -> int:
    """Accept only the non-negative OpenVPN client id of the server."""
    if isinstance(client_id, bool) or not isinstance(client_id, int) or not 0 <= client_id <= _MAX_CLIENT_ID:
        raise VpnSessionDenied(_INVALID_REQUEST)
    return client_id


def _client_address(value: object) -> str:
    """Keep only a well-formed client address for the audit record."""
    try:
        return str(ipaddress.ip_address(str(value)))
    except ValueError:
        return ""


def _current_target(range_obj: Range, generation: UUID) -> tuple[str, tuple[int, ...]]:
    """Return the target and ports while this generation's access is still valid."""
    from engine.models import Range

    request = range_obj.request
    if range_obj.status != Range.Status.READY or request is None or request.request_id != generation:
        raise VpnSessionDenied(_ACCESS_REVOKED)
    try:
        binding = parse_openvpn_binding(range_obj.vpn_access_binding)
        capability = parse_openvpn_capability(range_obj.remote_access_capability)
    except OpenVpnBindingError as exc:
        raise VpnSessionDenied(_ACCESS_REVOKED) from exc
    valid = (
        binding.ready
        and binding.generation == generation
        and binding.owner_user_id == range_obj.user_id
        and capability.target_ref == binding.target_ref
        and capability.teardown_at > timezone.now()
        and is_raes_member_target(binding.target_ref)
    )
    if not valid:
        raise VpnSessionDenied(_ACCESS_REVOKED)
    return _member_destination(range_obj, binding.target_ref)


def _realized_member(range_obj: Range, target_ref: str) -> dict[str, object]:
    """Return the one realized RAES member named ``target_ref``."""
    members = range_obj.provisioned_instances if isinstance(range_obj.provisioned_instances, list) else []
    matches = [
        member
        for member in members
        if isinstance(member, dict) and member.get("uuid") == target_ref and member.get("role") == "raes-node"
    ]
    if len(matches) != 1:
        raise VpnSessionDenied(_ACCESS_REVOKED)
    return matches[0]


def _channel_ports(channels: object) -> tuple[int, ...]:
    """Return the sorted ports of the declared participant channels."""
    if not isinstance(channels, list):
        return ()
    return tuple(sorted({_CHANNEL_PORTS[channel] for channel in channels if channel in _CHANNEL_PORTS}))


def _member_destination(range_obj: Range, target_ref: str) -> tuple[str, tuple[int, ...]]:
    """Resolve the realized participant target to one private address and its declared ports."""
    member = _realized_member(range_obj, target_ref)
    ports = _channel_ports(member.get("participant_access_channels"))
    try:
        address = ipaddress.ip_address(str(member.get("private_ip", "")))
    except ValueError as exc:
        raise VpnSessionDenied(_ACCESS_REVOKED) from exc
    if not ports or address.version != 4 or not address.is_private:
        raise VpnSessionDenied(_ACCESS_REVOKED)
    return str(address), ports


def _audit(session: VpnSession, action: str, state: dict[str, str]) -> None:
    """Record one pool session event without credential or certificate material."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=session.range_id,
            action=action,
            actor_type=AuditActorType.SYSTEM,
            new_state={"channel": "openvpn", "session": str(session.id), "server": session.server, **state},
            context="range_vpn_session",
        )
    )


def _end(session: VpnSession, reason: str) -> None:
    """End one active session and audit why."""
    from engine.models import VpnSessionState

    session.state = VpnSessionState.ENDED
    session.end_reason = reason
    session.ended_at = timezone.now()
    session.save(update_fields=["state", "end_reason", "ended_at"])
    _audit(session, AuditAction.DISCONNECT, {"reason": reason})


def authorize_vpn_session(
    *, common_name: object, server: object, client_id: object, client_address: object = ""
) -> VpnSessionGrant:
    """Admit one verified certificate to its own target, superseding any older session."""
    from engine.models import Range, VpnSession, VpnSessionEndReason, VpnSessionState

    server_name = _require_server(server)
    cid = _require_client_id(client_id)
    generation = _require_generation(common_name)
    with transaction.atomic():
        range_obj = (
            Range.objects.select_for_update(of=("self",))
            .select_related("request")
            .filter(request__request_id=generation)
            .first()
        )
        if range_obj is None:
            raise VpnSessionDenied(_UNKNOWN_CLIENT)
        target_ip, ports = _current_target(range_obj, generation)
        for previous in VpnSession.objects.select_for_update().filter(range=range_obj, state=VpnSessionState.ACTIVE):
            _end(previous, VpnSessionEndReason.SUPERSEDED)
        session = VpnSession.objects.create(
            range=range_obj,
            generation=generation,
            server=server_name,
            client_id=cid,
            lease_expires_at=timezone.now() + timedelta(seconds=VPN_SESSION_LEASE_SECONDS),
        )
        _audit(session, AuditAction.CONNECT, {"client_address": _client_address(client_address)})
    return VpnSessionGrant(session_id=session.id, target_ip=target_ip, ports=ports)


def _require_session_ids(session_ids: object) -> set[UUID]:
    """Accept a bounded list of session identifiers from one heartbeat."""
    if not isinstance(session_ids, list) or len(session_ids) > MAX_HEARTBEAT_SESSIONS:
        raise VpnSessionDenied(_INVALID_REQUEST)
    try:
        return {UUID(str(value)) for value in session_ids}
    except ValueError as exc:
        raise VpnSessionDenied(_INVALID_REQUEST) from exc


def _renewed(row: VpnSession, server_name: str, lease: datetime) -> bool:
    """Extend one reported session's lease, or end it when access is no longer valid."""
    from engine.models import VpnSessionEndReason, VpnSessionState

    if row.state != VpnSessionState.ACTIVE or row.server != server_name:
        return False
    try:
        _current_target(row.range, row.generation)
    except VpnSessionDenied:
        _end(row, VpnSessionEndReason.REVOKED)
        return False
    row.lease_expires_at = lease
    row.save(update_fields=["lease_expires_at"])
    return True


def _expire_lapsed() -> None:
    """End a bounded batch of sessions whose server stopped renewing them, for example after a crash."""
    from engine.models import VpnSession, VpnSessionEndReason, VpnSessionState

    lapsed = VpnSession.objects.select_for_update(skip_locked=True).filter(
        state=VpnSessionState.ACTIVE, lease_expires_at__lt=timezone.now()
    )
    for row in lapsed[:_EXPIRY_BATCH]:
        _end(row, VpnSessionEndReason.LEASE_EXPIRED)


def renew_vpn_sessions(*, server: object, session_ids: object) -> tuple[UUID, ...]:
    """Renew still-valid sessions this server holds and return the ones it must disconnect."""
    from engine.models import VpnSession, VpnSessionEndReason, VpnSessionState

    server_name = _require_server(server)
    reported = _require_session_ids(session_ids)
    lease = timezone.now() + timedelta(seconds=VPN_SESSION_LEASE_SECONDS)
    with transaction.atomic():
        rows = {
            row.id: row
            for row in VpnSession.objects.select_for_update(of=("self",))
            .select_related("range__request")
            .filter(id__in=reported)
        }
        kill = {session_id for session_id in reported if session_id not in rows}
        kill.update(session_id for session_id, row in rows.items() if not _renewed(row, server_name, lease))
        # A session the server no longer reports has left that server.
        for row in (
            VpnSession.objects.select_for_update()
            .filter(server=server_name, state=VpnSessionState.ACTIVE)
            .exclude(id__in=reported)
        ):
            _end(row, VpnSessionEndReason.DISCONNECTED)
        _expire_lapsed()
    return tuple(sorted(kill))


def end_vpn_session(*, server: object, session_id: object) -> None:
    """Record that a server's client disconnected; other servers' sessions are untouched."""
    from engine.models import VpnSession, VpnSessionEndReason, VpnSessionState

    server_name = _require_server(server)
    try:
        identifier = UUID(str(session_id))
    except ValueError as exc:
        raise VpnSessionDenied(_INVALID_REQUEST) from exc
    with transaction.atomic():
        row = (
            VpnSession.objects.select_for_update()
            .filter(id=identifier, server=server_name, state=VpnSessionState.ACTIVE)
            .first()
        )
        if row is not None:
            _end(row, VpnSessionEndReason.DISCONNECTED)
