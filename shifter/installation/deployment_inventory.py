"""Bounded external deployment loader; validity does not grant bootstrap authority."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .deployment_inventory_types import DeploymentRecord
from .errors import ConfigIssue, InstallationConfigError
from .loader import parse_yaml_mapping, validate_root_config_data

MAX_RECORD_BYTES = 1_048_576


def _invalid(message: str) -> InstallationConfigError:
    """Build a structured inventory validation error."""
    return InstallationConfigError([ConfigIssue("inventory", message)])


def validate_record(data: dict[str, Any]) -> DeploymentRecord:
    """Use the full installation validator, then the common envelope validator.

    Inventory diagnostics never include rejected values or private record keys.
    """
    try:
        if not isinstance(data, dict) or type(data.get("version")) is not int:
            raise ValueError("invalid record")
        installation = validate_root_config_data(data["installation"])
        record = DeploymentRecord.model_validate({**data, "installation": installation})
        from .deployment_identity_gcp import trust_condition

        trust_condition(record.execution)
        return record
    except (KeyError, TypeError, ValueError, ValidationError, InstallationConfigError):
        raise _invalid("record fails installation, schema or ownership validation") from None


def load_record(inventory_root: Path, relative_path: str) -> DeploymentRecord:
    """Read a regular, bounded record contained in the declared inventory root."""
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise _invalid("record path must be relative and contained in the inventory")
    descriptor = None
    try:
        descriptor = os.open(inventory_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in candidate.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        child = os.open(candidate.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(child, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise _invalid("record must be a regular file")
            payload = source.read(MAX_RECORD_BYTES + 1)
        return parse_record(payload)
    except (OSError, ValueError, RecursionError, InstallationConfigError):
        raise _invalid("record is unreadable, malformed, or outside the inventory boundary") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def parse_record(payload: bytes) -> DeploymentRecord:
    """Validate bounded committed bytes with the same loader as local records."""
    try:
        if len(payload) > MAX_RECORD_BYTES:
            raise ValueError("oversized record")
        return validate_record(parse_yaml_mapping(payload.decode("utf-8"), Path("inventory")))
    except (ValueError, RecursionError, InstallationConfigError):
        raise _invalid("record is oversized or malformed") from None


def validate_ownership(records: list[DeploymentRecord]) -> None:
    """Reject competing owners before an inventory can bootstrap any deployment."""
    owners: set[tuple[str, ...]] = set()
    protected_buckets = {state.bucket for record in records for state in record.state.values()}
    protected_buckets.update(record.gcp.evidence_bucket for record in records if record.gcp)
    for record in records:
        resources = [("deployment", record.installation.deployment.name)]
        resources.extend(("bucket", state.bucket) for state in record.state.values())
        resources.extend(
            ("subject", record.execution.repository.lower(), context.environment.lower())
            for contexts in record.execution.purposes.values()
            for context in contexts
        )
        if record.gcp:
            if protected_buckets.intersection(record.gcp.build_read_bucket_names) or protected_buckets.intersection(
                record.gcp.platform_external_bucket_names
            ):
                raise _invalid("capability authority overlaps inventory-owned foundations or state")
            resources.extend(
                [
                    ("pool", record.installation.settings["project_id"], record.gcp.name_prefix),
                    ("runner", record.installation.settings["project_id"], record.gcp.name_prefix),
                    ("account", record.installation.settings["project_id"], record.gcp.name_prefix.replace("-", "")),
                    ("bucket", record.gcp.evidence_bucket),
                    ("platform", str(record.installation.settings["project_id"])),
                ]
            )
        if any(resource in owners for resource in resources):
            raise _invalid("deployments have overlapping resource or state ownership")
        owners.update(resources)
