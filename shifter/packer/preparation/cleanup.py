"""Remove owned preparation resources after every creator has been quiesced."""

from typing import Any
from uuid import UUID

from preparation.gce_build import ComputeAPI


def cleanup_operation(
    api: ComputeAPI, operation_id: UUID, attempts: list[UUID], *, retained_image: dict[str, str] | None = None
) -> dict[str, list[str]]:
    """Delete VMs before their disks; release capacity only after empty readback.

    The platform controller must stop every worker before dispatching cleanup.
    Accepted provider operations can outlive those workers; wait for them before
    enumerating resources. Attempt UUIDs come from the durable operation history.
    """
    api.wait_for_attempt_operations(attempts)
    scopes = [
        f"projects/{api.project}/zones/{api.zone}/instances",
        f"projects/{api.project}/zones/{api.zone}/disks",
        f"projects/{api.project}/global/images",
    ]
    retained = retained_image or {}
    if retained and (
        set(retained) != {"image_ref", "image_id"}
        or not retained["image_ref"].startswith(scopes[-1] + "/")
        or not retained["image_id"].isdigit()
    ):
        raise ValueError("invalid retained image identity")

    def disposable(scope: str, resource: dict[str, Any]) -> bool:
        """Handle disposable."""
        reference = f"{scope}/{resource['name']}"
        if reference != retained.get("image_ref"):
            return True
        if str(resource["id"]) != retained["image_id"]:
            raise ValueError("retained image identity changed")
        return False

    for scope in scopes:
        for resource in api.list_owned(scope, operation_id):
            if disposable(scope, resource):
                api.delete_owned(f"{scope}/{resource['name']}", str(resource["id"]), operation_id)
    if any(disposable(scope, resource) for scope in scopes for resource in api.list_owned(scope, operation_id)):
        raise RuntimeError("preparation resources remain after cleanup")
    return {"resources_remaining": []}
