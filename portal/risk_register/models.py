"""Risk Register models."""

import hashlib
import secrets
from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone


class Severity(models.TextChoices):
    """Risk severity levels."""

    CRITICAL = "critical", "Critical"
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class Status(models.TextChoices):
    """Risk lifecycle status."""

    OPEN = "open", "Open"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    MITIGATING = "mitigating", "Mitigating"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"


class StrideCategory(models.TextChoices):
    """STRIDE threat modeling categories."""

    SPOOFING = "S", "Spoofing"
    TAMPERING = "T", "Tampering"
    REPUDIATION = "R", "Repudiation"
    INFO_DISCLOSURE = "I", "Information Disclosure"
    DENIAL_OF_SERVICE = "D", "Denial of Service"
    ELEVATION = "E", "Elevation of Privilege"


class Risk(models.Model):
    """Security risk entry with threat modeling data."""

    title = models.CharField(max_length=200)
    description = models.TextField()
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    # Threat modeling fields (JSONField for SQLite compatibility)
    stride_categories = models.JSONField(
        default=list,
        blank=True,
        help_text="List of STRIDE category codes (S, T, R, I, D, E)",
    )
    likelihood_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="1-5 scale")
    impact_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="1-5 scale")
    attack_vector = models.TextField(blank=True)
    affected_assets = models.TextField(blank=True)
    mitigation_status = models.TextField(blank=True)
    resolution_reason = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "deleted_at"]),
            models.Index(fields=["severity", "deleted_at"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.severity})"

    @property
    def is_deleted(self) -> bool:
        """Return True if risk has been soft-deleted."""
        return self.deleted_at is not None

    @property
    def risk_score(self) -> int | None:
        """Compute risk score as likelihood * impact."""
        if self.likelihood_score and self.impact_score:
            return self.likelihood_score * self.impact_score
        return None

    @property
    def comment_count(self) -> int:
        """Return count of non-deleted comments."""
        return self.comments.filter(deleted_at__isnull=True).count()

    @classmethod
    def active(cls):
        """Return queryset of non-deleted risks."""
        return cls.objects.filter(deleted_at__isnull=True)

    def soft_delete(self):
        """Mark risk as deleted without removing from database."""
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def restore(self):
        """Restore a soft-deleted risk."""
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])


class Comment(models.Model):
    """Immutable comment attached to a risk."""

    risk = models.ForeignKey(Risk, on_delete=models.CASCADE, related_name="comments")
    content = models.TextField()

    # Author can be either a user or an API key
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="risk_comments",
    )
    author_apikey = models.ForeignKey(
        "APIKey",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comments",
    )

    # For edit versioning (immutable comments)
    parent_comment = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="versions",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["risk", "deleted_at", "created_at"]),
        ]

    def __str__(self):
        author = self.author_display
        return f"Comment by {author} on {self.risk.title}"

    @property
    def is_deleted(self) -> bool:
        """Return True if comment has been soft-deleted."""
        return self.deleted_at is not None

    @property
    def author_display(self) -> str:
        """Return display name for the comment author."""
        if self.author_user:
            return self.author_user.email
        if self.author_apikey:
            return f"API: {self.author_apikey.name}"
        return "Unknown"

    @property
    def author_type(self) -> str:
        """Return 'user' or 'apikey' based on author."""
        if self.author_user:
            return "user"
        return "apikey"

    @property
    def author_id(self) -> int | None:
        """Return ID of the author (user or apikey)."""
        if self.author_user:
            return self.author_user.id
        if self.author_apikey:
            return self.author_apikey.id
        return None

    def soft_delete(self):
        """Mark comment as deleted without removing from database."""
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])


class APIKey(models.Model):
    """API key for programmatic access."""

    name = models.CharField(max_length=100, help_text="Human-friendly name for this key")
    prefix = models.CharField(max_length=8, unique=True, help_text="Key prefix for identification")
    key_hash = models.CharField(max_length=64, help_text="SHA-256 hash of full key")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_api_keys",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"
        indexes = [
            models.Index(fields=["prefix"]),
            models.Index(fields=["created_by", "revoked_at"]),
        ]

    def __str__(self):
        status = "active" if self.is_active else "revoked"
        return f"{self.name} ({self.prefix}...) - {status}"

    @property
    def is_active(self) -> bool:
        """Return True if key is not revoked and not expired."""
        if self.revoked_at is not None:
            return False
        return not (self.expires_at is not None and self.expires_at < timezone.now())

    @property
    def display_key(self) -> str:
        """Return prefix with ellipsis for display."""
        return f"{self.prefix}..."

    def revoke(self):
        """Revoke this API key."""
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])

    def update_last_used(self):
        """Update last_used_at to current time."""
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])

    @classmethod
    def create_key(cls, name: str, created_by, expires_at=None) -> tuple["APIKey", str]:
        """
        Create a new API key.

        Returns:
            Tuple of (APIKey instance, raw key string).
            The raw key is only available at creation time.
        """
        # Generate random key: rr_live_<32 random chars>
        random_part = secrets.token_urlsafe(24)[:32]
        raw_key = f"rr_live_{random_part}"
        prefix = raw_key[:8]

        # Hash the full key for storage
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        api_key = cls.objects.create(
            name=name,
            prefix=prefix,
            key_hash=key_hash,
            created_by=created_by,
            expires_at=expires_at,
        )
        return api_key, raw_key

    @classmethod
    def authenticate(cls, raw_key: str) -> "APIKey | None":
        """
        Authenticate an API key.

        Returns:
            APIKey instance if valid, None otherwise.
        """
        if not raw_key or not raw_key.startswith("rr_live_"):
            return None

        prefix = raw_key[:8]
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        try:
            api_key = cls.objects.get(prefix=prefix, key_hash=key_hash)
            if api_key.is_active:
                return api_key
        except cls.DoesNotExist:
            pass

        return None


class AuditLog(models.Model):
    """Record of state changes for auditing."""

    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        RESTORE = "restore", "Restore"
        CLOSE = "close", "Close"
        REOPEN = "reopen", "Reopen"

    class EntityType(models.TextChoices):
        RISK = "risk", "Risk"
        COMMENT = "comment", "Comment"
        APIKEY = "apikey", "API Key"

    class ActorType(models.TextChoices):
        USER = "user", "User"
        APIKEY = "apikey", "API Key"

    entity_type = models.CharField(max_length=20, choices=EntityType.choices)
    entity_id = models.PositiveIntegerField()
    action = models.CharField(max_length=20, choices=Action.choices)

    actor_type = models.CharField(max_length=10, choices=ActorType.choices)
    actor_id = models.PositiveIntegerField()

    timestamp = models.DateTimeField(auto_now_add=True)
    previous_state = models.JSONField(null=True, blank=True)
    new_state = models.JSONField(null=True, blank=True)
    context = models.TextField(blank=True, help_text="Optional reason or notes")

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["actor_type", "actor_id"]),
            models.Index(fields=["timestamp"]),
        ]

    def __str__(self):
        return f"{self.action} {self.entity_type} {self.entity_id} at {self.timestamp}"

    @classmethod
    def log(
        cls,
        entity_type: str,
        entity_id: int,
        action: str,
        actor_type: str,
        actor_id: int,
        previous_state: dict[str, Any] | None = None,
        new_state: dict[str, Any] | None = None,
        context: str = "",
    ) -> "AuditLog":
        """Create an audit log entry."""
        return cls.objects.create(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_type=actor_type,
            actor_id=actor_id,
            previous_state=previous_state,
            new_state=new_state,
            context=context,
        )
