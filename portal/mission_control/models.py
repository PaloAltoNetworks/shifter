"""Mission Control models."""

from django.conf import settings
from django.db import models


class OperatingSystem(models.Model):
    """Reference table for supported operating systems."""

    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    extensions = models.JSONField(
        default=list, help_text="File extensions that map to this OS (e.g., ['.msi'])"
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Operating System"
        verbose_name_plural = "Operating Systems"

    def __str__(self):
        return self.name

    @classmethod
    def get_for_extension(cls, extension: str):
        """Find the OS that matches a given file extension."""
        ext = extension.lower() if not extension.startswith(".") else extension.lower()
        if not ext.startswith("."):
            ext = f".{ext}"
        for os in cls.objects.all():
            if ext in os.extensions:
                return os
        return None


class UserProfile(models.Model):
    """Extended user data for soft delete and anonymization."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    anonymized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"Profile for {self.user.email}"

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class AgentConfig(models.Model):
    """XDR/XSIAM agent installer uploaded by a user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agents"
    )
    os = models.ForeignKey(
        OperatingSystem, on_delete=models.PROTECT, related_name="agents"
    )
    name = models.CharField(max_length=100, help_text="User-friendly name for this agent")
    s3_key = models.CharField(max_length=500, help_text="S3 object key for the installer")
    original_filename = models.CharField(max_length=255)
    file_size_bytes = models.PositiveBigIntegerField()
    sha256_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Agent Config"
        verbose_name_plural = "Agent Configs"

    def __str__(self):
        return f"{self.name} ({self.os.name})"

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def file_size_mb(self):
        """Return file size in megabytes, rounded to 1 decimal."""
        return round(self.file_size_bytes / (1024 * 1024), 1)

    @classmethod
    def active_for_user(cls, user):
        """Return non-deleted agents for a user."""
        return cls.objects.filter(user=user, deleted_at__isnull=True)


class Range(models.Model):
    """User's cyber range instance with lifecycle management."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROVISIONING = "provisioning", "Provisioning"
        READY = "ready", "Ready"
        PAUSED = "paused", "Paused"
        RESUMING = "resuming", "Resuming"
        DESTROYING = "destroying", "Destroying"
        DESTROYED = "destroyed", "Destroyed"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ranges"
    )
    agent = models.ForeignKey(
        AgentConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ranges",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    victim_ip = models.GenericIPAddressField(null=True, blank=True)
    chat_url = models.URLField(max_length=500, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    destroyed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        agent_name = self.agent.name if self.agent else "Unknown Agent"
        return f"Range {self.id} ({agent_name}) - {self.status}"

    @property
    def is_active(self):
        """Return True if range is in an active/usable state."""
        return self.status in (self.Status.READY, self.Status.PAUSED)

    @property
    def is_terminal(self):
        """Return True if range has reached a final state."""
        return self.status in (self.Status.DESTROYED, self.Status.FAILED)

    @classmethod
    def get_active_for_user(cls, user):
        """Return the user's active range, or None."""
        return cls.objects.filter(
            user=user,
            status__in=[
                cls.Status.PENDING,
                cls.Status.PROVISIONING,
                cls.Status.READY,
                cls.Status.PAUSED,
                cls.Status.RESUMING,
            ],
        ).first()


class ActivityLog(models.Model):
    """Generic activity/event log for analytics and auditing."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    action = models.CharField(max_length=100, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Activity Log"
        verbose_name_plural = "Activity Logs"

    def __str__(self):
        user_str = self.user.email if self.user else "anonymous"
        return f"{self.action} by {user_str} at {self.timestamp}"

    @classmethod
    def log(cls, action: str, user=None, **metadata):
        """Convenience method to log an activity."""
        return cls.objects.create(user=user, action=action, metadata=metadata)
