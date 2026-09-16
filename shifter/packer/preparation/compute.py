"""Bounded GCE REST operations for the contained preparation worker.

Credentials are resolved only when an explicitly dispatched worker constructs
the client. No project is inferred from local gcloud state. Provider URLs and
error bodies never become instructions or operator-facing diagnostics.
"""

from __future__ import annotations

import base64
import json
import re
import time
from collections.abc import Iterator
from typing import Any, Protocol
from uuid import UUID, uuid5

from preparation.scan_guest import FAILURE_CODES

_BASE = "https://compute.googleapis.com/compute/v1/"
_PROJECT = r"[a-z][a-z0-9-]{4,61}[a-z0-9]"
_RESOURCE = r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_INVALID_SCANNER_RECEIPT = "invalid preparation scanner receipt"


class ProviderResponse(Protocol):
    """Bounded response surface consumed by the Compute client."""

    status_code: int

    def iter_content(self, chunk_size: int) -> Iterator[bytes]: ...
    def close(self) -> None: ...


class ProviderSession(Protocol):
    """Minimal authorized HTTP session needed by the Compute client."""

    def request(self, method: str, url: str, **kwargs: Any) -> ProviderResponse: ...


class ProviderRequestError(RuntimeError):
    """Bounded transport status, with no provider error body or private input."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"preparation provider request failed (HTTP {status})")


def reference_matches(observed: object, expected: str) -> bool:
    """Accept only canonical relative or documented Google Compute resource links."""
    return observed in (expected, _BASE + expected, "https://www.googleapis.com/compute/v1/" + expected)


class ComputeClient:
    """A single worker deadline bounds every provider request and poll."""

    def __init__(
        self,
        project: str,
        zone: str,
        duration: int,
        *,
        session: ProviderSession | None = None,
    ) -> None:
        if not re.fullmatch(_PROJECT, project) or not re.fullmatch(r"[a-z]+-[a-z]+\d-[a-z]", zone):
            raise ValueError("invalid preparation cloud scope")
        if type(duration) is not int or not 1 <= duration <= 7200:
            raise ValueError("invalid preparation worker duration")
        self.project = project
        self.zone = zone
        self.deadline = time.monotonic() + duration
        if session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            session = AuthorizedSession(credentials)
        self.session = session

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read one concrete resource with a bounded response and no redirects."""
        _, document = self._request("GET", path, params=params)
        return document

    def create(self, path: str, body: dict[str, Any], request_id: str) -> None:
        """Create or strictly observe the same immutable resource after a retry."""
        UUID(request_id)
        status, operation = self._request("POST", path, body=body, params={"requestId": request_id}, conflict=True)
        if status == 409:
            existing = self.get(f"{path}/{body['name']}")
            if not self._same_resource(existing, body):
                raise ValueError("preparation resource conflicts with its immutable ownership")
            return
        self._wait_operation(path.rsplit("/", 1)[0], operation)

    def list_owned(self, path: str, operation_id: UUID) -> list[dict[str, Any]]:
        """Bound enumeration and independently check the provider's label filter."""
        resources = []
        for resource in self._list_items(path, {"filter": f"labels.shifter-preparation = {operation_id.hex}"}):
            if resource.get("labels", {}).get("shifter-preparation") == operation_id.hex:
                resources.append(resource)
                if len(resources) > 256:
                    raise ValueError("preparation resource count exceeds its bound")
        return resources

    def wait_for_attempt_operations(self, attempts: list[UUID]) -> None:
        """Quiesced workers can still have accepted provider creates in flight.

        Wait for their deterministic target names before enumerating cleanup
        resources. Failed provider operations are terminal too, not a reason to
        abandon cleanup. Other tenant workloads are never waited on or changed.
        """
        if len(attempts) > 128:
            raise ValueError("preparation attempt count exceeds its bound")
        stems = tuple(f"prep-{attempt.hex}" for attempt in attempts)
        scopes = (
            f"projects/{self.project}/zones/{self.zone}",
            f"projects/{self.project}/global",
        )
        for scope in scopes:
            for operation in self._list_items(f"{scope}/operations", {"filter": "status != DONE"}):
                if _attempt_target(operation.get("targetLink"), scope, stems):
                    self._wait_operation(scope, operation, allow_failure=True)

    def _list_items(self, path: str, query: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Bound every page and reject repeated continuation tokens."""
        params = dict(query, maxResults=100)
        seen_pages = set()
        for _ in range(32):
            document = self.get(path, params=params)
            yield from document.get("items", [])
            page = document.get("nextPageToken")
            if not page:
                return
            if not isinstance(page, str) or len(page) > 4096 or page in seen_pages:
                raise ValueError("invalid preparation resource pagination")
            seen_pages.add(page)
            params["pageToken"] = page
        raise ValueError("preparation resource pagination exceeds its bound")

    def delete_owned(self, path: str, resource_id: str, operation_id: UUID) -> None:
        """Recheck ownership and immutable ID immediately before deleting a resource.

        Callers must first quiesce every creator. Compute delete has no resource-ID
        precondition; IAM isolation and the controller's worker fence are required.
        """
        status, resource = self._request("GET", path, missing=True)
        if status == 404:
            return
        if (
            str(resource.get("id")) != resource_id
            or resource.get("labels", {}).get("shifter-preparation") != operation_id.hex
        ):
            raise ValueError("preparation cleanup ownership changed")
        status, operation = self._request(
            "DELETE", path, params={"requestId": str(uuid5(operation_id, f"delete:{path}:{resource_id}"))}, missing=True
        )
        if status != 404:
            self._wait_operation(path.rsplit("/", 2)[0], operation)

    def clear_metadata(self, path: str) -> None:
        """Erase private startup material using the current metadata fingerprint."""
        resource = self.get(path)
        fingerprint = resource.get("metadata", {}).get("fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("preparation metadata fingerprint is unavailable")
        _, operation = self._request("POST", f"{path}/setMetadata", body={"fingerprint": fingerprint, "items": []})
        self._wait_operation(path.rsplit("/", 2)[0], operation)

    def attach_readonly(self, path: str, disk: str, request_id: str) -> None:
        """Attach data only after the scanner's root filesystem has booted."""
        UUID(request_id)
        if not re.fullmatch(rf"projects/{self.project}/zones/{self.zone}/disks/{_RESOURCE}", disk):
            raise ValueError("scanner disk is outside the granted scope")
        body = {
            "boot": False,
            "autoDelete": False,
            "type": "PERSISTENT",
            "source": disk,
            "mode": "READ_ONLY",
            "deviceName": "shifter-candidate",
        }
        attachments = self.get(path).get("disks", [])
        if len(attachments) != 1:
            if len(attachments) == 2 and _same_attachment(attachments[1], body):
                return
            raise ValueError("scanner has a conflicting candidate attachment")
        _, operation = self._request("POST", f"{path}/attachDisk", body=body, params={"requestId": request_id})
        self._wait_operation(path.rsplit("/", 2)[0], operation)

    def wait_for_ready(self, instance_path: str, nonce: str) -> None:
        """Wait for trusted startup before introducing duplicate filesystem IDs."""
        UUID(nonce)
        if self._wait_receipt(instance_path, f"SHIFTER_PREPARATION_READY:{nonce}", stopped=False):
            raise ValueError("invalid scanner readiness receipt")

    def wait_for_build(self, instance_path: str, nonce: str) -> None:
        """Require an attempt-bound completion marker and a stopped build VM."""
        UUID(nonce)
        if self._wait_receipt(instance_path, f"SHIFTER_PREPARATION_DONE:{nonce}"):
            raise ValueError("invalid preparation build receipt")

    def wait_for_observation(self, instance_path: str, nonce: str) -> dict[str, Any]:
        """Read bounded scanner evidence, without exposing guest console content."""
        UUID(nonce)
        payload = self._wait_receipt(instance_path, f"SHIFTER_PREPARATION_OBSERVATION:{nonce}:")
        try:
            observation = json.loads(base64.b64decode(payload, validate=True))
        except ValueError as exc:
            raise ValueError(_INVALID_SCANNER_RECEIPT) from exc
        if not isinstance(observation, dict):
            raise ValueError(_INVALID_SCANNER_RECEIPT)
        if "failure_code" in observation:
            code = observation["failure_code"]
            if set(observation) != {"failure_code"} or not isinstance(code, str) or code not in FAILURE_CODES:
                raise ValueError(_INVALID_SCANNER_RECEIPT)
            raise RuntimeError(f"preparation scanner failed: {code}")
        return observation

    def _wait_receipt(self, instance_path: str, prefix: str, *, stopped: bool = True) -> str:
        """Retain only one nonce-bound receipt and a bounded partial console line."""
        offset = 0
        receipt = None
        tail = ""
        while True:
            try:
                serial = self.get(f"{instance_path}/serialPort", params={"port": 1, "start": offset})
            except ProviderRequestError as exc:
                # The serial endpoint may disappear as the VM powers off. A
                # receipt already read from this attempt is retained, but only
                # successful provider readback of a stopped VM can complete it.
                if (
                    exc.status in {400, 404, 503}
                    and receipt is not None
                    and self.get(instance_path).get("status") == "TERMINATED"
                ):
                    return receipt
                raise
            text = serial.get("contents", "")
            if not isinstance(text, str):
                raise ValueError("invalid preparation guest receipt")
            receipt, tail = _read_receipt_lines(tail + text, prefix, receipt)
            offset = int(serial.get("next", offset))
            instance = self.get(instance_path)
            completed = _completed_receipt(instance.get("status"), receipt, stopped=stopped)
            if completed is not None:
                return completed
            self._pause()

    def _wait_operation(self, scope: str, operation: dict[str, Any], *, allow_failure: bool = False) -> None:
        name = operation.get("name", "")
        if not isinstance(name, str) or not re.fullmatch(_RESOURCE, name):
            raise ValueError("invalid preparation provider operation")
        while operation.get("status") != "DONE":
            operation = self.get(f"{scope}/operations/{name}")
            if operation.get("status") != "DONE":
                self._pause()
        if operation.get("error") and not allow_failure:
            raise RuntimeError("preparation provider operation failed")

    def _pause(self) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("preparation worker deadline exceeded")
        time.sleep(min(2, remaining))

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        conflict: bool = False,
        missing: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        self._validate_path(method, path)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("preparation worker deadline exceeded")
        response = self.session.request(
            method,
            _BASE + path,
            json=body,
            params=params,
            timeout=min(30, remaining),
            allow_redirects=False,
            stream=True,
        )
        try:
            if response.status_code == 409 and conflict:
                return 409, {}
            if response.status_code == 404 and missing:
                return 404, {}
            if response.status_code != 200:
                raise ProviderRequestError(response.status_code)
            content = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                content.extend(chunk)
                if len(content) > _MAX_RESPONSE_BYTES:
                    raise ValueError("preparation provider response exceeds its bound")
            document = json.loads(content)
            if not isinstance(document, dict):
                raise ValueError("invalid preparation provider response")
            return response.status_code, document
        finally:
            response.close()

    def _validate_path(self, method: str, path: str) -> None:
        zonal = rf"projects/{self.project}/zones/{self.zone}/(?:instances|disks|operations)"
        global_scope = rf"projects/{self.project}/global/(?:images|operations)"
        suffix = rf"(?:/{_RESOURCE})?(?:/(?:setMetadata|serialPort|attachDisk))?"
        if re.fullmatch(rf"(?:{zonal}|{global_scope}){suffix}", path):
            return
        # Locked input images may belong to another publisher. Only concrete
        # image reads cross the granted project boundary.
        if method == "GET" and re.fullmatch(rf"projects/{_PROJECT}/global/images/{_RESOURCE}", path):
            return
        raise ValueError("preparation request is outside the granted cloud scope")

    @staticmethod
    def _same_resource(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
        """A 409 is not success unless the existing resource is the owned intent."""
        labels = desired.get("labels")
        if not labels or existing.get("labels") != labels or existing.get("name") != desired.get("name"):
            return False
        matches = False
        if "sourceDisk" in desired:
            matches = reference_matches(existing.get("sourceDisk"), desired["sourceDisk"])
        elif "sourceImage" in desired:
            matches = reference_matches(existing.get("sourceImage"), desired["sourceImage"]) and str(
                existing.get("sizeGb")
            ) == str(desired.get("sizeGb"))
        elif "disks" in desired:
            matches = _same_guest(existing, desired)
        return matches


def _attempt_target(target: object, scope: str, stems: tuple[str, ...]) -> bool:
    """Match complete deterministic names in the granted provider scope."""
    if not isinstance(target, str):
        return False
    relative = target.removeprefix(_BASE).removeprefix("https://www.googleapis.com/compute/v1/")
    for kind in ("instances", "disks", "images"):
        prefix = f"{scope}/{kind}/"
        if relative.startswith(prefix):
            name = relative.removeprefix(prefix)
            return bool(re.fullmatch(r"[a-z][a-z0-9-]{0,62}", name)) and any(
                name == stem or name.startswith(stem + "-") for stem in stems
            )
    return False


def _read_receipt_lines(text: str, prefix: str, receipt: str | None) -> tuple[str | None, str]:
    """Handle read receipt lines."""
    lines = text.split("\n")
    tail = lines.pop()
    if len(tail) > 96 * 1024:
        raise ValueError("preparation guest receipt exceeds its bound")
    for line in lines:
        if not line.startswith(prefix):
            continue
        value = line[len(prefix) :].rstrip("\r")
        if len(value) > 96 * 1024 or (receipt is not None and receipt != value):
            raise ValueError("preparation guest receipts conflict or exceed their bound")
        receipt = value
    return receipt, tail


def _completed_receipt(status: object, receipt: str | None, *, stopped: bool) -> str | None:
    """Handle completed receipt."""
    if not stopped and receipt is not None and status == "RUNNING":
        return receipt
    if status != "TERMINATED":
        return None
    if receipt is None:
        raise RuntimeError("preparation guest did not complete its work")
    return receipt


def _same_guest(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
    """Private metadata can be cleared only after the owned guest has stopped."""
    metadata = existing.get("metadata", {}).get("items")
    metadata_matches = metadata == desired.get("metadata", {}).get("items")
    if not metadata and existing.get("status") == "TERMINATED":
        metadata_matches = True
    networks = existing.get("networkInterfaces", [])
    return (
        not existing.get("serviceAccounts")
        and metadata_matches
        and reference_matches(existing.get("machineType"), desired["machineType"])
        and len(networks) == 1
        and not networks[0].get("accessConfigs")
        and not networks[0].get("ipv6AccessConfigs")
        and reference_matches(networks[0].get("subnetwork"), desired["networkInterfaces"][0]["subnetwork"])
        and _same_guest_disks(existing.get("disks", []), desired)
    )


def _same_guest_disks(observed: list[dict[str, Any]], desired: dict[str, Any]) -> bool:
    """Handle same guest disks."""
    wanted = _expected_guest_disks(observed, desired)
    if wanted is None:
        return False
    scope = desired["machineType"].split("/machineTypes/", 1)[0]
    return all(_same_guest_disk(actual, expected, scope) for actual, expected in zip(observed, wanted, strict=True))


def _expected_guest_disks(observed: list[dict[str, Any]], desired: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Return the normalized desired disk list when its scan attachment is owned."""
    wanted = desired["disks"]
    scope = desired["machineType"].split("/machineTypes/", 1)[0]
    attempt = desired.get("labels", {}).get("preparation-attempt", "")
    if (
        len(wanted) == 1
        and len(observed) == 2
        and re.fullmatch(r"[a-f0-9]{32}", attempt)
        and desired.get("name") == f"prep-{attempt}-scan"
    ):
        candidate = {
            "source": f"{scope}/disks/prep-{attempt}-data",
            "boot": False,
            "autoDelete": False,
            "mode": "READ_ONLY",
            "deviceName": "shifter-candidate",
        }
        if not _same_attachment(observed[1], candidate):
            return None
        wanted = [*wanted, candidate]
    if len(observed) != len(wanted):
        return None
    return wanted


def _same_guest_disk(actual: dict[str, Any], expected: dict[str, Any], scope: str) -> bool:
    """Compare one observed guest disk with its normalized desired attachment."""
    source = expected.get("source") or f"{scope}/disks/{expected['initializeParams']['diskName']}"
    return (
        reference_matches(actual.get("source"), source)
        and actual.get("boot", False) == expected.get("boot", False)
        and actual.get("autoDelete") == expected.get("autoDelete")
        and actual.get("mode", "READ_WRITE") == expected.get("mode", "READ_WRITE")
    )


def _same_attachment(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Handle same attachment."""
    return reference_matches(actual.get("source"), expected["source"]) and all(
        actual.get(key) == expected[key] for key in ("boot", "autoDelete", "mode", "deviceName")
    )
