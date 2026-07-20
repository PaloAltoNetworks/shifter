"""Image-source URL resolution for GDC VM Runtime disks."""

from __future__ import annotations

from typing import Any


def _resolve_image_source(source_url: str, gcs_secret_name: str | None) -> dict[str, Any]:
    """Translate a Shifter image source URL into a GDC disk-source spec."""
    if source_url.startswith("gs://"):
        gcs_source: dict[str, Any] = {"url": source_url}
        if gcs_secret_name:
            gcs_source["secretRef"] = gcs_secret_name
        resolved: dict[str, Any] = {"gcs": gcs_source}
    elif source_url.startswith("https://"):
        resolved = {"http": {"url": source_url}}
    elif source_url.startswith("docker://"):
        resolved = {"registry": {"url": source_url}}
    elif source_url.startswith("registry://"):
        resolved = {"registry": {"url": f"docker://{source_url.removeprefix('registry://')}"}}
    elif source_url.startswith("oci://"):
        resolved = {"registry": {"url": f"docker://{source_url.removeprefix('oci://')}"}}
    else:
        raise RuntimeError(
            f"Unsupported GDC VM Runtime image source {source_url!r}. "
            "Use gs://, https://, docker://, registry://, or oci://."
        )
    return resolved
