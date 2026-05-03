"""Provisioning request and materialized entities.

Holds the ``Request`` aggregate and the entities a request hydrates into a
range: ``Instance``, ``App``, ``Subnet``. ``EntityBase`` is the abstract
shared base for every concrete entity. Imports from :mod:`cms.models.catalogs`
for the InstanceType / AppType FK targets; the FK from Instance/Subnet to
Request uses Django's string ref pattern so all three classes can live in
this same module without circular import gymnastics.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from django.conf import settings
from django.db import models

from cms.models.catalogs import AppType, InstanceType
from cms.models.lifecycle import apply_terminal_soft_delete
from cms.models.mixins import SoftDeleteMixin
from shared.enums import RequestType, ResourceStatus

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Abstract Entity Base
# -----------------------------------------------------------------------------


class EntityBase(SoftDeleteMixin, models.Model):
    """Abstract base for concrete entities in ranges (Instance, App).

    Entities represent materialized "things" that exist in provisioned ranges.
    Each entity has a UUID primary key for correlation across CMS, Engine,
    and events.

    The UUID is auto-generated on first save and included in specs sent to Engine.
    Status tracks lifecycle and automatically soft-deletes on terminal states
    via :func:`~cms.models.lifecycle.apply_terminal_soft_delete`.

    Attributes:
        id: UUID primary key (auto-generated).
        status: Lifecycle status (pending, provisioning, ready, etc.).
        created_at: When this entity was created.
        deleted_at: Soft delete timestamp (None = active).
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    status = models.CharField(
        max_length=20,
        default=ResourceStatus.PENDING.value,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        """Save with terminal-status soft-delete invariant enforcement."""
        apply_terminal_soft_delete(self, kwargs)
        super().save(*args, **kwargs)


# -----------------------------------------------------------------------------
# Request and its materialized entities
# -----------------------------------------------------------------------------


class Request(SoftDeleteMixin, models.Model):
    """Provisioning request container.

    Groups items requested together while allowing independent lifecycles.
    Maps 1:1 with RequestSpec schema. The :class:`~cms.models.mixins.SoftDeleteMixin`
    supplies ``is_deleted``.

    Attributes:
        request_id: UUID identifier for this request (correlation key).
        user: User who made the request.
        created_at: When the request was created.
        deleted_at: Soft delete timestamp (None = active).
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
        related_name="requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Request"
        verbose_name_plural = "Requests"

    def __str__(self):
        return f"Request {self.request_id}"


class Instance(EntityBase):
    """Instance definition - a concrete compute resource in a range.

    Stores instance config with type-specific data in a JSON field.
    Validation is delegated to Pydantic spec classes referenced by InstanceType.

    Inherits from EntityBase:
        id: UUID primary key (auto-generated, used for event correlation).
        status: Lifecycle status (pending, provisioning, ready, etc.).
        created_at: When this instance was created.
        deleted_at: Soft delete timestamp (auto-set on terminal status).

    Attributes:
        request: FK to Request (provides user context).
        name: User-friendly name for this instance.
        instance_type: FK to InstanceType catalog.
        data: Type-specific fields as JSON (validated by spec_class).
    """

    request = models.ForeignKey(
        "Request",
        on_delete=models.CASCADE,
        related_name="instances",
    )
    name = models.CharField(max_length=100, help_text="User-friendly name")
    instance_type = models.ForeignKey(
        InstanceType,
        on_delete=models.PROTECT,
        related_name="instance_configs",
    )
    data = models.JSONField(
        default=dict,
        help_text="Type-specific instance data (validated by spec_class)",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Instance"
        verbose_name_plural = "Instances"

    def __str__(self):
        return f"{self.name} ({self.id})"


class App(EntityBase):
    """App definition - a concrete application running on an instance.

    Stores app config with type-specific data in a JSON field.
    Validation is delegated to Pydantic spec classes referenced by AppType.

    Inherits from EntityBase:
        id: UUID primary key (auto-generated, used for event correlation).
        status: Lifecycle status (pending, provisioning, ready, etc.).
        created_at: When this app was created.
        deleted_at: Soft delete timestamp (auto-set on terminal status).

    Attributes:
        name: User-friendly name for this app.
        app_type: FK to AppType catalog.
        instance: Parent Instance this app runs on.
        data: Type-specific fields as JSON (validated by spec_class).
    """

    name = models.CharField(max_length=100, help_text="User-friendly name")
    app_type = models.ForeignKey(
        AppType,
        on_delete=models.PROTECT,
        related_name="apps",
    )
    instance = models.ForeignKey(
        Instance,
        on_delete=models.CASCADE,
        related_name="apps",
        null=True,
        blank=True,
        help_text="Parent instance this app runs on",
    )
    data = models.JSONField(
        default=dict,
        help_text="Type-specific app data (validated by spec_class)",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "App"
        verbose_name_plural = "Apps"

    def __str__(self):
        return f"{self.name} ({self.id})"


class Subnet(EntityBase):
    """Logical network segment in a range.

    Subnets group instances for routing policy purposes. When a range
    has an NGFW, inter-subnet traffic flows through it via connections.

    Inherits from EntityBase:
        id: UUID primary key (auto-generated, used for event correlation).
        status: Lifecycle status (pending, provisioning, ready, etc.).
        created_at: When this subnet was created.
        deleted_at: Soft delete timestamp (auto-set on terminal status).

    Attributes:
        request: FK to Request (provides user context).
        name: Subnet name (e.g., 'dc_network', 'server_network').
        data: SubnetSpec data as JSON (instances list, connected_to).
    """

    request = models.ForeignKey(
        "Request",
        on_delete=models.CASCADE,
        related_name="subnets",
    )
    name = models.CharField(max_length=100, help_text="Subnet name")
    data = models.JSONField(
        default=dict,
        help_text="SubnetSpec data (instances, connected_to)",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Subnet"
        verbose_name_plural = "Subnets"

    def __str__(self) -> str:
        return f"{self.name} ({self.id})"

    def save(self, *args, **kwargs) -> None:
        """Save with validation and logging."""
        is_new = self._state.adding
        self.validate_data()
        super().save(*args, **kwargs)

        if is_new:
            logger.info(
                "Subnet created: name=%s, id=%s, instances=%r",
                self.name,
                self.id,
                self.instances,
            )

    def validate_data(self) -> None:
        """Validate data against SubnetSpec.

        Raises:
            pydantic.ValidationError: If data is invalid.
        """
        from shared.schemas import SubnetSpec

        spec_data: dict = {"name": self.name, **self.data}
        if self.id:
            spec_data["uuid"] = str(self.id)
        SubnetSpec.model_validate(spec_data)

    @property
    def instances(self) -> list[str]:
        """Return list of instance names in this subnet."""
        return self.data.get("instances", [])

    @property
    def connected_to(self) -> list[str]:
        """Return list of subnet names this subnet connects to."""
        return self.data.get("connected_to", [])
