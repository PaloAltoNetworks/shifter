"""Administrator-controlled CTF Organizer authorization (issue #1516).

Organizer authority — the ``CTF Organizer`` Django group, which gates the CTF
admin surface and participant range provisioning — must never be derivable from
self-service identity/profile data (the #937 SEC-5 invariant, tightened by
#1516). :mod:`config.user_type_sync` therefore no longer maps a self-mutable
``user_type`` claim to that group. This module is the single seam that grants
``CTF Organizer`` from an administrator-controlled source:

- verified provider group evidence — the ``cognito:groups`` claim captured by
  :mod:`config.cognito_groups` from the already-verified OIDC / Identity Platform
  payload — mapped through one settings-driven allowlist
  (``CTF_ORGANIZER_PROVIDER_GROUPS``); and
- explicit local administrator assignment (dev-login in a dev environment, or a
  superuser adding the group through the Django admin).

It is provider-neutral by design: OIDC (Cognito), GCP Identity Platform, and
dev-login all grant organizer through here, so the module is not named for a
single provider. Grants are additive and every change writes a strict
``ROLE_SYNC`` audit row (the same reviewability control as user-type sync). The
allowlist is fail-closed: empty or unset configuration grants no organizer
authority, and only ``CTF Organizer`` is ever reachable — staff/superuser stay
email-env driven via :func:`config.bootstrap_admin.apply_bootstrap_admin_flags`
and ``Threat Research`` stays local-admin managed. Provider-group capture stays
pure evidence in :mod:`config.cognito_groups`; authorization happens only here.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models.signals import m2m_changed

from config.cognito_groups import COGNITO_GROUPS_CLAIM, normalize_cognito_groups
from management.services import get_user_profile
from shared.audit import (
    AuditActorType,
    RequestAudit,
    StateChange,
    audit_role_sync,
    get_client_ip,
    get_request_id,
)
from shared.auth import CTF_ORGANIZER_GROUP

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from django.contrib.auth.models import User
    from django.http import HttpRequest

logger = logging.getLogger(__name__)

# Reentrancy guard: the organizer m2m signal (below) reconciles provenance for
# group changes made *outside* this module (e.g. the Django admin). This module's
# own helpers already set provenance and audit atomically, so they suppress the
# signal while they mutate ``user.groups`` to avoid a double audit / wrong
# intermediate provenance.
_signal_guard = threading.local()


@contextmanager
def _suppress_membership_signal() -> Iterator[None]:
    """Suppress the organizer membership signal for the current thread."""
    _signal_guard.active = True
    try:
        yield
    finally:
        _signal_guard.active = False


def _membership_signal_suppressed() -> bool:
    """Return True when this module is mid-mutation and the signal must skip."""
    return getattr(_signal_guard, "active", False)


PROVIDER_GROUPS_SETTING = "CTF_ORGANIZER_PROVIDER_GROUPS"

# Provenance recorded on ``UserProfile.organizer_grant_source`` so login-time
# provider reconciliation can revoke provider-derived authority when the
# administrator-controlled evidence disappears, while never touching an explicit
# local assignment. Kept in sync with ``UserProfile.ORGANIZER_GRANT_SOURCE_CHOICES``.
ORGANIZER_SOURCE_PROVIDER = "provider"
ORGANIZER_SOURCE_LOCAL = "local"


def provider_group_organizer_allowlist() -> frozenset[str]:
    """Return the exact provider group names that grant ``CTF Organizer``.

    Read from settings at call time (fail-closed: empty/unset grants nothing).
    Provider group names are case-sensitive, so they are compared verbatim.
    """
    configured = getattr(settings, PROVIDER_GROUPS_SETTING, [])
    return frozenset(str(name).strip() for name in configured if str(name).strip())


def _request_audit(request: HttpRequest | None) -> RequestAudit:
    """Return the request-derived audit context for an organizer-grant row."""
    if request is None:
        return RequestAudit()
    return RequestAudit(
        source_ip=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        request_id=get_request_id(request),
    )


def _grant_organizer(user: User, *, provenance: str, audit_source: str, request: HttpRequest | None) -> None:
    """Additively add ``CTF Organizer`` to ``user``, record provenance, and audit.

    No-op (and no audit row) when the user already holds the group. Records
    ``organizer_grant_source`` = ``provenance`` (provider / local) so provider
    reconciliation can later revoke provider-derived authority without touching a
    local assignment. The audit write is fail-closed (strict) inside the
    transaction, so a failed audit rolls back the membership change it describes.
    Only ``CTF Organizer`` is granted — never staff/superuser flags or any other
    group.
    """
    if user.groups.filter(name=CTF_ORGANIZER_GROUP).exists():
        return
    profile = get_user_profile(user)
    request_audit = _request_audit(request)
    with _suppress_membership_signal(), transaction.atomic():
        previous = sorted(user.groups.values_list("name", flat=True))
        group, _ = Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)
        user.groups.add(group)
        profile.organizer_grant_source = provenance
        profile.save(update_fields=["organizer_grant_source"])
        new = sorted(user.groups.values_list("name", flat=True))
        audit_role_sync(
            user_id=user.id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            change=StateChange(previous={"groups": previous}, new={"groups": new}),
            source=audit_source,
            request=request_audit,
        )
    logger.info("Granted CTF Organizer to user %s (%s)", getattr(user, "pk", None), provenance)


def _revoke_provider_organizer(user: User, *, request: HttpRequest | None) -> None:
    """Remove a *provider-derived* ``CTF Organizer`` membership and audit it.

    No-op unless ``organizer_grant_source`` is ``provider``: explicit local
    assignments and unknown-provenance memberships are preserved. Clears the
    provenance and writes a strict audit row in the same transaction.
    """
    profile = get_user_profile(user)
    if profile.organizer_grant_source != ORGANIZER_SOURCE_PROVIDER:
        return
    request_audit = _request_audit(request)
    with _suppress_membership_signal(), transaction.atomic():
        previous = sorted(user.groups.values_list("name", flat=True))
        group = Group.objects.filter(name=CTF_ORGANIZER_GROUP).first()
        if group is not None:
            user.groups.remove(group)
        profile.organizer_grant_source = ""
        profile.save(update_fields=["organizer_grant_source"])
        new = sorted(user.groups.values_list("name", flat=True))
        audit_role_sync(
            user_id=user.id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            change=StateChange(previous={"groups": previous}, new={"groups": new}),
            source="provider_group_revoked",
            request=request_audit,
        )
    logger.info("Revoked provider-derived CTF Organizer from user %s", getattr(user, "pk", None))


def reconcile_provider_privileged_groups(
    user: User,
    claims: Mapping[str, object],
    request: HttpRequest | None = None,
) -> None:
    """Reconcile ``CTF Organizer`` against verified, admin-controlled provider groups.

    The provider group is the authoritative source for provider-derived organizer
    authority, so this both grants and revokes:

    - allowlisted provider group present, not yet organizer -> grant (provenance
      ``provider``), audited;
    - allowlisted provider group absent, but a *provider-derived* organizer
      membership exists -> revoke it, audited (an administrator removed the user
      from the provider group);
    - explicit local assignments and unknown-provenance memberships are never
      revoked by this path.

    Fail-closed: when the allowlist is empty/unset the provider path is disabled
    entirely — it neither grants nor revokes, so a missing configuration can never
    strip organizer authority. Unknown provider group names are ignored.
    """
    allowlist = provider_group_organizer_allowlist()
    if not allowlist:
        return
    provider_groups = set(normalize_cognito_groups(claims.get(COGNITO_GROUPS_CLAIM)))
    if provider_groups & allowlist:
        _grant_organizer(user, provenance=ORGANIZER_SOURCE_PROVIDER, audit_source="provider_group", request=request)
    elif user.groups.filter(name=CTF_ORGANIZER_GROUP).exists():
        _revoke_provider_organizer(user, request=request)


def grant_local_organizer(user: User, *, source: str, request: HttpRequest | None = None) -> None:
    """Explicit local administrator assignment of ``CTF Organizer``.

    For administrator-controlled local paths (dev-login in a dev environment).
    Additive and audited; recorded with ``local`` provenance so provider
    reconciliation never auto-revokes it.
    """
    _grant_organizer(user, provenance=ORGANIZER_SOURCE_LOCAL, audit_source=source, request=request)


def _record_local_membership_change(user: User, *, added: bool) -> None:
    """Persist local provenance and a strict audit row for an out-of-band change."""
    current = sorted(user.groups.values_list("name", flat=True))
    if added:
        previous = sorted(set(current) - {CTF_ORGANIZER_GROUP})
        new = current
        provenance = ORGANIZER_SOURCE_LOCAL
        audit_source = "local_admin_assignment"
    else:
        previous = sorted(set(current) | {CTF_ORGANIZER_GROUP})
        new = current
        provenance = ""
        audit_source = "local_admin_removal"
    profile = get_user_profile(user)
    with transaction.atomic():
        profile.organizer_grant_source = provenance
        profile.save(update_fields=["organizer_grant_source"])
        audit_role_sync(
            user_id=user.id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            change=StateChange(previous={"groups": previous}, new={"groups": new}),
            source=audit_source,
            request=RequestAudit(),
        )


def _reconcile_membership_provenance(user: User) -> None:
    """Align ``organizer_grant_source`` with the user's actual ``CTF Organizer``
    membership after an out-of-band group change (e.g. the Django admin).

    Idempotent: a no-op when provenance already matches membership. An untracked
    add records ``local`` provenance; an untracked removal clears it. Each real
    change writes a strict ``ROLE_SYNC`` audit row so the local-assignment path
    has the same durable trail as the provider and self-service paths.
    """
    has_organizer = user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()
    source = get_user_profile(user).organizer_grant_source
    if has_organizer and not source:
        _record_local_membership_change(user, added=True)
    elif not has_organizer and source:
        _record_local_membership_change(user, added=False)


def _signal_affected_users(instance: object, reverse: bool, pk_set: set[int] | None) -> list[User]:
    """Return the users whose organizer provenance may need reconciling.

    Forward changes (``user.groups`` edited, e.g. the admin User form) carry the
    user as ``instance``; reverse changes (``group.user_set`` edited, e.g. the
    admin Group form) carry the group as ``instance`` and affected user pks in
    ``pk_set`` and are only relevant when the group is ``CTF Organizer``.
    """
    user_model = get_user_model()
    if not reverse:
        return [instance] if isinstance(instance, user_model) else []
    if getattr(instance, "name", None) != CTF_ORGANIZER_GROUP or not pk_set:
        return []
    return list(user_model.objects.filter(pk__in=pk_set))


def on_user_groups_changed(
    sender: object,
    instance: object,
    action: str,
    reverse: bool,
    pk_set: set[int] | None = None,
    **kwargs: object,
) -> None:
    """``m2m_changed`` receiver keeping organizer provenance and audit consistent
    with out-of-band ``CTF Organizer`` membership changes (issue #1516)."""
    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    if _membership_signal_suppressed():
        return
    for user in _signal_affected_users(instance, reverse, pk_set):
        _reconcile_membership_provenance(user)


def register_organizer_authority_signals() -> None:
    """Connect the organizer membership signal. Called from ``config.apps`` ready()."""
    m2m_changed.connect(
        on_user_groups_changed,
        sender=get_user_model().groups.through,
        dispatch_uid="config_organizer_authority_membership",
    )
