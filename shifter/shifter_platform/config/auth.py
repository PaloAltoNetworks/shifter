"""Platform-local authentication boundaries."""

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpRequest

from management.services import is_temporary_ctf_account


class _ProfileAwareModelBackend(ModelBackend):
    """Load the durable origin marker with the authenticated session user."""

    def get_user(self, user_id: int) -> User | None:
        user_model = get_user_model()
        try:
            user = user_model._default_manager.select_related("profile").get(pk=user_id)
        except user_model.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None


class PlatformModelBackend(_ProfileAwareModelBackend):
    """Django password backend that excludes temporary CTF identities."""

    def user_can_authenticate(self, user: User | AnonymousUser | None) -> bool:
        return user is not None and not is_temporary_ctf_account(user) and super().user_can_authenticate(user)


class CTFParticipantBackend(_ProfileAwareModelBackend):
    """Django auth backend for CTF participants.

    Registered in ``AUTHENTICATION_BACKENDS`` (composition). The participant
    authentication *logic* is CTF-domain and lives in
    ``ctf.services.authenticate_ctf_participant``; this backend delegates to it
    so the CTF domain does not import the composition layer (ADR-001, #1523).
    ``get_user`` / ``user_can_authenticate`` are retained here because Django
    reloads the session principal through the registered backend.
    """

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> User | None:
        # Only run when explicitly targeted by the CTF login path, so the generic
        # authenticate() flow never routes a platform account through here.
        if kwargs.pop("ctf_participant", False) is not True:
            return None
        from ctf.services import authenticate_ctf_participant

        return authenticate_ctf_participant(username, password)

    def user_can_authenticate(self, user: User | AnonymousUser | None) -> bool:
        return user is not None and is_temporary_ctf_account(user) and super().user_can_authenticate(user)
