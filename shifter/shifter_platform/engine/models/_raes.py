"""RAES backend models: image mapping (ADR-032-R2) + content-delivery binding (#1564)."""

from django.db import models

#: Swappable-safe string reference to the Range model, shared by every RAES
#: sidecar binding FK so the literal is defined once (Sonar python:S1192).
_RANGE_MODEL = "engine.Range"


class RaesImageMapping(models.Model):
    """Tenant-managed mapping from an authored RAES image identity to a concrete provider image.

    The ADR-032-R2 realization seam. An RAES scenario names an image via its
    ``source`` (name + optional version); a tenant operator maps that authored
    identity to a concrete provider image (and optional sizing defaults) here, on
    the running tenant. This is deliberately data, not code/config: new images are
    added to a deployed tenant at runtime and survive redeploys (the deployment
    model is updatable tenants, not repo-based config). The provisioner resolves
    against these rows at realization; the platform only manages them.

    A blank ``source_version`` is the any-version fallback for a ``source_name``.
    Retire a mapping with ``enabled=False`` -- which preserves audit history and
    makes realization fail loud -- rather than deleting it.
    """

    class Provider(models.TextChoices):
        """Cloud provider a mapping targets (RAES-scoped; extensible)."""

        GCE = "gce", "Google Compute Engine"
        AWS = "aws", "AWS EC2"

    provider = models.CharField(max_length=16, choices=Provider.choices)
    source_name = models.CharField(max_length=200, help_text="Authored RAES image source name (for example 'kali').")
    source_version = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Authored source version; blank matches any version for this source_name.",
    )
    image_ref = models.CharField(
        max_length=500,
        help_text="Concrete provider image (GCE source_image / family URL, AWS AMI id, ...).",
    )
    # Portable RAES artifact identity + admission evidence (#1580, ADR-034-R2/R8).
    # A GCE image has no intrinsic sha256, so an operator binds a mapping to the
    # portable ArtifactIdentity here and attests the integrity/provenance evidence
    # that admits it; registration (CMS-authoring-gated) is the owning admission
    # gate for backend-owned inventory. Blank leaves a legacy alias-only mapping
    # that resolves by source_name/version but never satisfies a portable
    # artifact requirement (fail-closed): a portable mapping requires a non-blank
    # artifact_digest AND both evidence refs (enforced by CheckConstraint).
    artifact_id = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="Portable RAES ArtifactIdentity id this image realizes (blank = legacy alias-only mapping).",
    )
    artifact_version = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="Portable ArtifactIdentity version; part of the full identity a requirement is matched against.",
    )
    artifact_digest = models.CharField(
        max_length=71,
        blank=True,
        default="",
        help_text="Portable ArtifactIdentity sha256 digest ('sha256:'+64 hex); blank = legacy alias-only mapping.",
    )
    media_type = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="Portable ArtifactIdentity media type (for example application/vnd.raes.image).",
    )
    integrity_ref = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="Verified integrity evidence reference admitting this artifact (required for a portable mapping).",
    )
    provenance_ref = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="Verified provenance evidence reference admitting this artifact (required for a portable mapping).",
    )
    machine_type = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Optional provider machine type; blank lets the backend size from resources/defaults.",
    )
    disk_size_gb = models.PositiveIntegerField(
        null=True, blank=True, help_text="Optional boot disk size (GB); blank uses the backend default."
    )
    disk_type = models.CharField(
        max_length=100, blank=True, default="", help_text="Optional provider disk type; blank uses the backend default."
    )
    enabled = models.BooleanField(
        default=True,
        help_text="Disabled mappings do not resolve (realization fails loud); use instead of deleting to keep audit.",
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Table + uniqueness (one mapping per provider/source_name/source_version)."""

        db_table = "engine_raes_image_mapping"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "source_name", "source_version"],
                name="unique_raes_image_mapping",
            ),
            # A mapping is either fully legacy (no portable identity) or fully
            # portable (identity + both admission evidence refs). A half-populated
            # portable mapping is rejected at the data layer, fail-closed, so a
            # disclosure can never be built without its integrity/provenance evidence.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        artifact_digest="",
                        artifact_id="",
                        artifact_version="",
                        media_type="",
                        integrity_ref="",
                        provenance_ref="",
                    )
                    | (
                        ~models.Q(artifact_digest="")
                        & ~models.Q(artifact_id="")
                        & ~models.Q(artifact_version="")
                        & ~models.Q(media_type="")
                        & ~models.Q(integrity_ref="")
                        & ~models.Q(provenance_ref="")
                    )
                ),
                name="raes_image_mapping_portable_identity_complete",
            ),
        ]

    def __str__(self) -> str:
        version = self.source_version or "*"
        return f"{self.provider}:{self.source_name}@{version} -> {self.image_ref}"


class RaesContentDeliveryBinding(models.Model):
    """Server-owned, byte-free delivery identity persisted beside a Range (#1564).

    Mirrors ``shared.raes.content_delivery.DeliveryBinding``: one row per content
    address realized for a range, carrying only the compiled resource address, the
    sha256 of the delivered payload, the content-addressed storage key, the byte
    count, and the binding schema version. No payload bytes, URL, bucket, or
    credential is ever persisted here (ADR-032-R3). The Engine create seam
    (``engine.services.create_raes_range``) is the sole writer; the provisioner
    only reads these rows (SELECT-only grant) to join + verify + realize content
    at apply time.
    """

    range = models.ForeignKey(
        _RANGE_MODEL,
        on_delete=models.CASCADE,
        related_name="content_delivery_bindings",
        help_text="Range this delivery binding is realized for.",
    )
    content_address = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Compiled RAES content resource address this binding identifies.",
    )
    resource_type = models.CharField(max_length=64, blank=True, default="")
    resource_address = models.CharField(max_length=500, blank=True, default="")
    payload_kind = models.CharField(max_length=32, blank=True, default="")
    install_policy = models.CharField(max_length=32, blank=True, default="")
    sha256 = models.CharField(max_length=64, help_text="Lowercase hex sha256 of the delivered payload.")
    storage_key = models.CharField(
        max_length=500, help_text="Normalized content-addressed object key for the delivered payload."
    )
    byte_count = models.PositiveBigIntegerField(help_text="Size in bytes of the delivered payload.")
    binding_version = models.PositiveIntegerField(help_text="DeliveryBinding schema version (rolling-deploy seam).")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Table + uniqueness (one binding per range/content_address)."""

        db_table = "engine_raes_content_delivery_binding"
        constraints = [
            models.UniqueConstraint(
                fields=["range", "content_address"],
                condition=~models.Q(content_address=""),
                name="unique_raes_content_delivery_binding",
            ),
            models.UniqueConstraint(
                fields=["range", "resource_type", "resource_address"],
                condition=models.Q(resource_type="feature-binding"),
                name="unique_raes_resource_delivery_binding",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(binding_version=1) & ~models.Q(content_address="")
                    | models.Q(
                        binding_version=2,
                        content_address="",
                        resource_type="feature-binding",
                    )
                    & ~models.Q(resource_address="")
                    & ~models.Q(payload_kind="")
                    & ~models.Q(install_policy="")
                ),
                name="valid_raes_delivery_binding_identity",
            ),
        ]

    def __str__(self) -> str:
        identity = self.content_address or f"{self.resource_type}:{self.resource_address}"
        return f"RaesContentDeliveryBinding({self.range_id}, {identity})"


class RaesParticipantAccessBinding(models.Model):
    """Immutable, non-secret participant-access identity beside a Range (#1710).

    Mirrors ``shared.raes.participant_access.ParticipantAccessBinding``: one row
    per authored ``(target, channel)`` the compiled scenario declared, carrying
    only resolved compiled addresses and the closed channel. It is the
    declaration of record the realized access binding is later compared against,
    never authorization on its own.

    No credential, credential reference, login name, address, port, or provider
    identifier is ever persisted here (ADR-032-R10) -- the provisioner resolves
    those from provisioning truth after joining this row to the separately
    parsed plan. The Engine create seam (``engine.services.create_raes_range``)
    is the sole writer; the provisioner never reads this table directly and
    receives the rows only through the generation-fenced operation input.
    """

    range = models.ForeignKey(
        _RANGE_MODEL,
        on_delete=models.CASCADE,
        related_name="participant_access_bindings",
        help_text="Range this participant-access declaration is realized for.",
    )
    target_address = models.CharField(
        max_length=500,
        help_text="Compiled RAES provisioning node address the participant may reach.",
    )
    channel = models.CharField(
        max_length=32,
        help_text="Closed participant access channel (ssh/rdp).",
    )
    account_address = models.CharField(
        max_length=500,
        help_text="Compiled RAES account address the channel is brokered as.",
    )
    binding_version = models.PositiveIntegerField(
        help_text="ParticipantAccessBinding schema version (rolling-deploy seam).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Table + uniqueness (one binding per range/target/channel)."""

        db_table = "engine_raes_participant_access_binding"
        constraints = [
            models.UniqueConstraint(
                fields=["range", "target_address", "channel"],
                name="unique_raes_participant_access_binding",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(binding_version=1)
                    & ~models.Q(target_address="")
                    & ~models.Q(account_address="")
                    & models.Q(channel__in=["ssh", "rdp"])
                ),
                name="valid_raes_participant_access_binding_identity",
            ),
        ]

    def __str__(self) -> str:
        return f"RaesParticipantAccessBinding({self.range_id}, {self.target_address}/{self.channel})"


class RaesArtifactSatisfactionBinding(models.Model):
    """Generation-fenced artifact-satisfaction decision beside a Range (#1580, ADR-034-R8).

    Mirrors :class:`shared.raes.artifact_binding.ArtifactBinding`: one row per
    authored artifact requirement the CMS launch resolved to a concrete
    backend-owned image. Carries the portable satisfaction disclosure identity
    (requirement id + ``ArtifactIdentity`` fields + mechanism/acquisition/timing)
    for audit + fail-closed verification and the concrete provider ``image_ref``
    (+ optional sizing) the provisioner applies. No credential, URL, bucket,
    signed URL, payload bytes, or secret is ever persisted here.

    The CMS launch (through ``engine.services.create_raes_range``) is the sole
    writer; the engine launch path reads these rows into the immutable
    ``OperationInput`` and the provisioner realizes the fenced binding without
    re-resolving. The provisioner never reads this table directly.
    """

    range = models.ForeignKey(
        _RANGE_MODEL,
        on_delete=models.CASCADE,
        related_name="artifact_satisfaction_bindings",
        help_text="Range this artifact-satisfaction decision is realized for.",
    )
    target_address = models.CharField(
        max_length=500,
        help_text="Compiled RAES provisioning node address this binding realizes.",
    )
    requirement_id = models.CharField(
        max_length=256, help_text="Authored artifact requirement id this binding satisfies."
    )
    artifact_id = models.CharField(max_length=256, help_text="Portable ArtifactIdentity id realized.")
    artifact_version = models.CharField(max_length=256, help_text="Portable ArtifactIdentity version realized.")
    digest = models.CharField(max_length=71, help_text="Portable ArtifactIdentity sha256 digest ('sha256:'+64 hex).")
    media_type = models.CharField(max_length=256, help_text="Portable ArtifactIdentity media type.")
    mechanism = models.CharField(
        max_length=128, help_text="Portable satisfaction mechanism (for example exact-artifact)."
    )
    acquisition = models.CharField(max_length=32, help_text="Acquisition transport of the selected route.")
    timing = models.CharField(max_length=32, help_text="Realization timing of the selected route.")
    image_ref = models.CharField(max_length=500, help_text="Concrete backend image the provisioner realizes.")
    image_id = models.CharField(
        max_length=20, blank=True, default="", help_text="Verified immutable GCE image identity."
    )
    machine_type = models.CharField(max_length=100, blank=True, default="")
    disk_size_gb = models.PositiveIntegerField(null=True, blank=True)
    disk_type = models.CharField(max_length=100, blank=True, default="")
    binding_version = models.PositiveIntegerField(help_text="ArtifactBinding schema version (rolling-deploy seam).")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Table + uniqueness (one artifact binding per range/target node)."""

        db_table = "engine_raes_artifact_satisfaction_binding"
        constraints = [
            models.UniqueConstraint(
                fields=["range", "target_address"],
                name="unique_raes_artifact_satisfaction_binding",
            ),
        ]

    def __str__(self) -> str:
        return f"RaesArtifactSatisfactionBinding({self.range_id}, {self.target_address} -> {self.image_ref})"
