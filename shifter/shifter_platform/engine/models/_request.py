"""Request, Instantiation, Instance, and App models.

- Request: Provisioning request container (1:1 with RequestSpec)
- Instantiation: Abstract base for materialized specs
- Instance: Materialized InstanceSpec - compute resource
- App: Materialized AppSpec - application running on an Instance
"""

import uuid

from django.conf import settings
from django.db import models

from shared.enums import RequestType


class Request(models.Model):
    """Provisioning request container.

    Groups items requested together while allowing independent lifecycles.
    Maps 1:1 with RequestSpec schema.

    Engine owns its own Request record - separate from CMS's Request.
    Correlation is via request_id UUID.

    Attributes:
        request_id: UUID identifier for this request (correlation key).
        user: User who made the request.
        created_at: When the request was created.
    """

    request_id = models.UUIDField(unique=True, db_index=True)
    request_type = models.CharField(
        max_length=20,
        choices=[(t.value, t.name) for t in RequestType],
        db_index=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="engine_requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Default ordering and display names for the Request model."""

        ordering = ["-created_at"]
        verbose_name = "Request"
        verbose_name_plural = "Requests"

    def __str__(self) -> str:
        """Return a human-readable label with the request's correlation UUID."""
        return f"Request {self.request_id}"


class Instantiation(models.Model):
    """Abstract base for any materialized spec.

    Provides common fields for tracking lifecycle of specs that have been
    interpreted into concrete infrastructure or behavior.

    Attributes:
        uuid: The UUID from the spec being instantiated (instance uuid, range uuid,
            app uuid, etc). This is the correlation key for events, WebSocket
            subscriptions, and linking to Terraform/Pulumi outputs.
        request: The request that spawned this instantiation.
        spec: The hydrated spec JSON (what was asked for).
        status: Current lifecycle status.
        created_at: When this was instantiated.
        deleted_at: When removal was requested (soft delete).
        destroyed_at: When infrastructure was actually torn down.
    """

    uuid = models.UUIDField(unique=True, db_index=True, default=uuid.uuid4, help_text="UUID from the spec")
    request = models.ForeignKey(
        Request,
        on_delete=models.CASCADE,
        related_name="%(class)s_instantiations",
        null=True,
        blank=True,
    )
    spec = models.JSONField(
        null=True,
        blank=True,
        help_text="Hydrated spec JSON from CMS (what was asked for)",
    )
    state = models.JSONField(
        null=True,
        blank=True,
        help_text="Infrastructure state (resource IDs, IPs, etc.)",
    )
    status = models.CharField(max_length=20, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    destroyed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Marks Instantiation as an abstract base with no table of its own."""

        abstract = True

    @property
    def is_deleted(self) -> bool:
        """Return True if removal has been requested."""
        return self.deleted_at is not None

    @property
    def is_destroyed(self) -> bool:
        """Return True if infrastructure has been torn down."""
        return self.destroyed_at is not None


class Instance(Instantiation):
    """Materialized InstanceSpec - compute resource.

    Represents an EC2 instance, container, or other compute unit.
    Apps run on Instances (1:N relationship).

    Attributes:
        role: Instance role from InstanceSpec (attacker, victim, dc, ngfw).
        os_type: Operating system type (kali, ubuntu, windows, panos).
    """

    class Role(models.TextChoices):
        """Instance roles from InstanceSpec."""

        ATTACKER = "attacker", "Attacker"
        VICTIM = "victim", "Victim"
        DC = "dc", "Domain Controller"
        NGFW = "ngfw", "NGFW"

    class OSType(models.TextChoices):
        """Operating system types an Instance can run."""

        KALI = "kali", "Kali Linux"
        UBUNTU = "ubuntu", "Ubuntu"
        WINDOWS = "windows", "Windows"
        PANOS = "panos", "PAN-OS"

    role = models.CharField(max_length=20, choices=Role.choices, db_index=True)
    os_type = models.CharField(max_length=20, choices=OSType.choices)
    provisioner_operation = models.CharField(max_length=32, blank=True, default="")
    provisioner_operation_id = models.UUIDField(null=True, blank=True, editable=False)
    subnet = models.ForeignKey(
        "Subnet",
        on_delete=models.CASCADE,
        related_name="instances",
        null=True,
        blank=True,
        help_text="Logical subnet this instance belongs to",
    )

    class Meta:
        """Default ordering and display names for the Instance model."""

        ordering = ["-created_at"]
        verbose_name = "Instance"
        verbose_name_plural = "Instances"

    def __str__(self) -> str:
        """Return a human-readable label with uuid, role, and OS type."""
        return f"Instance {self.uuid} ({self.role}/{self.os_type})"


class App(Instantiation):
    """Materialized AppSpec - application running on compute.

    Represents an app (NGFW, Agent, OS, Other) that runs on an Instance.
    Child of Instance - mirrors the spec nesting.

    Attributes:
        app_type: App type discriminator (os, ngfw, agent, other).
        instance: Parent Instance this App runs on.
    """

    class AppType(models.TextChoices):
        """App type discriminator for what an App represents."""

        OS = "os", "OS"
        NGFW = "ngfw", "NGFW"
        AGENT = "agent", "Agent"
        OTHER = "other", "Other"

    app_type = models.CharField(max_length=20, choices=AppType.choices, db_index=True)
    instance = models.ForeignKey(
        Instance,
        on_delete=models.CASCADE,
        related_name="apps",
    )

    class Meta:
        """Default ordering and display names for the App model."""

        ordering = ["-created_at"]
        verbose_name = "App"
        verbose_name_plural = "Apps"

    def __str__(self) -> str:
        """Return a human-readable label with uuid and app type."""
        return f"App {self.uuid} ({self.app_type})"
