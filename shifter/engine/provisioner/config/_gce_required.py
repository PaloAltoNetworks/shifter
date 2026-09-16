"""Required environment resolution for the GCE range-cell backend."""

import os

from ._range import get_range_availability_zone


def resolve_gce_range_required_env() -> tuple[str, str, str, str]:
    """Resolve required environment for the GCE range-cell backend.

    ``GCP_RANGE_CELL_PROJECT_ID`` takes precedence so range cells can be
    provisioned into a different project than the control plane's
    ``GCP_PROJECT_ID`` (and so the range backend is unaffected when the
    control-plane project is a deploy-overlay placeholder). It falls back to the
    control-plane project keys, mirroring ``GCP_RANGE_VERTEX_PROJECT_ID``.
    """
    project_id = (
        os.environ.get("GCP_RANGE_CELL_PROJECT_ID")
        or os.environ.get("GCP_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("CLOUD_PROJECT_ID")
        or ""
    ).strip()
    region = (
        os.environ.get("RANGE_NETWORK_REGION") or os.environ.get("GCP_REGION") or os.environ.get("CLOUD_REGION") or ""
    ).strip()
    zone = get_range_availability_zone(default="").strip()
    service_account_email = os.environ.get("GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL", "").strip()
    return project_id, region, zone, service_account_email


def missing_gce_range_required_env(
    *,
    project_id: str,
    region: str,
    zone: str,
    service_account_email: str,
) -> list[str]:
    """Return display names for missing GCE range-cell settings."""
    return [
        name
        for name, value in (
            ("GCP_RANGE_CELL_PROJECT_ID/GCP_PROJECT_ID", project_id),
            ("RANGE_NETWORK_REGION/GCP_REGION", region),
            ("RANGE_NETWORK_ZONE", zone),
            ("GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL", service_account_email),
        )
        if not value
    ]
