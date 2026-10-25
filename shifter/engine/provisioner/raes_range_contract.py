"""Closed backend admission and diagnostic classification for native lifecycle results."""

from shared.raes.operation_input import RaesOperationInput
from shared.range_instantiation_policy import (
    POLICY_DENIAL_CODE,
    PREREQUISITE_DENIAL_CODE,
    InstantiationPurpose,
    evaluate_gcp_backend_admission,
)

from cloud.exceptions import CloudError
from executors.base import GuestReadinessTimeoutError
from raes_content_payload import RaesContentDeliveryError
from raes_gcp_network_allocation import RaesRealizationError

_FAILURE_REASON_CODE = "cloud_operation_failed"
_INVALID_STATE_REASON_CODE = "invalid_state"
_TIMEOUT_REASON_CODE = "cloud_timeout"


def _binding_error(message: str, code: str) -> CloudError:
    """Return an authored lifecycle failure with a stable classification."""
    error = CloudError(message)
    error.code = code
    return error


def _require_gce_live_fire_binding(operation_input: RaesOperationInput) -> str:
    """Validate the projected ownership/purpose pair for a normal RAES range."""
    raw_backend = operation_input.range_backend
    if not raw_backend:
        raise _binding_error(
            "RAES GCP range ownership binding is missing",
            PREREQUISITE_DENIAL_CODE,
        )
    try:
        purpose = InstantiationPurpose(operation_input.instantiation_purpose)
    except (TypeError, ValueError):
        raise _binding_error(
            "RAES GCP range instantiation purpose is missing or invalid",
            PREREQUISITE_DENIAL_CODE,
        ) from None
    if purpose is not InstantiationPurpose.LIVE_FIRE:
        raise _binding_error(
            "Normal RAES GCP ranges require the live_fire instantiation purpose",
            POLICY_DENIAL_CODE,
        )
    admission = evaluate_gcp_backend_admission(raw_backend, None, purpose)
    if not admission.admitted:
        raise _binding_error(admission.reason, admission.code)
    return admission.backend


#: Failures whose messages are authored text, safe to report: RAES realization
#: errors raised by this module, content-delivery errors, which carry only
#: constant messages naming the failing step (enforced by
#: test_content_delivery_errors_carry_only_authored_text), and guest readiness
#: timeouts, which carry only the wait and a fixed probe-failure category.
_AUTHORED_FAILURES: tuple[tuple[type[BaseException], str, str], ...] = (
    (RaesRealizationError, _INVALID_STATE_REASON_CODE, "{stage}: {message}"),
    (RaesContentDeliveryError, _FAILURE_REASON_CODE, "{stage} failed: {message}"),
    (GuestReadinessTimeoutError, _TIMEOUT_REASON_CODE, "{stage} timed out: {message}"),
)


def _classify_failure(exc: BaseException, stage: str) -> tuple[str, str]:
    """Map a realization failure onto an authored reason code and diagnostic.

    The exception *message* must never cross this boundary. RAES failures travel
    through cloud-provider, storage, content-delivery, and guest-realization
    code whose messages can carry provider response bodies, resource ids,
    storage references, signed URLs, and guest output; the result inbox is a
    durable channel readable by anyone permitted to inspect diagnostics, and an
    authenticated range author can deliberately provoke failures to populate it.
    Truncation bounds size, not confidentiality, and ``safe_log_value`` is
    injection defence, not redaction (ADR-043-R5).

    The exception *type* is a code identifier rather than runtime data, so it
    crosses to keep the channel useful for triage. Full context stays in the
    provisioner's own logs, where the raw error is re-raised to the task runner.
    """
    for error_type, reason_code, template in _AUTHORED_FAILURES:
        if isinstance(exc, error_type):
            return reason_code, template.format(stage=stage, message=exc)
    if isinstance(exc, TimeoutError):
        return _TIMEOUT_REASON_CODE, f"{stage} timed out ({type(exc).__name__})"
    return _FAILURE_REASON_CODE, f"{stage} failed ({type(exc).__name__})"
