"""Safe personal-credential metadata; Knox alone owns secrets and verification."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.utils import timezone
from knox.auth import TokenAuthentication
from knox.models import AuthToken
from rest_framework.exceptions import AuthenticationFailed

from shared.api_tokens.scopes import KNOWN_SCOPES, validate_scopes
from shared.authorization import TargetRef
from shared.authorization.catalog import TargetType
from shared.principal_port import principal_for_user

if TYPE_CHECKING:
    from datetime import datetime

    from django.contrib.auth.models import User

# Public token discriminator, not a credential.
TOKEN_PREFIX = "shf" + "_"


class ApiToken(models.Model):
    """Immutable credential limits and retained lifecycle/audit metadata."""

    name = models.CharField(max_length=100, help_text="Human-friendly name for this token")
    token_id = models.CharField(max_length=32, unique=True, help_text="Non-secret display identity")
    # Historical values remain available to S8 mapping only. No runtime code
    # reads this column as proof or derives a replacement credential from it.
    verifier_hash = models.CharField(max_length=64, blank=True, default="")
    credential_uuid = models.UUIDField(default=uuid4, unique=True, editable=False)
    knox_token = models.OneToOneField(
        AuthToken, null=True, blank=True, on_delete=models.SET_NULL, related_name="platform_metadata"
    )
    principal_uuid = models.UUIDField(null=True, blank=True, editable=False)
    target_type = models.CharField(max_length=20, blank=True, default="", editable=False)
    target_uuid = models.UUIDField(null=True, blank=True, editable=False)
    scopes = models.JSONField(default=list, help_text="Immutable scopes from the central registry")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_api_tokens"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Retain stable metadata row IDs for existing operation/audit references."""

        db_table = "shared_api_token"
        ordering = ["-created_at"]
        verbose_name = "API Token"
        verbose_name_plural = "API Tokens"
        indexes = [
            models.Index(fields=["token_id"]),
            models.Index(fields=["created_by", "revoked_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.display_id})"

    def save(self, *args, **kwargs) -> None:
        """Metadata edits cannot widen or transfer an issued credential."""
        if self.pk:
            fields = (
                "scopes",
                "expires_at",
                "created_by_id",
                "principal_uuid",
                "credential_uuid",
                "target_type",
                "target_uuid",
            )
            previous = type(self).objects.filter(pk=self.pk).values(*fields).first()
            if previous is not None and any(previous[field] != getattr(self, field) for field in fields):
                raise ValueError("Credential limits and ownership are immutable")
        super().save(*args, **kwargs)

    @property
    def target(self) -> TargetRef | None:
        """Return the immutable issuance target; historical/internal metadata may lack one."""
        if not self.target_type and self.target_uuid is None:
            return None
        return TargetRef(cast(TargetType, self.target_type), self.target_uuid)

    @property
    def is_active(self) -> bool:
        """Legacy metadata, deleted Knox proofs, revocation and expiry all deny."""
        return bool(
            self.knox_token_id
            and self.revoked_at is None
            and self.expires_at is not None
            and self.expires_at > timezone.now()
        )

    @property
    def display_id(self) -> str:
        return f"{TOKEN_PREFIX}{self.token_id}"

    @property
    def requires_reissue(self) -> bool:
        """Historical custom proofs are retained for S8 disposition, not login."""
        return bool(self.verifier_hash) and self.knox_token_id is None and self.revoked_at is None

    @property
    def has_usable_scope(self) -> bool:
        return bool(self.scopes) and all(scope in KNOWN_SCOPES for scope in self.scopes)

    @property
    def has_eligible_owner(self) -> bool:
        owner = self.created_by
        profile = getattr(owner, "profile", None)
        return bool(
            owner is not None
            and owner.is_active
            and not getattr(profile, "deleted_at", None)
            and not getattr(profile, "is_ctf_account", False)
        )

    def revoke(self) -> None:
        """Remove the library credential while retaining stable audit metadata."""
        with transaction.atomic():
            # Admission locks the owner before the token. Match that order so
            # the deferred FK check on the token update cannot deadlock with
            # a concurrent admission holding the owner row.
            owner_id = type(self).objects.filter(pk=self.pk).values_list("created_by_id", flat=True).first()
            if owner_id is not None:
                get_user_model().objects.select_for_update().filter(pk=owner_id).first()
            locked = type(self).objects.select_for_update().get(pk=self.pk)
            if locked.revoked_at is None:
                locked.revoked_at = timezone.now()
                locked.save(update_fields=["revoked_at"])
            if locked.knox_token_id:
                AuthToken.objects.filter(pk=locked.knox_token_id).delete()
            self.revoked_at = locked.revoked_at
            self.knox_token_id = None

    def touch_last_used(self, *, coalesce_seconds: int) -> bool:
        now = timezone.now()
        if self.last_used_at is not None and (now - self.last_used_at).total_seconds() < coalesce_seconds:
            return False
        self.last_used_at = now
        self.save(update_fields=["last_used_at"])
        return True

    @classmethod
    def create_token(
        cls,
        *,
        name: str,
        created_by: User | None,
        scopes: list[str],
        expires_at: datetime | None = None,
        target: TargetRef | None = None,
    ) -> tuple[ApiToken, str]:
        """Persistence primitive; public issuance enters the authorized service."""
        granted = validate_scopes(scopes)
        if target is not None and not isinstance(target, TargetRef):
            raise ValueError("Invalid credential target")
        if created_by is None or created_by.pk is None:
            raise ValueError("A persisted personal credential owner is required")
        now = timezone.now()
        maximum = timedelta(days=settings.API_TOKEN_MAX_TTL_DAYS)
        lifetime = expires_at - now if expires_at is not None else maximum
        if lifetime > maximum:
            raise ValueError("Credential lifetime exceeds the configured maximum")
        principal = principal_for_user(created_by)
        with transaction.atomic():
            native, raw = AuthToken.objects.create(user=created_by, expiry=lifetime, prefix=TOKEN_PREFIX)
            token = cls.objects.create(
                name=name,
                token_id=uuid4().hex,
                knox_token=native,
                scopes=granted,
                principal_uuid=principal.uuid,
                target_type=target.type if target else "",
                target_uuid=target.uuid if target else None,
                created_by=created_by,
                expires_at=native.expiry,
            )
        return token, raw

    @classmethod
    def authenticate(cls, raw_token: str) -> ApiToken | None:
        """Delegate proof verification to Knox; never try a legacy verifier."""
        if not isinstance(raw_token, str) or not raw_token.startswith(TOKEN_PREFIX) or len(raw_token) > 256:
            return None
        try:
            _user, native = TokenAuthentication().authenticate_credentials(raw_token.encode())
        except (AuthenticationFailed, ValueError):
            return None
        token = cls.objects.select_related("created_by").filter(knox_token=native).first()
        return token if token is not None and token.is_active and token.has_usable_scope else None
