"""NGFW Terraform operations for provisioning and deprovisioning.

This module provides the Terraform equivalent of the Pulumi NGFW operations.
It reports normalized state through the authoritative operation result inbox;
the Engine-owned applier writes domain state, audit, and range-event intent.
"""

import logging
import os
import time
from collections.abc import Mapping
from typing import Any, cast

from shared.operation_results import ResultStep

import terraform_runner
from cloud.exceptions import CloudProviderNotImplementedError
from config import resolve_cloud_provider
from events import (
    STATUS_FAILED,
    STATUS_PROVISIONING,
    STATUS_READY,
)
from executors.ngfw_executor import NGFWExecutor
from log_redact import safe_log_fingerprint, safe_log_value
from ngfw_polling import (
    NGFW_SSH_WAIT_TIMEOUT_DEFAULT,
    poll_for_serial_and_cert,
    poll_for_serial_number,
)
from ngfw_post_provision import _NgfwPostProvision, _short_circuit_local_dev_post_provision
from ngfw_runtime import update_instance_state
from ngfw_runtime_ops import run_ngfw_operation
from ngfw_terraform_cleanup import (
    _cleanup_ngfw_bootstrap_objects,
    _run_deprovision,
    _run_gdc_deprovision,
)
from ngfw_terraform_state import _build_provider_state, _build_tf_variables
from orchestrators.setup_orchestrator import SetupOrchestrator
from plans.base import SetupPlan
from plans.ngfw_provision import NGFWProvisionPlan
from provisioner_db_ngfw import get_ngfw_data_by_request_id

logger = logging.getLogger(__name__)

# ADR-043: map the argv tf-op to the canonical operation name for the authoritative result append.
_NGFW_TF_OP_TO_CANONICAL_OPERATION = {"up": "provision", "destroy": "deprovision"}


def _resolve_ngfw_post_provision(env: Mapping[str, str] | None = None) -> _NgfwPostProvision:
    """Select the NGFW post-provision strategy for the current environment.

    Resolves the local-dev-versus-production decision once, at the seam, rather
    than reading ``os.environ`` deep inside the provisioning flow. Local dev is
    signalled by ``DB_PASSWORD`` (the same password-auth boundary signal
    ``provisioner_db`` uses): PAN-OS is not reachable there, so the short-circuit
    adapter stands in for the live SSH bring-up while still emitting the
    ready-then-paused lifecycle transitions.
    """
    source = os.environ if env is None else env
    if source.get("DB_PASSWORD"):
        return _short_circuit_local_dev_post_provision
    return _run_pan_os_post_provision


def _run_ngfw_operation_for_provider(
    operation: str,
    request_id: str,
    instance_id: str,
    app_spec: dict[str, Any],
    sls_region: str,
    *,
    operation_id: str | None = None,
) -> None:
    """Dispatch the requested NGFW operation to the configured cloud provider path."""
    provider = resolve_cloud_provider()
    if operation not in ("up", "destroy"):
        raise ValueError(f"Unknown operation: {operation}")

    if provider == "gcp":
        if operation == "up":
            _run_gdc_provision(
                request_id,
                instance_id,
                app_spec,
                sls_region,
                post_provision=_resolve_ngfw_post_provision(),
                operation_id=operation_id,
            )
        else:
            _run_gdc_deprovision(request_id, operation_id=operation_id)
        return

    if provider == "aws":
        if operation == "up":
            _run_provision(
                request_id,
                instance_id,
                app_spec,
                sls_region,
                post_provision=_resolve_ngfw_post_provision(),
                operation_id=operation_id,
            )
        else:
            _run_deprovision(request_id, instance_id, operation_id=operation_id)
        return

    raise CloudProviderNotImplementedError(provider)


def _cleanup_failed_ngfw_provision(request_id: str, instance_id: str, app_spec: dict[str, Any]) -> None:
    """Best-effort cleanup for a failed NGFW provision operation."""
    logger.info("NGFW provision failed - attempting auto-cleanup...")
    provider = resolve_cloud_provider()
    if provider == "gcp":
        gdc_state = get_ngfw_data_by_request_id(request_id).get("state", {})
        if gdc_state:
            import gdc_vmseries_ngfw

            gdc_vmseries_ngfw.destroy_ngfw(gdc_state)
        return

    if provider == "aws":
        tf_vars = _build_tf_variables(request_id, instance_id, app_spec)
        terraform_runner.destroy_ngfw(
            request_id,
            terraform_runner.NGFW_MODULE_PATH,
            variables=tf_vars,
        )
        terraform_runner.cleanup_ngfw_state(request_id)
        return

    raise CloudProviderNotImplementedError(provider)


def run_ngfw_terraform(operation: str, request_id: str, *, operation_id: str | None = None) -> None:
    """Run NGFW Terraform operation (provision or deprovision).

    Args:
        operation: Either 'up' (provision) or 'destroy' (deprovision).
        request_id: UUID string of the Request.
        operation_id: ADR-043 canonical operation generation (#1834); ``None`` on local-dev runs.

    Raises:
        ValueError: If unknown operation or Request not found.
        Exception: If the Terraform operation fails.
    """
    logger.info(
        "run_ngfw_terraform: starting operation=%s request_id=%s",
        operation,
        request_id,
    )

    # Get NGFW data from database (same as Pulumi path)
    ngfw_data = get_ngfw_data_by_request_id(request_id)

    # Validate required fields
    instance_id = ngfw_data.get("instance_id")
    if not instance_id:
        raise ValueError(f"Missing instance_id in NGFW data for request {request_id}")

    app_id = ngfw_data.get("app_id")
    if not app_id:
        raise ValueError(f"Missing app_id in NGFW data for request {request_id}")

    app_spec: dict[str, Any] = ngfw_data.get("app_spec", {})

    try:
        sls_region = app_spec.get("sls_region", "americas")
        _run_ngfw_operation_for_provider(
            operation, request_id, instance_id, app_spec, sls_region, operation_id=operation_id
        )

    except Exception as e:
        error_msg = str(e)[:1000]
        logger.exception("NGFW Terraform operation failed: %s", error_msg)

        if operation == "up":
            try:
                _cleanup_failed_ngfw_provision(request_id, instance_id, app_spec)
            except Exception as cleanup_error:
                logger.warning("Auto-cleanup failed: %s", cleanup_error)

        # Update DB and emit failure event
        update_instance_state(
            request_id,
            STATUS_FAILED,
            step=ResultStep.NGFW_TERMINAL_FAILED,
            operation_id=operation_id,
            operation=_NGFW_TF_OP_TO_CANONICAL_OPERATION.get(operation),
            error_message=error_msg,
        )
        raise


def _build_ngfw_ssh_executor_from_output(output_data: dict[str, Any]) -> tuple[str, "NGFWExecutor"]:
    """Resolve `management_ip` + load the SSH key from Secrets Manager.

    Returns:
        (management_ip, NGFWExecutor) ready to talk to the device.

    Raises:
        RuntimeError: if either output field is missing or the secret fetch fails.
    """
    management_ip = output_data.get("management_ip")
    ssh_key_secret_arn = output_data.get("ssh_key_secret_arn")
    if not ssh_key_secret_arn:
        raise RuntimeError("NGFW provisioning output missing ssh_key_secret_arn")
    if not management_ip:
        raise RuntimeError("NGFW provisioning output missing management_ip")

    from cloud import get_secrets_store

    try:
        private_key = get_secrets_store().get_secret(ssh_key_secret_arn)
    except Exception as e:
        raise RuntimeError(f"Failed to retrieve SSH key from Secrets Manager: {e}") from e

    return management_ip, NGFWExecutor(private_key=private_key)


def _wait_for_ngfw_management_plane(output_data: dict[str, Any]) -> tuple[str, NGFWExecutor, str]:
    """Wait until PAN-OS management is reachable and returns its serial number."""
    management_ip, ssh_executor = _build_ngfw_ssh_executor_from_output(output_data)
    ssh_timeout = int(os.environ.get("NGFW_SSH_WAIT_TIMEOUT", NGFW_SSH_WAIT_TIMEOUT_DEFAULT))
    # management_ip is read from the same terraform output dict that carries the
    # SSH key secret ARN, so CodeQL taints it as sensitive; fingerprint it for
    # correlation without clear-text logging (py/clear-text-logging-sensitive-data).
    logger.info("Waiting for SSH on NGFW at %s...", safe_log_fingerprint(management_ip))
    ssh_executor.wait_for_agent(management_ip, timeout_seconds=ssh_timeout)

    logger.info("Polling for NGFW serial number (management plane readiness check)...")
    serial_number = poll_for_serial_number(
        ssh_executor=ssh_executor,
        host=management_ip,
        timeout_seconds=600,
        poll_interval=30,
    )
    logger.info("NGFW management plane ready, serial=%s", serial_number)

    logger.info("Waiting 30s for management plane to stabilize before configuration...")
    time.sleep(30)

    logger.info("Re-verifying SSH availability (allowing for potential NGFW reboot)...")
    ssh_executor.wait_for_agent(management_ip, timeout_seconds=600)
    logger.info("SSH confirmed available, proceeding with configuration...")
    return management_ip, ssh_executor, serial_number


def _run_ngfw_provision_plan(
    *,
    management_ip: str,
    ssh_executor: NGFWExecutor,
    output_data: dict[str, Any],
    sls_region: str,
) -> None:
    """Run the PAN-OS provisioning plan through the setup orchestrator."""
    context = {
        "ec2_instance_id": output_data.get("ec2_instance_id"),
        "management_ip": management_ip,
        "dataplane_ip": output_data.get("dataplane_ip"),
        "data_eni_id": output_data.get("data_eni_id"),
        "sls_region": sls_region,
    }

    orchestrator = SetupOrchestrator(executor=ssh_executor)
    provision_plan = cast(SetupPlan, NGFWProvisionPlan())
    logger.info("Running NGFW provision plan...")
    provision_result = orchestrator.orchestrate(
        instance_id=management_ip,
        plan=provision_plan,
        context=context,
    )
    if not provision_result.success:
        raise RuntimeError("NGFW post-infrastructure configuration failed")


def _fetch_ngfw_license_and_certificate_serial(
    *,
    request_id: str,
    management_ip: str,
    ssh_executor: NGFWExecutor,
    serial_number: str,
) -> str:
    """Fetch license data and return the latest certificate-backed serial."""
    logger.info("Fetching NGFW license: request_id=%s", request_id)
    license_result = ssh_executor.run_command(
        instance_id=management_ip,
        script="request license fetch",
        timeout_seconds=120,
    )
    if not license_result.success:
        logger.warning("License fetch returned non-success: %s", license_result.stderr)
    logger.info(
        "License fetch output: %s",
        license_result.stdout[:500] if license_result.stdout else "(empty)",
    )

    logger.info("Polling for valid device certificate: request_id=%s", request_id)
    poll_timeout = int(os.environ.get("NGFW_CERT_POLL_TIMEOUT", 2400))
    cert_serial = poll_for_serial_and_cert(
        ssh_executor=ssh_executor,
        host=management_ip,
        timeout_seconds=poll_timeout,
        poll_interval=30,
    )
    return cert_serial or serial_number


def _auto_stop_ngfw(request_id: str, *, operation_id: str | None = None) -> None:
    """Auto-stop the NGFW after readiness, without failing provisioning.

    The power-off is a step of the *provision* generation (ADR-043 phase 4
    preflight): it must not mint a second `stop` generation, so the owning
    operation is passed through explicitly.
    """
    logger.info("Auto-stopping NGFW: request_id=%s", request_id)
    try:
        run_ngfw_operation("stop", request_id, operation_id=operation_id, owning_operation="provision")
        logger.info("Auto-stop completed: request_id=%s", request_id)
    except Exception:
        logger.exception(
            "Auto-stop failed (non-fatal) - NGFW remains running: request_id=%s",
            request_id,
        )


def _run_pan_os_post_provision(
    *,
    request_id: str,
    instance_id: str,
    output_data: dict[str, Any],
    sls_region: str,
    operation_id: str | None = None,
) -> None:
    """Run shared live PAN-OS VM-Series post-boot configuration for any provider.

    The local-dev short-circuit is no longer branched here; the post-provision
    strategy is resolved at the operation seam (:func:`_resolve_ngfw_post_provision`)
    and this function is the production collaborator it returns.
    """
    logger.info("Running post-infrastructure NGFW configuration...")
    management_ip, ssh_executor, serial_number = _wait_for_ngfw_management_plane(output_data)
    _run_ngfw_provision_plan(
        management_ip=management_ip,
        ssh_executor=ssh_executor,
        output_data=output_data,
        sls_region=sls_region,
    )

    update_instance_state(
        request_id,
        STATUS_PROVISIONING,
        step=ResultStep.NGFW_PROVISION_INFRA,
        operation_id=operation_id,
        operation="provision",
        ngfw_state=_build_provider_state(output_data),
    )
    serial_number = _fetch_ngfw_license_and_certificate_serial(
        request_id=request_id,
        management_ip=management_ip,
        ssh_executor=ssh_executor,
        serial_number=serial_number,
    )

    update_instance_state(
        request_id,
        STATUS_READY,
        step=ResultStep.NGFW_PROVISION_READY,
        operation_id=operation_id,
        operation="provision",
    )
    bootstrap_cleanup_error = None
    try:
        _cleanup_ngfw_bootstrap_objects(instance_id)
    except Exception as e:
        logger.exception("NGFW bootstrap object cleanup failed: request_id=%s", request_id)
        bootstrap_cleanup_error = e
    logger.info(
        "NGFW provisioning complete, serial=%s: request_id=%s",
        safe_log_fingerprint(serial_number),
        safe_log_value(request_id),
    )

    _auto_stop_ngfw(request_id, operation_id=operation_id)

    if bootstrap_cleanup_error:
        raise RuntimeError("NGFW bootstrap object cleanup failed") from bootstrap_cleanup_error


def _run_provision(
    request_id: str,
    instance_id: str,
    app_spec: dict[str, Any],
    sls_region: str,
    *,
    post_provision: _NgfwPostProvision,
    operation_id: str | None = None,
) -> None:
    """Run Terraform apply for NGFW, then run the resolved post-provision strategy."""
    # Update local DB and emit provisioning status event
    update_instance_state(
        request_id,
        STATUS_PROVISIONING,
        step=ResultStep.NGFW_PROVISION_REQUESTED,
        operation_id=operation_id,
        operation="provision",
    )

    logger.info("Running terraform apply for NGFW...")

    tf_variables = _build_tf_variables(request_id, instance_id, app_spec)

    # Run Terraform apply and get outputs
    output_data = terraform_runner.apply_ngfw(request_id, tf_variables, terraform_runner.NGFW_MODULE_PATH)
    # Log correlation IDs + a field count, never the full output dict: NGFW
    # Terraform outputs carry a Secret Manager / Secrets Manager reference
    # (ssh_key_secret_id / ssh_key_secret_arn), so json.dumps-ing the whole dict
    # logs it in clear text (CodeQL py/clear-text-logging) and would leak any
    # future sensitive output field.
    logger.info(
        "Terraform apply complete for NGFW: request_id=%s instance_id=%s (%d output fields)",
        safe_log_value(request_id),
        safe_log_value(instance_id),
        len(output_data),
    )

    post_provision(
        request_id=request_id,
        instance_id=instance_id,
        output_data=output_data,
        sls_region=sls_region,
        operation_id=operation_id,
    )


def _run_gdc_provision(
    request_id: str,
    instance_id: str,
    app_spec: dict[str, Any],
    sls_region: str,
    *,
    post_provision: _NgfwPostProvision,
    operation_id: str | None = None,
) -> None:
    """Create a Palo Alto VM-Series firewall on GDC VM Runtime, then run post-provision."""
    import gdc_vmseries_ngfw

    update_instance_state(
        request_id,
        STATUS_PROVISIONING,
        step=ResultStep.NGFW_PROVISION_REQUESTED,
        operation_id=operation_id,
        operation="provision",
    )

    logger.info("Running GDC VM Runtime provisioning for Palo Alto VM-Series...")
    output_data = gdc_vmseries_ngfw.apply_ngfw(
        request_id=request_id,
        instance_id=instance_id,
        app_spec=app_spec,
    )
    # See _run_provision: log non-sensitive correlation only, not the dict.
    logger.info(
        "GDC VM-Series provisioning applied: request_id=%s instance_id=%s (%d output fields)",
        safe_log_value(request_id),
        safe_log_value(instance_id),
        len(output_data),
    )

    # Persist the VM Runtime state before waiting on PAN-OS so failure cleanup has enough context.
    update_instance_state(
        request_id,
        STATUS_PROVISIONING,
        step=ResultStep.NGFW_PROVISION_INFRA,
        operation_id=operation_id,
        operation="provision",
        ngfw_state=_build_provider_state(output_data),
    )

    post_provision(
        request_id=request_id,
        instance_id=instance_id,
        output_data=output_data,
        sls_region=sls_region,
        operation_id=operation_id,
    )
