"""Explicit operator CLI for live profile qualification in a disposable network."""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404  # NOSONAR -- Bandit requires its suppression inline.
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from preparation.compute import ComputeClient
from preparation.context import load_context
from preparation.qualification import qualify


class GcloudSession:
    """Use the named gcloud account without copying its credentials to a guest.

    Token output stays in memory. Normal dispatched workers use Workload Identity
    through ComputeClient's ADC path instead of this operator-only transport.
    """

    def __init__(self, account: str) -> None:
        self.account = account
        self.session = requests.Session()

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        result = subprocess.run(  # noqa: S603  # nosec B603 B607
            ["gcloud", "auth", "print-access-token", f"--account={self.account}", "--quiet"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode or not result.stdout.strip():
            raise RuntimeError("qualification account authentication failed")
        return self.session.request(method, url, headers={"Authorization": "Bearer " + result.stdout.strip()}, **kwargs)


def main() -> None:
    """Handle main."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "account",
        "project",
        "zone",
        "subnetwork",
        "base-image",
        "base-image-id",
        "scanner-image",
        "scanner-image-id",
        "context-digest",
        "record",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--context-root", type=Path, default=Path(__file__).with_name("contexts"))
    parser.add_argument("--specification-id", default="http-smoke")
    parser.add_argument(
        "--build-and-output-only",
        action="store_true",
        help="Development diagnostic: omit input measurement and make no input qualification claim",
    )
    args = parser.parse_args()
    context = load_context(args.context_root, args.specification_id, args.context_digest)
    requested_output = Path(args.record)
    if requested_output.parent != Path() or requested_output.name in {"", ".", ".."}:
        raise ValueError("record must be a new filename in the current directory")
    output = Path.cwd() / requested_output.name
    # A qualification never overwrites an earlier receipt or private source file.
    with output.open("x", encoding="utf-8") as stream:
        operation_id = str(uuid4())
        request = {
            "operation_id": operation_id,
            "project_id": args.project,
            "zone": args.zone,
            "subnetwork": args.subnetwork,
            "image_ref": args.base_image,
            "image_id": args.base_image_id,
            "scanner_image": args.scanner_image,
            "scanner_image_id": args.scanner_image_id,
            "max_disk_gb": 40,
            "max_duration_seconds": 1200,
        }

        def record(phase: str, evidence: dict[str, Any]) -> None:
            """Handle record."""
            value = {"operation_id": operation_id, "phase": phase, "at": datetime.now(UTC).isoformat(), **evidence}
            stream.write(json.dumps(value, sort_keys=True) + "\n")
            stream.flush()
            print(f"{phase}: recorded", flush=True)  # noqa: T201 - bounded operator progress

        record(
            "started",
            {
                "request": request,
                "context_digest": args.context_digest,
                "build_and_output_only": args.build_and_output_only,
            },
        )
        session = GcloudSession(args.account)
        qualify(
            lambda: ComputeClient(args.project, args.zone, 1200, session=session),
            request,
            context,
            record,
            build_and_output_only=args.build_and_output_only,
        )


if __name__ == "__main__":
    main()
