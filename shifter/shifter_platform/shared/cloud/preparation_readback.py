"""Read-only provider observations for the preparation controller's admission gate."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any, Protocol
from uuid import UUID

from shared.artifact_preparation import BuildEvidence, InputEvidence, OutputEvidence, RawDiskObservation
from shared.preparation_grant import PreparationGrantConfiguration


class PreparationComputeReader(Protocol):
    """Minimal bounded Compute read interface used by admission verification."""

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]: ...


class ComputeReader:
    """Only bounded GETs to the configured Compute API; never provider mutations."""

    def __init__(self, project: str) -> None:
        from shared.cloud.gcp.base import import_google_module

        auth = import_google_module("google.auth")
        transport = import_google_module("google.auth.transport.requests")
        credentials, _ = auth.default(scopes=["https://www.googleapis.com/auth/compute.readonly"])
        self.session = transport.AuthorizedSession(credentials)
        self.project = project

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Paths are constructed by the observer, never accepted from HTTP clients."""
        if (
            not path.startswith(f"projects/{self.project}/")
            or any(char in path for char in "?#%")
            or ".." in path.split("/")
        ):
            raise ValueError("preparation readback is outside the configured project")
        response = self.session.get(
            "https://compute.googleapis.com/compute/v1/" + path,
            allow_redirects=False,
            timeout=30,
            stream=True,
            params=params,
        )
        try:
            if response.status_code != 200:
                raise ValueError("preparation provider readback failed")
            payload = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                payload.extend(chunk)
                if len(payload) > 2 * 1024**2:
                    raise ValueError("preparation provider readback exceeds its bound")
            import json

            value = json.loads(payload)
            if not isinstance(value, dict):
                raise ValueError("invalid preparation provider observation")
            return value
        finally:
            response.close()


class GCEPreparationReadback:
    """Observe actual resources after worker quiescence and before the database fence."""

    def __init__(
        self,
        grant: PreparationGrantConfiguration,
        reader: PreparationComputeReader | None = None,
    ) -> None:
        self.grant = grant
        self.reader = reader or ComputeReader(grant.project_id)
        self.scope = f"projects/{grant.project_id}/zones/{grant.zone}"

    def verify_cleanup(
        self,
        operation: UUID,
        attempts: list[UUID],
        *,
        retained_image: dict[str, Any] | None = None,
    ) -> None:
        """Release capacity only after settled provider operations and actual absence."""
        if len(attempts) > 128:
            raise ValueError("preparation history exceeds its bound")
        names = tuple("prep-" + attempt.hex for attempt in attempts)
        self._verify_settled_operations(names)
        self._verify_cleanup_resources(operation, retained_image or {})

    def _verify_settled_operations(self, names: tuple[str, ...]) -> None:
        for scope in (self.scope, f"projects/{self.grant.project_id}/global"):
            for item in self._items(f"{scope}/operations", {"filter": "status != DONE"}):
                target = str(item.get("targetLink", ""))
                name = target.rsplit("/", 1)[-1]
                if item.get("status") != "DONE" and any(name == stem or name.startswith(stem + "-") for stem in names):
                    raise ValueError("preparation provider operations remain unsettled")

    def _verify_cleanup_resources(self, operation: UUID, retained: dict[str, Any]) -> None:
        found = False
        for scope in (
            f"{self.scope}/instances",
            f"{self.scope}/disks",
            f"projects/{self.grant.project_id}/global/images",
        ):
            for item in self._items(scope, {"filter": f"labels.shifter-preparation = {operation.hex}"}):
                if item.get("labels", {}).get("shifter-preparation") != operation.hex:
                    continue
                reference = f"{scope}/{item.get('name', '')}"
                if reference != retained.get("image_ref") or str(item.get("id")) != retained.get("image_id"):
                    raise ValueError("preparation resources remain after cleanup")
                found = True
        if retained and not found:
            raise ValueError("admitted image is missing after cleanup")

    def _items(self, path: str, parameters: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Bound pages, records and continuation tokens without following URLs."""
        params = dict(parameters, maxResults=100)
        seen = set()
        count = 0
        for _ in range(16):
            page = self.reader.get(path, params=params)
            items = page.get("items", [])
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError("invalid preparation resource listing")
            count += len(items)
            if count > 1024:
                raise ValueError("preparation provider listing exceeds its bound")
            yield from items
            token = page.get("nextPageToken")
            if not token:
                return
            if not isinstance(token, str) or not re.fullmatch(r"[a-zA-Z0-9_+/=-]{1,2048}", token) or token in seen:
                raise ValueError("invalid preparation provider continuation")
            seen.add(token)
            params["pageToken"] = token
        raise ValueError("preparation provider pagination exceeds its bound")

    def verify_build(self, operation: UUID, attempt: UUID, evidence: dict[str, Any]) -> None:
        """Require immutable image/disk/guest identities and actual stopped isolation."""
        built = BuildEvidence.model_validate(evidence)
        name = "prep-" + attempt.hex
        image_path = f"projects/{self.grant.project_id}/global/images/{name}"
        if built.image_ref != image_path:
            raise ValueError("candidate image does not belong to the build attempt")
        image = self._owned(image_path, operation, attempt)
        disk = self._owned(f"{self.scope}/disks/{name}", operation, attempt)
        guest = self._owned(f"{self.scope}/instances/{name}", operation, attempt)
        if (
            str(image.get("id")) != built.image_id
            or image.get("status") != "READY"
            or str(image.get("sourceDiskId")) != built.source_disk_id
            or str(disk.get("id")) != built.source_disk_id
            or str(disk.get("sourceImageId")) != built.source_image_id
            or str(guest.get("id")) != built.builder_instance_id
        ):
            raise ValueError("candidate provider lineage changed after the builder receipt")
        self._guest(guest, f"{self.scope}/disks/{name}", status="TERMINATED")

    def verify_inputs(self, operation: UUID, attempt: UUID, evidence: dict[str, Any]) -> None:
        """The initial contained profile has one independently attached fixed disk."""
        inputs = InputEvidence.model_validate(evidence)
        if len(inputs.observations) != 1:
            raise ValueError("unsupported contained input set")
        self._scan(operation, attempt, inputs.observations[0])

    def verify_output(self, operation: UUID, attempt: UUID, evidence: dict[str, Any]) -> None:
        """Recheck the independent disk scan and both fresh functional-probe guests."""
        observed = OutputEvidence.model_validate(evidence)
        self._scan(operation, attempt, observed)
        for suffix, image_id, status in (
            ("boot", observed.image_id, "RUNNING"),
            ("probe", self.grant.scanner_image_id, "TERMINATED"),
        ):
            name = f"prep-{attempt.hex}-{suffix}"
            disk_path = f"{self.scope}/disks/{name}"
            disk = self._owned(disk_path, operation, attempt)
            guest = self._owned(f"{self.scope}/instances/{name}", operation, attempt)
            if str(disk.get("sourceImageId")) != image_id:
                raise ValueError("functional probe source identity changed")
            self._guest(guest, disk_path, status=status)

    def _scan(self, operation: UUID, attempt: UUID, observed: RawDiskObservation) -> None:
        name = "prep-" + attempt.hex
        data_path = f"{self.scope}/disks/{name}-data"
        scanner_path = f"{self.scope}/disks/{name}-scan"
        data = self._owned(data_path, operation, attempt)
        scanner = self._owned(scanner_path, operation, attempt)
        guest = self._owned(f"{self.scope}/instances/{name}-scan", operation, attempt)
        if (
            str(data.get("id")) != observed.disk_id
            or str(data.get("sourceImageId")) != observed.image_id
            or int(data.get("sizeGb", 0)) * 1024**3 != observed.size_bytes
            or str(scanner.get("sourceImageId")) != self.grant.scanner_image_id
        ):
            raise ValueError("independent scanner or data disk lineage changed")
        self._guest(guest, scanner_path, status="TERMINATED", data_disk=data_path)

    def _owned(self, path: str, operation: UUID, attempt: UUID) -> dict[str, Any]:
        value = self.reader.get(path)
        labels = value.get("labels", {})
        if labels.get("shifter-preparation") != operation.hex or labels.get("preparation-attempt") != attempt.hex:
            raise ValueError("preparation provider ownership changed")
        return value

    def _guest(
        self,
        value: dict[str, Any],
        disk: str,
        *,
        status: str,
        data_disk: str | None = None,
    ) -> None:
        interfaces = value.get("networkInterfaces", [])
        disks = value.get("disks", [])
        if not _isolated_guest(value, interfaces, disks, status, disk, self.grant.subnetwork, bool(data_disk)):
            raise ValueError("preparation guest isolation or terminal state changed")
        if data_disk and (not _same_ref(disks[1].get("source"), data_disk) or disks[1].get("mode") != "READ_ONLY"):
            raise ValueError("preparation scanner attachment changed")


def _isolated_guest(
    value: dict[str, Any],
    interfaces: list[dict[str, Any]],
    disks: list[dict[str, Any]],
    status: str,
    disk: str,
    subnetwork: str,
    has_data_disk: bool,
) -> bool:
    """Handle isolated guest."""
    return (
        value.get("status") == status
        and not value.get("serviceAccounts")
        and len(interfaces) == 1
        and not interfaces[0].get("accessConfigs")
        and not interfaces[0].get("ipv6AccessConfigs")
        and _same_ref(interfaces[0].get("subnetwork"), subnetwork)
        and len(disks) == (2 if has_data_disk else 1)
        and disks[0].get("boot") is True
        and _same_ref(disks[0].get("source"), disk)
    )


def _same_ref(actual: object, expected: str) -> bool:
    """Handle same ref."""
    if not isinstance(actual, str):
        return False
    for prefix in ("https://www.googleapis.com/compute/v1/", "https://compute.googleapis.com/compute/v1/"):
        actual = actual.removeprefix(prefix)
    return actual == expected
