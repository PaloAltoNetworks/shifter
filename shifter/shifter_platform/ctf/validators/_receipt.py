"""Authenticated, DNS-pinned transport for receipt-v1 validation."""

from __future__ import annotations

import contextlib
import http.client
import json
import logging
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from shared.cloud import get_secrets_store
from shared.receipt_validation import ReceiptValidationContext, VerifiedReceiptEvidence

from ._receipt_profiles import ReceiptVerifierProfile
from ._ssrf import _safe_parse_url

logger = logging.getLogger(__name__)

_RECEIPT_PROTOCOL = "shifter-receipt-v1"
_MAX_RECEIPT_BYTES = 4096
_INVALID_RESPONSE = object()
_REJECTED_RECEIPT = object()
_RESPONSE_KEYS = frozenset({"valid", "receipt_id", "issuer", "expires_at", "binding"})


@dataclass(frozen=True, slots=True)
class _ReceiptRequest:
    """Fully prepared request pinned to trusted destination addresses."""

    hostname: str
    port: int
    path: str
    body: bytes
    headers: dict[str, str]
    pinned_ips: tuple[str, ...]
    max_response_bytes: int


class _RequestUnavailable(Exception):
    """Internal fail-closed signal while preparing a provider request."""


def validate_receipt(
    submitted_receipt: str,
    profile: ReceiptVerifierProfile,
    context: ReceiptValidationContext,
) -> VerifiedReceiptEvidence | None:
    """Verify a receipt through one exact authenticated deployment profile."""
    started = time.monotonic()
    request = _prepare_request(submitted_receipt, profile, context, started)
    evidence = None
    if request is not None:
        raw = _request_pinned_addresses(request, profile, started)
        if raw is not None:
            evidence = _accepted_evidence(raw, profile, context)
        else:
            logger.warning("Receipt validator provider is unavailable")
    return evidence


def _prepare_request(
    submitted_receipt: object,
    profile: object,
    context: object,
    started: float,
) -> _ReceiptRequest | None:
    """Build an authenticated request only from valid profile-bound inputs."""
    if not _request_inputs_are_valid(submitted_receipt, profile, context):
        return None
    assert isinstance(submitted_receipt, str)
    assert isinstance(profile, ReceiptVerifierProfile)
    assert isinstance(context, ReceiptValidationContext)
    try:
        return _prepare_valid_request(submitted_receipt, profile, context, started)
    except _RequestUnavailable:
        return None


def _prepare_valid_request(
    submitted_receipt: str,
    profile: ReceiptVerifierProfile,
    context: ReceiptValidationContext,
    started: float,
) -> _ReceiptRequest:
    """Prepare a request after its public inputs have passed type validation."""
    parsed_tuple = _safe_parse_url(profile.endpoint_url)
    if parsed_tuple is None:
        raise _RequestUnavailable
    parsed, hostname, port = parsed_tuple
    service_auth = _load_service_auth(profile)
    if service_auth is None or _remaining(profile, started) <= 0:
        raise _RequestUnavailable
    body = _request_body(submitted_receipt, profile, context)
    if body is None:
        raise _RequestUnavailable
    from ctf import validators as public_validators

    pinned_ips = public_validators._resolve_target(hostname, port, context.challenge_id)
    if not pinned_ips or _remaining(profile, started) <= 0:
        raise _RequestUnavailable
    return _ReceiptRequest(
        hostname=hostname,
        port=port,
        path=parsed.path or "/",
        body=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "X-Service-Token": service_auth,
        },
        pinned_ips=tuple(pinned_ips[: profile.max_addresses]),
        max_response_bytes=profile.max_response_bytes,
    )


def _load_service_auth(profile: ReceiptVerifierProfile) -> str | None:
    """Load one bounded service credential without exposing its value."""
    try:
        service_auth = get_secrets_store().get_secret(profile.service_auth_secret_ref)
    except Exception:
        logger.warning("Receipt validator service authentication is unavailable")
        return None
    if not isinstance(service_auth, str) or not service_auth or len(service_auth) > 8192:
        return None
    return service_auth


def _request_body(
    submitted_receipt: str,
    profile: ReceiptVerifierProfile,
    context: ReceiptValidationContext,
) -> bytes | None:
    """Serialize the closed provider request inside its configured byte limit."""
    payload = {
        "contract": _RECEIPT_PROTOCOL,
        "provider_contract": profile.provider_contract,
        "audience": profile.audience,
        "receipt": submitted_receipt,
        "binding": _binding_payload(context),
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return body if len(body) <= profile.max_request_bytes else None


def _request_pinned_addresses(
    request: _ReceiptRequest,
    profile: ReceiptVerifierProfile,
    started: float,
) -> bytes | None:
    """Try each bounded pinned address until one provider responds."""
    raw = None
    for pinned_ip in request.pinned_ips:
        response = _request_one_address(
            request,
            pinned_ip=pinned_ip,
            timeout=_remaining(profile, started),
        )
        if response is not None:
            raw = response
            break
        if _remaining(profile, started) <= 0:
            break
    return raw


def _accepted_evidence(
    raw: bytes,
    profile: ReceiptVerifierProfile,
    context: ReceiptValidationContext,
) -> VerifiedReceiptEvidence | None:
    """Return exact verified evidence and reject all other provider responses."""
    parsed = _parse_evidence(raw, profile, context)
    evidence = parsed if isinstance(parsed, VerifiedReceiptEvidence) else None
    if parsed is _INVALID_RESPONSE:
        logger.warning("Receipt validator returned an invalid response")
    return evidence


def _request_inputs_are_valid(
    submitted_receipt: object,
    profile: object,
    context: object,
) -> bool:
    """Return whether input types, receipt text, and profile binding are exact."""
    return bool(
        isinstance(profile, ReceiptVerifierProfile)
        and isinstance(context, ReceiptValidationContext)
        and _receipt_text_is_valid(submitted_receipt)
        and _context_matches_profile(context, profile)
    )


def _receipt_text_is_valid(submitted_receipt: object) -> bool:
    """Require one bounded, canonical, single-line receipt string."""
    return bool(
        isinstance(submitted_receipt, str)
        and submitted_receipt
        and submitted_receipt == submitted_receipt.strip()
        and not any(character in submitted_receipt for character in ("\x00", "\r", "\n"))
        and len(submitted_receipt.encode("utf-8")) <= _MAX_RECEIPT_BYTES
    )


def _context_matches_profile(context: ReceiptValidationContext, profile: ReceiptVerifierProfile) -> bool:
    """Require the trusted context to select this exact closed profile."""
    context_values = (
        context.profile_id,
        context.deployment_id,
        context.provider_contract,
        context.issuer_id,
    )
    profile_values = (
        profile.profile_id,
        profile.deployment_id,
        profile.provider_contract,
        profile.issuer_id,
    )
    return bool(
        context_values == profile_values
        and context.key_mode in profile.allowed_key_modes
        and context.algorithm_id in profile.allowed_algorithms
        and context.objective_id in profile.permitted_objectives
    )


def _binding_payload(context: ReceiptValidationContext) -> dict[str, object]:
    """Project the exact provider-facing receipt binding payload."""
    return {
        "event": str(context.event_id),
        "participant": context.provider_participant_namespace,
        "challenge": str(context.challenge_id),
        "range_instance": context.provider_range_namespace,
        "materialization": str(context.materialization_id),
        "assignment_epoch": str(context.assignment_epoch),
        "registration_revision": str(context.registration_revision),
        "reset_generation": context.reset_generation,
        "objective": context.objective_id,
    }


def _remaining(profile: ReceiptVerifierProfile, started: float) -> float:
    """Return the non-negative request time budget."""
    return max(0.0, profile.total_timeout_seconds - (time.monotonic() - started))


def _request_one_address(
    request: _ReceiptRequest,
    *,
    pinned_ip: str,
    timeout: float,
) -> bytes | None:
    """Attempt one bounded pinned connection and return one complete body."""
    raw = None
    conn: http.client.HTTPSConnection | None = None
    try:
        if timeout <= 0:
            return raw
        tls_context = ssl.create_default_context()
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
        from ctf import validators as public_validators

        conn = public_validators._build_https_connection(
            hostname=request.hostname,
            pinned_ip=pinned_ip,
            port=request.port,
            timeout=timeout,
            context=tls_context,
        )
        conn.request("POST", request.path, body=request.body, headers=request.headers)
        response = conn.getresponse()
        if response.status == 200:
            response_body = response.read(request.max_response_bytes + 1)
            raw = response_body if len(response_body) <= request.max_response_bytes else b""
        else:
            raw = b""
    except (OSError, http.client.HTTPException):
        raw = None
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
    return raw


def _parse_evidence(
    raw: bytes,
    profile: ReceiptVerifierProfile,
    context: ReceiptValidationContext,
) -> VerifiedReceiptEvidence | object:
    """Parse one exact response into immutable verified evidence."""
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (TypeError, ValueError):
        return _INVALID_RESPONSE
    if value == {"valid": False}:
        return _REJECTED_RECEIPT
    return _build_evidence(value, profile, context)


def _build_evidence(
    value: object,
    profile: ReceiptVerifierProfile,
    context: ReceiptValidationContext,
) -> VerifiedReceiptEvidence | object:
    """Build evidence from a structurally exact accepted-response object."""
    evidence: VerifiedReceiptEvidence | object = _INVALID_RESPONSE
    if _response_matches_contract(value, profile, context):
        assert isinstance(value, dict)
        receipt_id = value["receipt_id"]
        issuer_id = value["issuer"]
        expires_at = _parse_expiry(value["expires_at"], profile.max_receipt_ttl_seconds)
        if isinstance(receipt_id, str) and isinstance(issuer_id, str) and expires_at is not None:
            try:
                evidence = VerifiedReceiptEvidence(
                    receipt_id=receipt_id,
                    issuer_id=issuer_id,
                    expires_at=expires_at,
                    context=context,
                )
            except ValueError:
                evidence = _INVALID_RESPONSE
    return evidence


def _response_matches_contract(
    value: object,
    profile: ReceiptVerifierProfile,
    context: ReceiptValidationContext,
) -> bool:
    """Require an accepted response with exact keys, issuer, and binding."""
    return bool(
        isinstance(value, dict)
        and set(value) == _RESPONSE_KEYS
        and value.get("valid") is True
        and value.get("issuer") == profile.issuer_id
        and value.get("binding") == _binding_payload(context)
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Decode a JSON object while rejecting duplicate member names."""
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON member")
        value[key] = item
    return value


def _parse_expiry(value: object, max_ttl_seconds: int) -> datetime | None:
    """Parse a bounded, future, timezone-aware receipt expiration."""
    expires_at = None
    if isinstance(value, str) and len(value) <= 64:
        try:
            candidate = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            candidate = None
        now = timezone.now()
        if (
            candidate is not None
            and candidate.tzinfo is not None
            and now < candidate <= now + timedelta(seconds=max_ttl_seconds)
        ):
            expires_at = candidate
    return expires_at
