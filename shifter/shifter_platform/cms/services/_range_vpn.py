"""Product-neutral CMS authorization boundary for OpenVPN profiles."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cms.exceptions import CMSError
from shared.enums import RangeSource, ResourceStatus

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import RangeInstance
    from shared.remote_access import OpenVpnProfile

_RANGE_NOT_FOUND = "Range not found"


class OpenVpnProfileNotFound(CMSError):
    """The caller has no matching product range (non-enumerating)."""


class OpenVpnProfileConflict(CMSError):
    """The owned range is not currently eligible for profile delivery."""


class OpenVpnProfileUnavailable(CMSError):
    """The profile binding or provider material cannot currently be resolved."""


# Compatibility names retained for the CTF bridge and existing imports.
CtfOpenVpnProfileNotFound = OpenVpnProfileNotFound
CtfOpenVpnProfileConflict = OpenVpnProfileConflict
CtfOpenVpnProfileUnavailable = OpenVpnProfileUnavailable


def _load_owned_range(user: User, range_source: RangeSource, range_instance_pk: int | None = None) -> RangeInstance:
    """Load one active, caller-owned product range without crossing sources."""
    from cms.models import RangeInstance

    if getattr(user, "id", None) is None:
        raise OpenVpnProfileNotFound(_RANGE_NOT_FOUND)
    query = RangeInstance.objects.select_related("request").filter(
        user_id=user.id,
        range_source=range_source.value,
    )
    if range_instance_pk is not None:
        query = query.filter(pk=range_instance_pk)
    instance = query.first()
    if instance is None:
        raise OpenVpnProfileNotFound(_RANGE_NOT_FOUND)
    if instance.status != ResourceStatus.READY.value:
        raise OpenVpnProfileConflict("Range is not ready")
    if instance.request is None:
        raise OpenVpnProfileUnavailable("Range access is unavailable")
    return instance


def _resolve_profile(user: User, instance: RangeInstance) -> OpenVpnProfile:
    """Resolve an Engine profile while preserving the CMS error vocabulary."""
    from cms import services as cms_services
    from engine.services import VpnProfileConflict, VpnProfileNotFound, VpnProfileUnavailable

    request = instance.request
    if request is None:
        raise OpenVpnProfileUnavailable("Range access is unavailable")
    try:
        return cms_services.engine_get_openvpn_profile(user, request.request_id)
    except VpnProfileNotFound as exc:
        raise OpenVpnProfileNotFound(_RANGE_NOT_FOUND) from exc
    except VpnProfileConflict as exc:
        raise OpenVpnProfileConflict("Range VPN profile is not ready") from exc
    except VpnProfileUnavailable as exc:
        raise OpenVpnProfileUnavailable("Range VPN profile is unavailable") from exc


def _has_profile(user: User, instance: RangeInstance) -> bool:
    """Return whether Engine has a profile for the owned range generation."""
    from cms import services as cms_services

    request = instance.request
    if request is None:
        return False
    return cms_services.engine_has_openvpn_profile(user, request.request_id)


def get_ctf_openvpn_profile(user: User, range_instance_pk: int) -> OpenVpnProfile:
    """Return the profile for one caller-owned, ready CTF range."""
    return _resolve_profile(user, _load_owned_range(user, RangeSource.CTF, range_instance_pk))


def has_ctf_openvpn_profile(user: User, range_instance_pk: int) -> bool:
    """Return whether one caller-owned CTF range has a ready profile."""
    try:
        instance = _load_owned_range(user, RangeSource.CTF, range_instance_pk)
    except CMSError:
        return False
    return _has_profile(user, instance)


def get_mission_control_openvpn_profile(user: User) -> tuple[OpenVpnProfile, int]:
    """Return the active Mission Control profile and range-instance ID."""
    instance = _load_owned_range(user, RangeSource.MISSION_CONTROL)
    return _resolve_profile(user, instance), instance.pk


def has_mission_control_openvpn_profile(user: User) -> bool:
    """Return whether the caller's active Mission Control range has a profile."""
    try:
        instance = _load_owned_range(user, RangeSource.MISSION_CONTROL)
    except CMSError:
        return False
    return _has_profile(user, instance)
