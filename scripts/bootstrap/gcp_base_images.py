"""Reusable GCE base-image consumption for the supported GCP tenant bootstrap.

A fresh GCP tenant should not re-bake its guest images. At bootstrap time this
module discovers the minimum base guest set (Kali, Ubuntu, DC) from the public
GHCR packages published by ``packer-gcp.yml``, validates each artifact and its
provenance, pins an immutable digest, and imports the disk as a *native GCE
image* in the target project - reusing an existing image when the digest is
unchanged, creating a traceable new one when it changes. The caller wires the
resulting ``GCP_RANGE_*_IMAGE`` references into the deployment (#2309).

Sourcing is hard-coded to public GHCR. Private packages (#2312) and a shipped
default image-pack installed through the content-pack/adapter seam are separate
follow-ups.

Subprocess calls go through ``bootstrap_core.run_cmd`` / ``gcloud_resource_exists``
so tests mock that boundary (ADR-019). The parsing/validation helpers are pure.
"""

from __future__ import annotations

import json
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from bootstrap_core import (
    header,
    info,
    run_cmd,
    subheader,
    success,
)

__all__ = [
    "BASE_IMAGE_ROLES",
    "BaseImageError",
    "ImportedImage",
    "ResolvedArtifact",
    "discover_and_import",
    "import_base_image",
    "package_for_role",
    "render_range_image_env",
    "resolve_artifact",
]

# The minimum reusable base set the supported GCE tenant bootstrap needs.
BASE_IMAGE_ROLES = ("kali", "ubuntu", "dc")

# OCI contract published by packer-gcp.yml (publish_target=ghcr).
GCE_IMAGE_ARTIFACT_TYPE = "application/vnd.shifter.gce-image.v1"
GCE_IMAGE_MEDIA_TYPE = "application/vnd.shifter.gce-image.tar.gz"

# GHCR owner the base-image packages are published under.
GHCR_OWNER = "brad-edwards"

# Each base role maps to the GCE range-cell image env var the runtime consumes.
# ubuntu is the default unkeyed Linux/host profile (GCP_RANGE_LINUX_IMAGE).
_ROLE_TO_RANGE_ENV = {
    "kali": "GCP_RANGE_KALI_IMAGE",
    "ubuntu": "GCP_RANGE_LINUX_IMAGE",
    "dc": "GCP_RANGE_DC_IMAGE",
}

# Raw disk export/import does not retain image-level guest OS features. Every
# runtime range guest uses Shielded VM Secure Boot, so all imported bases must
# be marked UEFI compatible. Windows-family roles additionally need WINDOWS.
# The premium Windows license is not carried by a raw disk export/import, so the
# DC image imported from GHCR is verified for boot/licensing in the #2309 proof-2
# tenant run.
_WINDOWS_ROLES = frozenset({"dc"})

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_DISCOVERY_TAG_RE = re.compile(r"^gce-(\d+)$")
_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class BaseImageError(RuntimeError):
    """A base-image artifact is missing, incompatible, or failed to import."""


@dataclass(frozen=True)
class ResolvedArtifact:
    """A validated, digest-pinned base-image artifact ready to import."""

    role: str
    package: str  # e.g. ghcr.io/brad-edwards/shifter-gce-kali
    digest: str  # sha256:<64 hex>
    disk_digest: str  # sha256:<64 hex> for the validated GCE disk layer
    revision: str  # provenance: the protected build source revision

    @property
    def pinned_reference(self) -> str:
        """Immutable ``oci://<package>@<digest>`` reference (never a tag)."""
        return f"oci://{self.package}@{self.digest}"

    @property
    def short_digest(self) -> str:
        """First 12 hex of the digest, for deterministic image naming/reuse."""
        return self.digest.split(":", 1)[1][:12]


@dataclass(frozen=True)
class ImportedImage:
    """A native GCE image made available for one base role."""

    role: str
    image_name: str
    image_ref: str  # projects/<project>/global/images/<name> (a GCP_RANGE_*_IMAGE value)
    digest: str
    reused: bool


def package_for_role(role: str) -> str:
    """Return the GHCR package path for a base role."""
    if role not in BASE_IMAGE_ROLES:
        raise BaseImageError(f"unsupported public base-image role {role!r}")
    return f"ghcr.io/{GHCR_OWNER}/shifter-gce-{role}"


# --- Pure parsing / validation -----------------------------------------------


def _newest_discovery_tag(tags: list[str]) -> str | None:
    """Return the newest ``gce-<id>`` discovery tag, or None when there is none.

    The ``<id>`` is the source GCE image's numeric ID. GCE assigns image IDs
    monotonically increasing over time within a project, so the highest ID among
    a package's tags is the most recently built artifact - a defined ordering,
    not a guess. Every tag in a package comes from the one protected build.
    """
    numbered = []
    for tag in tags:
        match = _DISCOVERY_TAG_RE.fullmatch(tag.strip())
        if match:
            numbered.append((int(match.group(1)), tag.strip()))
    if not numbered:
        return None
    return max(numbered)[1]


def _disk_layer_digest(manifest: dict[str, object]) -> str:
    """Return the one validated, digest-pinned GCE disk layer."""
    layers = manifest.get("layers") or []
    if not isinstance(layers, list) or not all(isinstance(layer, dict) for layer in layers):
        raise BaseImageError("base-image manifest layers must be an array of descriptors")
    disk_layers = [layer for layer in layers if layer.get("mediaType") == GCE_IMAGE_MEDIA_TYPE]
    if len(disk_layers) != 1:
        raise BaseImageError(f"expected exactly one {GCE_IMAGE_MEDIA_TYPE} layer, found {len(disk_layers)}")
    layer_digest = str(disk_layers[0].get("digest", "")).strip()
    if not _DIGEST_RE.fullmatch(layer_digest):
        raise BaseImageError("base-image disk layer is missing a full sha256 digest")
    return layer_digest


def _validate_disk_layer(manifest: dict[str, object]) -> None:
    """Require exactly one digest-pinned GCE disk layer."""
    _disk_layer_digest(manifest)


def _validate_annotations(manifest: dict[str, object], *, role: str) -> str:
    """Require the requested role and a protected source revision."""
    annotations = manifest.get("annotations") or {}
    if not isinstance(annotations, dict):
        raise BaseImageError("base-image manifest annotations must be an object")
    declared_role = str(annotations.get("com.shifter.image.role", "")).strip()
    if declared_role != role:
        raise BaseImageError(f"artifact role annotation {declared_role!r} does not match requested role {role!r}")
    revision = str(annotations.get("org.opencontainers.image.revision", "")).strip()
    if not _REVISION_RE.fullmatch(revision):
        raise BaseImageError("artifact is missing a full protected-source revision (image.revision annotation)")
    return revision


def validate_artifact_manifest(manifest: dict[str, object], *, role: str) -> str:
    """Validate an OCI manifest against the GCE base-image contract.

    Returns the provenance source revision. Raises :class:`BaseImageError` when
    the artifact type, layer media type, role annotation, or provenance is wrong
    or missing, so an incompatible artifact is rejected before any GCE mutation.
    """
    if not isinstance(manifest, dict):
        raise BaseImageError("base-image manifest is not a JSON object")
    artifact_type = manifest.get("artifactType", "")
    if artifact_type != GCE_IMAGE_ARTIFACT_TYPE:
        raise BaseImageError(f"unexpected artifactType {artifact_type!r}; expected {GCE_IMAGE_ARTIFACT_TYPE}")
    _validate_disk_layer(manifest)
    return _validate_annotations(manifest, role=role)


def image_name_for(role: str, short_digest: str) -> str:
    """Deterministic, digest-derived GCE image name (drives idempotent reuse)."""
    return f"shifter-{role}-{short_digest}"


def render_range_image_env(imported: dict[str, ImportedImage]) -> dict[str, str]:
    """Map imported base images to their ``GCP_RANGE_*_IMAGE`` runtime values."""
    return {_ROLE_TO_RANGE_ENV[role]: image.image_ref for role, image in imported.items() if role in _ROLE_TO_RANGE_ENV}


def _required_guest_os_features(role: str) -> frozenset[str]:
    """Return image features required by the range runtime posture."""
    features = {"UEFI_COMPATIBLE"}
    if role in _WINDOWS_ROLES:
        features.add("WINDOWS")
    return frozenset(features)


def _guest_os_feature_types(metadata: dict[str, object]) -> frozenset[str]:
    """Read normalized guest feature names from GCE image metadata."""
    raw = metadata.get("guestOsFeatures") or []
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(
        str(item.get("type", "")).strip()
        for item in raw
        if isinstance(item, dict) and str(item.get("type", "")).strip()
    )


# --- Registry / GCE boundary (mocked in tests via bootstrap_core.run_cmd) -----


def _oras_json(cmd: list[str], *, what: str) -> dict[str, object]:
    """Run an oras command that emits JSON and parse it, failing clearly."""
    result = run_cmd(cmd, check=False, capture=True)
    if result is None or result.returncode != 0:
        stderr = (getattr(result, "stderr", "") or "").strip()
        raise BaseImageError(f"{what} failed: {stderr or 'oras returned a non-zero status'}")
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise BaseImageError(f"{what} returned invalid JSON: {exc}") from exc


def _discover_newest_tag(package: str) -> str:
    """List discovery tags for a package and return the newest, or fail clearly."""
    result = run_cmd(["oras", "repo", "tags", package], check=False, capture=True)
    if result is None or result.returncode != 0:
        stderr = (getattr(result, "stderr", "") or "").strip()
        raise BaseImageError(
            f"no base image found at {package}; publish it via packer-gcp.yml "
            f"(publish_target=ghcr) then re-run ({stderr or 'oras repo tags failed'})"
        )
    tags = [line for line in (result.stdout or "").splitlines() if line.strip()]
    newest = _newest_discovery_tag(tags)
    if newest is None:
        raise BaseImageError(f"package {package} has no gce-<id> base-image tags to discover")
    return newest


def _fetch_digest(package: str, tag: str) -> str:
    """Resolve a discovery tag to its immutable manifest digest."""
    descriptor = _oras_json(
        ["oras", "manifest", "fetch", "--descriptor", f"{package}:{tag}"],
        what=f"resolving digest for {package}:{tag}",
    )
    digest = str(descriptor.get("digest", "")).strip()
    if not _DIGEST_RE.fullmatch(digest):
        raise BaseImageError(f"registry did not return a valid sha256 digest for {package}:{tag}")
    return digest


def _fetch_manifest(package: str, digest: str) -> dict[str, object]:
    """Fetch the manifest for a digest-pinned reference."""
    return _oras_json(
        ["oras", "manifest", "fetch", f"{package}@{digest}"],
        what=f"fetching manifest for {package}@{digest}",
    )


def resolve_artifact(role: str) -> ResolvedArtifact:
    """Discover, digest-pin, and validate the GHCR base-image artifact for a role."""
    package = package_for_role(role)
    digest = _fetch_digest(package, _discover_newest_tag(package))
    manifest = _fetch_manifest(package, digest)
    revision = validate_artifact_manifest(manifest, role=role)
    return ResolvedArtifact(
        role=role,
        package=package,
        digest=digest,
        disk_digest=_disk_layer_digest(manifest),
        revision=revision,
    )


def _existing_image_metadata(project: str, image_name: str) -> dict[str, object] | None:
    """Return code-owned provenance, status, and boot features for an existing image."""
    result = run_cmd(
        [
            "gcloud",
            "compute",
            "images",
            "describe",
            image_name,
            "--project",
            project,
            "--format=json(description,labels,status,guestOsFeatures)",
        ],
        check=False,
        capture=True,
    )
    if result is None or result.returncode != 0:
        return None
    try:
        metadata = json.loads(getattr(result, "stdout", "") or "{}")
    except json.JSONDecodeError as exc:
        raise BaseImageError(f"GCE image {image_name} returned invalid metadata JSON") from exc
    if not isinstance(metadata, dict):
        raise BaseImageError(f"GCE image {image_name} returned invalid metadata")
    return metadata


def _verify_image_ready(project: str, image_name: str) -> None:
    """Fail unless the freshly created GCE image reports status READY."""
    result = run_cmd(
        ["gcloud", "compute", "images", "describe", image_name, "--project", project, "--format=value(status)"],
        check=False,
        capture=True,
    )
    status = (getattr(result, "stdout", "") or "").strip()
    if status != "READY":
        raise BaseImageError(f"imported GCE image {image_name} is not READY (status={status or 'unknown'})")


def _existing_image_is_reusable(artifact: ResolvedArtifact, metadata: dict[str, object], image_name: str) -> bool:
    """Return true only for an exact code-owned, READY, runtime-compatible image."""
    labels = metadata.get("labels") or {}
    if not isinstance(labels, dict):
        labels = {}
    exact_source = str(metadata.get("description", "")).strip() == artifact.pinned_reference
    exact_role = str(labels.get("shifter-base-role", "")).strip() == artifact.role
    exact_digest_label = str(labels.get("shifter-base-digest", "")).strip() == artifact.short_digest
    if not (exact_source and exact_role and exact_digest_label):
        raise BaseImageError(
            f"GCE image {image_name} already exists without the exact source and role metadata; "
            "refusing to reuse an image this import did not create"
        )
    return str(metadata.get("status", "")).strip() == "READY" and _required_guest_os_features(artifact.role).issubset(
        _guest_os_feature_types(metadata)
    )


def _delete_owned_image(project: str, image_name: str) -> None:
    """Delete a proven code-owned image before converging its import contract."""
    run_cmd(["gcloud", "compute", "images", "delete", image_name, "--project", project, "--quiet"])


def _pull_disk_tarball(artifact: ResolvedArtifact, destination: Path) -> Path:
    """Fetch the validated disk blob to a caller-owned path and return it."""
    tarball = destination / f"{artifact.role}-{artifact.short_digest}.tar.gz"
    run_cmd(
        [
            "oras",
            "blob",
            "fetch",
            "--output",
            str(tarball),
            f"{artifact.package}@{artifact.disk_digest}",
        ]
    )
    if not tarball.is_file():
        raise BaseImageError(f"disk blob fetch produced no tarball for {artifact.pinned_reference}")
    return tarball


def _reconcile_existing_owned_image(
    artifact: ResolvedArtifact,
    metadata: dict[str, object],
    *,
    image_name: str,
    image_ref: str,
    project: str,
    dry_run: bool,
) -> ImportedImage | None:
    """Reuse, or clear for reimport, an existing code-owned image.

    Returns the reusable image when its digest and runtime guest features
    match; otherwise deletes the incompatible owned image (unless ``dry_run``)
    and returns ``None`` so the caller reimports.
    """
    if _existing_image_is_reusable(artifact, metadata, image_name):
        _verify_image_ready(project, image_name)
        info(f"Reusing existing GCE image {image_name} for role '{artifact.role}' (digest unchanged)")
        return ImportedImage(artifact.role, image_name, image_ref, artifact.digest, reused=True)
    status = str(metadata.get("status", "")).strip() or "unknown"
    if status not in {"FAILED", "READY"}:
        raise BaseImageError(f"code-owned GCE image {image_name} is not READY (status={status}); retry later")
    missing_features = _required_guest_os_features(artifact.role) - _guest_os_feature_types(metadata)
    reason = f"missing guest features {sorted(missing_features)}" if missing_features else f"status={status}"
    if dry_run:
        info(f"[DRY-RUN] Would replace code-owned GCE image {image_name} ({reason})")
    else:
        info(f"Replacing code-owned GCE image {image_name} ({reason})")
        _delete_owned_image(project, image_name)
    return None


def import_base_image(
    artifact: ResolvedArtifact,
    *,
    project: str,
    staging_bucket: str,
    dry_run: bool = False,
) -> ImportedImage:
    """Import (or reuse) a validated artifact as a native GCE image.

    An unchanged digest reuses the existing digest-named image when its runtime
    guest features match. A changed digest or incompatible owned image is
    imported as a traceably named image and moves the ``shifter-<role>`` family
    head. The staging object is removed on success and failure.
    """
    image_name = image_name_for(artifact.role, artifact.short_digest)
    family = f"shifter-{artifact.role}"
    image_ref = f"projects/{project}/global/images/{image_name}"

    metadata = _existing_image_metadata(project, image_name)
    if metadata is not None:
        reused = _reconcile_existing_owned_image(
            artifact,
            metadata,
            image_name=image_name,
            image_ref=image_ref,
            project=project,
            dry_run=dry_run,
        )
        if reused is not None:
            return reused

    if dry_run:
        info(f"[DRY-RUN] Would import {artifact.pinned_reference} as native GCE image {image_name}")
        return ImportedImage(artifact.role, image_name, image_ref, artifact.digest, reused=False)
    if not staging_bucket:
        raise BaseImageError("base-image import requires a run-owned transfer bucket")

    subheader(f"Importing '{artifact.role}' base image as native GCE image {image_name}")
    staging_uri = f"gs://{staging_bucket}/base-images/{image_name}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="shifter-gce-base-") as tmp:
        tarball = _pull_disk_tarball(artifact, Path(tmp))
        try:
            run_cmd(["gcloud", "storage", "cp", "--quiet", str(tarball), staging_uri, "--project", project])
            create_cmd = [
                "gcloud",
                "compute",
                "images",
                "create",
                image_name,
                "--source-uri",
                staging_uri,
                "--family",
                family,
                "--project",
                project,
                "--labels",
                f"shifter-base-role={artifact.role},shifter-base-digest={artifact.short_digest}",
                "--description",
                artifact.pinned_reference,
            ]
            create_cmd += [
                "--guest-os-features",
                ",".join(sorted(_required_guest_os_features(artifact.role))),
            ]
            run_cmd(create_cmd)
            _verify_image_ready(project, image_name)
        finally:
            # Always clear the staging object so no transfer drift is left behind.
            run_cmd(["gcloud", "storage", "rm", "--quiet", staging_uri, "--project", project], check=False)

    success(f"Imported '{artifact.role}' as native GCE image {image_name}")
    return ImportedImage(artifact.role, image_name, image_ref, artifact.digest, reused=False)


def _run_checked(cmd: list[str], *, failure: str) -> None:
    """Run a command while retaining domain-specific failure handling."""
    result = run_cmd(cmd, check=False, capture=True)
    if result is None or result.returncode != 0:
        raise BaseImageError(failure)


def _create_transfer_bucket(project: str, region: str) -> str:
    """Create and return one private, run-owned transfer bucket."""
    bucket = f"shifter-base-import-{project}-{uuid.uuid4().hex[:12]}"
    if len(bucket) > 63:
        raise BaseImageError("project ID is too long for the run-owned transfer bucket name")
    _run_checked(
        [
            "gcloud",
            "storage",
            "buckets",
            "create",
            f"gs://{bucket}",
            "--project",
            project,
            "--location",
            region,
            "--uniform-bucket-level-access",
            "--public-access-prevention",
            "--soft-delete-duration=0",
        ],
        failure=f"failed to create run-owned base-image transfer bucket {bucket}",
    )
    return bucket


def _delete_transfer_bucket(project: str, bucket: str) -> None:
    """Delete every object/version and the exact run-owned bucket."""
    _run_checked(
        ["gcloud", "storage", "rm", "--recursive", f"gs://{bucket}/", "--project", project, "--quiet"],
        failure=f"base-image transfer cleanup failed for run-owned bucket {bucket}",
    )


def discover_and_import(
    *,
    project: str,
    region: str = "us-central1",
    roles: tuple[str, ...] = BASE_IMAGE_ROLES,
    dry_run: bool = False,
) -> dict[str, ImportedImage]:
    """Discover, validate, and import the reusable base set as native GCE images.

    Returns the imported/reused image for each role; :func:`render_range_image_env`
    turns that into the ``GCP_RANGE_*_IMAGE`` values the runtime env consumes. A
    missing or incompatible artifact raises :class:`BaseImageError` (no silent
    Packer bake, no blind accept).
    """
    header("Reusable GCE base images (GHCR -> native GCE)")
    artifacts: list[ResolvedArtifact] = []
    for role in roles:
        artifact = resolve_artifact(role)
        info(f"Resolved '{role}' -> {artifact.pinned_reference} (build {artifact.revision[:12]})")
        artifacts.append(artifact)

    if dry_run:
        return {
            artifact.role: import_base_image(
                artifact,
                project=project,
                staging_bucket="",
                dry_run=True,
            )
            for artifact in artifacts
        }

    bucket = _create_transfer_bucket(project, region)
    try:
        return {
            artifact.role: import_base_image(
                artifact,
                project=project,
                staging_bucket=bucket,
            )
            for artifact in artifacts
        }
    finally:
        _delete_transfer_bucket(project, bucket)
