"""Deliver admitted model access over the generation's trusted guest channel."""

from __future__ import annotations

import base64
import json
import os
import re
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from importlib.resources import files
from typing import IO, Any, NoReturn
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
from uuid import UUID

from shared.model_access.credentials import ModelEnrollment
from shared.model_access.guest_binding import ModelGuestBinding
from shared.model_access.messages import strict_json
from shared.model_access.network import broker_egress_destination
from shared.model_access.workload_identity import workload_assertion

from executors.factory import build_guest_execution_context
from provisioner_db_operation_input import RaesOperationRun
from raes_plan import RaesPlan

_ORIGIN = re.compile(r"https://[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?(?::[1-9]\d{0,4})?", flags=re.ASCII)


class ModelEnrollmentError(RuntimeError):
    """Only a closed diagnostic may leave this credential-bearing boundary."""


class _NoRedirect(HTTPRedirectHandler):
    """Reject redirect attempts at the enrollment credential boundary."""

    def redirect_request(
        self, req: Request, fp: IO[bytes], code: int, msg: str, headers: Message, newurl: str
    ) -> NoReturn:
        raise ValueError("Enrollment redirect rejected")


@dataclass(frozen=True)
class EnrollmentDelivery:
    """Admitted guest targets and trusted private enrollment coordinates."""

    operation_id: UUID
    bindings: tuple[ModelGuestBinding, ...]
    provider: str
    region: str
    control_url: str
    audience: str
    broker_url: str
    ca_pem: str
    broker_vip: str = ""

    def gce_egress_capability(self) -> dict[str, object]:
        """Only an admitted enrollment opens the exact applied destination."""
        if self.provider != "gcp":
            raise ModelEnrollmentError("GCE broker egress requires the GCP provider")
        capability = {"contract_version": "model-broker-egress/v1", "vip": self.broker_vip, "port": 443}
        broker_egress_destination(capability, expected_vip=self.broker_vip, egress_mode="status-quo")
        return capability

    def execute(self, _plan: RaesPlan, instances: list[dict[str, Any]]) -> None:
        try:
            outputs = {instance["uuid"]: instance for instance in instances}
            if len(outputs) != len(instances) or any(
                f"{binding.target_address}#0" not in outputs for binding in self.bindings
            ):
                raise ValueError
            for binding in self.bindings:
                self._deliver(binding, outputs[f"{binding.target_address}#0"])
        except Exception:
            raise ModelEnrollmentError("Guest model enrollment failed") from None

    def _deliver(self, binding: ModelGuestBinding, instance: dict[str, Any]) -> None:
        """Send a one-use capability through private SSH stdin with pinned host identity."""
        execution = build_guest_execution_context(instance, os_type="linux", role="raes-node")
        try:
            # SSM stores command payloads. Enrollment requires a private
            # stdin channel and verified SSH host identity instead.
            if execution.transport_name != "ssh" or not execution.wait_for_ready(timeout_seconds=60):
                raise ValueError
            enrollment = self._issue(binding.allocation_id)
            if enrollment.expires_at <= datetime.now(UTC):
                raise ValueError
            payload = json.dumps(
                {
                    "broker_url": self.broker_url,
                    "ca_pem": self.ca_pem,
                    "enrollment_token": enrollment.enrollment_token.get_secret_value(),
                }
            )
            result = execution.executor.run_command(
                execution.target,
                _install_script(binding.workload_role),
                stdin_input=payload,
                timeout_seconds=30,
                document_name=execution.document_name,
            )
            if not result.success or result.exit_code != 0:
                raise ValueError
        finally:
            execution.close()

    def _issue(self, allocation_id: UUID) -> ModelEnrollment:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_verify_locations(cadata=self.ca_pem)
        opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), _NoRedirect())
        identity = workload_assertion(
            provider=self.provider,
            region=self.region,
            audience=f"{self.audience}:enroll:{self.operation_id}",
        )
        if not _ORIGIN.fullmatch(self.control_url):
            raise ValueError
        request = Request(  # noqa: S310  # Closed HTTPS origin, no redirects or environment proxies.
            self.control_url + "/control/v1/enroll",
            data=json.dumps({"allocation_id": str(allocation_id), "operation_id": str(self.operation_id)}).encode(),
            headers={"Content-Type": "application/json", "Authorization": identity},
            method="POST",
        )
        with opener.open(request, timeout=5) as response:
            if response.status != 200:
                raise ValueError
            return ModelEnrollment.model_validate(strict_json(response.read(8193), limit=8192))


def _load_guest_ca() -> str:
    """Validate the bounded deployment-owned TLS trust bundle before guest delivery."""
    ca = base64.b64decode(os.environ["MODEL_ENROLLMENT_CA_PEM_B64"], validate=True).decode("ascii")
    if len(ca) > 16384:
        raise ValueError
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cadata=ca)
    return ca


def load_model_enrollment(run: RaesOperationRun) -> EnrollmentDelivery | None:
    """Validate execution coordinates before any cloud mutation; tokens come later."""
    if not run.input.model_enrollments:
        return None
    try:
        ca = _load_guest_ca()
        control, broker = os.environ["MODEL_ENROLLMENT_CONTROL_URL"], os.environ["MODEL_BROKER_GUEST_URL"]
        if not _ORIGIN.fullmatch(control) or not _ORIGIN.fullmatch(broker):
            raise ValueError
        provider = os.environ["CLOUD_PROVIDER"]
        if provider not in {"aws", "gcp"}:
            raise ValueError
        region = os.environ.get("AWS_REGION" if provider == "aws" else "CLOUD_REGION", "")
        if provider == "aws" and not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", region, flags=re.ASCII):
            raise ValueError
        delivery = EnrollmentDelivery(
            operation_id=UUID(run.operation_id),
            bindings=run.input.model_enrollments,
            provider=provider,
            region=region,
            control_url=control,
            audience="shifter-model-control",
            broker_url=broker,
            ca_pem=ca,
            broker_vip=os.environ.get("MODEL_BROKER_GUEST_VIP", "") if provider == "gcp" else "",
        )
        if provider == "gcp":
            delivery.gce_egress_capability()
        return delivery
    except Exception:
        raise ModelEnrollmentError("Guest model enrollment configuration is unavailable") from None


def _install_script(role: str) -> str:
    """Load the generic enrollment installer for a validated workload role."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", role):
        raise ValueError
    encoded = base64.b64encode(files("shifter_adapter_sdk").joinpath("model_access.py").read_bytes()).decode("ascii")
    directory = f"/run/shifter-model-access/{role}"
    # The script is public; the short-lived token travels on a distinct stdin
    # channel. Runtime paths are root-owned tmpfs, never image or disk state.
    return (
        "set -euo pipefail\numask 077\n"
        'test "$(findmnt -n -o FSTYPE -T /run)" = tmpfs\n'
        "test ! -L /run/shifter-model-access\n"
        "install -d -m 0700 -o root -g root /run/shifter-model-access\n"
        f"test ! -L {directory}\ninstall -d -m 0700 -o root -g root {directory}\n"
        f"printf %s '{encoded}' | base64 -d > {directory}/helper.py\n"
        f"python3 {directory}/helper.py enroll --state {directory}/session.json >/dev/null 2>&1\n"
    )
