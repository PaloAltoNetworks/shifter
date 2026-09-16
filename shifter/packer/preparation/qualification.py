"""Exercise the real GCE profile without granting inventory admission authority."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from preparation.cleanup import cleanup_operation
from preparation.gce_boot import verify_boot
from preparation.gce_build import build_image
from preparation.gce_probe import probe_from_guest
from preparation.gce_verify import scan_image


def qualify(
    client: Callable[[], Any],
    request: dict[str, Any],
    context: dict[str, bytes],
    record: Callable[[str, dict[str, Any]], None],
    *,
    build_and_output_only: bool = False,
) -> None:
    """Qualify cloud construction/inspection/probing, always cleaning up afterward.

    This runner neither validates a public locked-input manifest nor admits an
    artifact. Its actual measurements are inputs to that subsequent qualification.
    Every synchronous cloud action finishes before cleanup begins.
    """
    operation_id = UUID(request["operation_id"])
    attempts: list[UUID] = []

    def attempt(kind: str, **overrides: Any) -> dict[str, Any]:
        """Handle attempt."""
        identity = uuid4()
        attempts.append(identity)
        record("attempt", {"attempt_id": str(identity), "kind": kind})
        return dict(request, attempt_id=str(identity), **overrides)

    try:
        if not build_and_output_only:
            record("input", scan_image(client(), attempt("verify-inputs"), context, verify_output=False))
        raw = attempt("build")
        raw.pop("scanner_image")
        raw.pop("scanner_image_id")
        built = build_image(client(), raw, context)
        record("build", built)
        candidate = {"image_ref": built["image_ref"], "image_id": built["image_id"]}
        output_request = attempt("verify-output", **candidate)
        record("output", scan_image(client(), output_request, context, verify_output=True))
        boot_request = dict(output_request)
        scanner_ref = boot_request.pop("scanner_image")
        scanner_id = boot_request.pop("scanner_image_id")
        probe_request = dict(boot_request, image_ref=scanner_ref, image_id=scanner_id)

        def probe(host: str, nonce: str) -> bool:
            """Handle probe."""
            return probe_from_guest(client(), probe_request, context["verify_boot.py"], host, nonce)

        record("boot", verify_boot(client(), boot_request, probe))
    finally:
        record("cleanup", cleanup_operation(client(), operation_id, attempts))
