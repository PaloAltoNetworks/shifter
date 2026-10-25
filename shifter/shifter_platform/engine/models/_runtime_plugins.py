"""Tenant-owned immutable runtime plugin installations."""

from uuid import uuid4

from django.conf import settings
from django.db import models

from shared.field_encryption import EncryptedStringField


class RuntimePluginInstallation(models.Model):
    """Executable identity is pinned; probes never grant readiness to a range."""

    class State(models.TextChoices):
        """Lifecycle states recorded by the installation controller."""

        CHECKING = "checking", "Checking compatibility"
        READY = "ready", "Ready"
        FAILED = "failed", "Installation failed"
        DISABLED = "disabled", "Disabled"
        RETIRED = "retired", "Retired"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organization_uuid = models.UUIDField(db_index=True)
    plugin_id = models.CharField(max_length=128)
    version = models.CharField(max_length=64)
    manifest = models.JSONField()
    manifest_digest = models.CharField(max_length=71)
    registry_credentials = EncryptedStringField(blank=True, default="")
    state = models.CharField(max_length=16, choices=State.choices, default=State.CHECKING, db_index=True)
    probe_id = models.UUIDField(default=uuid4, editable=False)
    probe_expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True)
    failure_code = models.CharField(max_length=32, blank=True, default="")
    installed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Enforce durable identity uniqueness and legal lifecycle states."""

        indexes = [models.Index(fields=["organization_uuid", "-created_at", "-id"], name="runtime_plugin_admin_page")]
        constraints = [
            models.UniqueConstraint(
                fields=["organization_uuid", "plugin_id", "version"],
                name="runtime_plugin_identity",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=["checking", "ready", "failed", "disabled", "retired"]),
                name="runtime_plugin_state",
            ),
        ]

    def __str__(self) -> str:
        return f"Runtime plugin {self.id} ({self.state})"


class RuntimePluginPackBinding(models.Model):
    """Tenant administration affects new ranges; existing ranges keep snapshots."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organization_uuid = models.UUIDField(db_index=True)
    pack_id = models.CharField(max_length=100)
    pack_digest = models.CharField(max_length=71)
    installation = models.ForeignKey(RuntimePluginInstallation, on_delete=models.PROTECT)
    bindings = models.JSONField()
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Enforce durable identity uniqueness and legal lifecycle states."""

        constraints = [
            models.UniqueConstraint(
                fields=["organization_uuid", "pack_id"],
                name="runtime_plugin_pack_binding",
            )
        ]

    def __str__(self) -> str:
        return f"Runtime plugin pack binding {self.id}"


class RuntimePluginRangeBinding(models.Model):
    """A write-once pin retained independently of pack and installation enablement."""

    range = models.OneToOneField("engine.Range", on_delete=models.PROTECT)
    installation = models.ForeignKey(RuntimePluginInstallation, on_delete=models.PROTECT)
    pin = models.JSONField()
    pin_digest = models.CharField(max_length=71)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Runtime plugin range binding {self.pk}"


class RuntimePluginInvocation(models.Model):
    """Controller-owned planning projection; provisioners may only read results."""

    id = models.UUIDField(primary_key=True, editable=False)
    operation_id = models.UUIDField(db_index=True)
    request_id = models.UUIDField()
    phase = models.CharField(max_length=16)
    input = models.JSONField()
    input_digest = models.CharField(max_length=71)
    result = models.JSONField(null=True)
    state = models.CharField(max_length=16, default="pending", db_index=True)
    expires_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Enforce durable identity uniqueness and legal lifecycle states."""

        db_table = "engine_runtime_plugin_invocation"
        constraints = [
            models.UniqueConstraint(fields=["operation_id", "phase"], name="runtime_plugin_operation_phase"),
            models.CheckConstraint(
                condition=models.Q(state__in=["pending", "planned", "failed"]), name="runtime_plugin_invocation_state"
            ),
        ]

    def __str__(self) -> str:
        return f"Runtime plugin invocation {self.id} ({self.state})"
