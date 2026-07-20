"""Generation-bound OpenVPN profile access at the Engine service boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from engine.secrets import SecretsError, get_openvpn_profile_secret
from shared.remote_access import (
    OpenVpnBinding,
    OpenVpnBindingError,
    OpenVpnProfile,
    parse_openvpn_binding,
    validate_openvpn_profile,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from engine.models import Range


class VpnProfileNotFound(ValueError):
    """No owned range exists for the requested correlation id."""


class VpnProfileConflict(ValueError):
    """The range exists but its current lifecycle cannot deliver a profile."""


class VpnProfileUnavailable(ValueError):
    """The provider binding or secret is unavailable or invalid."""


def _owned_range(user: User, request_id: UUID) -> Range:
    """Return the caller-owned range for this correlation id or raise."""
    from engine.models import Range

    range_obj = Range.objects.select_related("request").filter(request__request_id=request_id, user=user).first()
    if range_obj is None:
        raise VpnProfileNotFound("No owned range exists")
    return range_obj


def has_openvpn_profile(user: User, request_id: UUID) -> bool:
    """Project only safe readiness for the current owner and READY range."""
    from engine.models import Range

    range_obj = Range.objects.filter(request__request_id=request_id, user=user).first()
    if not range_obj or range_obj.status != Range.Status.READY:
        return False
    try:
        _validate_current_binding(range_obj, user, request_id)
    except (VpnProfileConflict, VpnProfileUnavailable):
        return False
    return True


def _validate_current_binding(range_obj: Range, user: User, request_id: UUID) -> OpenVpnBinding:
    """Return the binding only when it names this owner, request, and Kali."""
    from engine.models import Instance

    try:
        binding = parse_openvpn_binding(range_obj.vpn_access_binding)
    except OpenVpnBindingError as exc:
        raise VpnProfileUnavailable("VPN profile binding is unavailable") from exc
    if not binding.ready:
        raise VpnProfileConflict("VPN profile binding is not ready")
    if binding.owner_user_id != user.id:
        raise VpnProfileConflict("VPN profile binding does not belong to the current owner")
    if binding.generation != request_id:
        raise VpnProfileConflict("VPN profile binding generation is stale")
    target_exists = Instance.objects.filter(
        request=range_obj.request,
        uuid=binding.target_ref,
        role=Instance.Role.ATTACKER,
        os_type=Instance.OSType.KALI,
        status="ready",
        deleted_at__isnull=True,
        destroyed_at__isnull=True,
    ).exists()
    if not target_exists:
        raise VpnProfileConflict("VPN profile target is not a current Kali member")
    return binding


def get_openvpn_profile(user: User, request_id: UUID) -> OpenVpnProfile:
    """Resolve and validate the current participant profile entirely in memory."""
    from engine.models import Range

    range_obj = _owned_range(user, request_id)
    if range_obj.status != Range.Status.READY:
        raise VpnProfileConflict("Range is not ready for VPN profile delivery")
    binding = _validate_current_binding(range_obj, user, request_id)
    try:
        profile = get_openvpn_profile_secret(binding.secret_ref)
        return OpenVpnProfile(
            content=validate_openvpn_profile(profile, binding),
            generation=binding.generation,
            profile_version=binding.profile_version,
        )
    except (SecretsError, OpenVpnBindingError) as exc:
        raise VpnProfileUnavailable("VPN profile material is unavailable") from exc
