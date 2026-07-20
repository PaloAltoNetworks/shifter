"""CTF participant password authentication (domain-owned).

The authentication of a live CTF participant is a CTF-domain concern. This is
the single implementation; the Django ``AUTHENTICATION_BACKENDS`` entry
``config.auth.CTFParticipantBackend`` (composition) delegates here, and the CTF
login view calls it directly — so the CTF domain no longer imports the
composition-layer auth backend (ADR-001, #1523). Behavior is identical to the
former backend: it authenticates only active, temporary CTF accounts that are
live participants, never a platform (non-CTF) account.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model

from management.services import is_temporary_ctf_account

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def authenticate_ctf_participant(username: str | None, password: str | None) -> User | None:
    """Return the live CTF participant matching the credentials, else ``None``.

    Mirrors ``ModelBackend`` password verification (including the timing-attack
    mitigation for unknown usernames) and then applies the CTF gates: the account
    must be active, a temporary CTF account, and a live participant.
    """
    if username is None or password is None:
        return None

    user_model = get_user_model()
    try:
        user = user_model._default_manager.get_by_natural_key(username)
    except user_model.DoesNotExist:
        # Run the default password hasher once to keep timing uniform for
        # unknown usernames (matches django.contrib.auth.backends.ModelBackend).
        user_model().set_password(password)
        user = None
    if user is None or not user.check_password(password):
        return None

    from ctf.services.participant.accounts import live_participant_for_user

    is_live_ctf_participant = (
        user.is_active and is_temporary_ctf_account(user) and live_participant_for_user(user) is not None
    )
    return user if is_live_ctf_participant else None
