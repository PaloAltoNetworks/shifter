"""CTF flag hashing and verification.

Hashing (bcrypt with a PBKDF2-SHA256 fallback), per-flag-type verification
(static/regex/programmable/http), and the ``verify_flag`` /
``verify_single_flag`` entry points used by the submission service. Also
houses the ``validator_config`` validation for programmable/http flags,
shared with ``_flag_crud`` at flag-write time.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from ctf.exceptions import CTFValidationError
from ctf.models import CTFChallenge, CTFFlag
from ctf.services.challenge._receipt_context import accept_registered_evidence as _accept_registered_evidence

if TYPE_CHECKING:
    from shared.receipt_validation import ReceiptSubmissionContext, ReceiptValidationContext, VerifiedReceiptEvidence

logger = logging.getLogger(__name__)

# Use bcrypt for flag hashing (secure and includes salt)
try:
    import bcrypt

    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    logger.warning("bcrypt not available, using SHA256 for flag hashing (less secure)")


def hash_flag(flag: str, case_sensitive: bool = True) -> str:
    """Hash a flag for secure storage.

    Uses bcrypt if available, falls back to PBKDF2-SHA256.

    Args:
        flag: The plaintext flag value.
        case_sensitive: If False, normalize to lowercase before hashing.

    Returns:
        Hashed flag string for storage.
    """
    value = flag if case_sensitive else flag.lower()
    if BCRYPT_AVAILABLE:
        return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    else:
        salt = secrets.token_hex(16)
        hash_value = hashlib.pbkdf2_hmac(
            "sha256", value.encode("utf-8"), salt.encode("utf-8"), iterations=600_000
        ).hex()
        return f"pbkdf2:{salt}:{hash_value}"


def _verify_bcrypt(submitted_flag: str, stored_hash: str, context_id: UUID) -> bool:
    """Verify a submitted flag against a bcrypt hash (``$2`` prefix)."""
    try:
        return bcrypt.checkpw(
            submitted_flag.encode("utf-8"),
            stored_hash.encode("utf-8"),
        )
    except Exception as e:
        logger.exception("Flag verification error for %s: %s", context_id, e)
        return False


def _verify_pbkdf2(submitted_flag: str, stored_hash: str, context_id: UUID) -> bool:
    """Verify a submitted flag against a ``pbkdf2:<salt>:<hash>`` digest."""
    parts = stored_hash.split(":", 2)
    if len(parts) != 3:
        logger.error("Invalid hash format for %s", context_id)
        return False
    _, salt, expected_hash = parts
    actual_hash = hashlib.pbkdf2_hmac(
        "sha256", submitted_flag.encode("utf-8"), salt.encode("utf-8"), iterations=600_000
    ).hex()
    return secrets.compare_digest(actual_hash, expected_hash)


def _verify_legacy_sha256(submitted_flag: str, stored_hash: str, context_id: UUID) -> bool:
    """Verify a submitted flag against a legacy ``sha256:<salt>:<hash>`` digest.

    Kept for backward compatibility with hashes created before the PBKDF2
    migration. New flags always use bcrypt or PBKDF2 (see ``hash_flag()``).
    """
    parts = stored_hash.split(":", 2)
    if len(parts) != 3:
        logger.error("Invalid hash format for %s", context_id)
        return False
    _, salt, expected_hash = parts
    actual_hash = hashlib.sha256(  # NOSONAR — legacy compat, not for new hashes
        f"{salt}:{submitted_flag}".encode()
    ).hexdigest()
    return secrets.compare_digest(actual_hash, expected_hash)


def _verify_hash(submitted_flag: str, stored_hash: str, context_id: UUID) -> bool:
    """Verify a submitted flag against a stored hash.

    Args:
        submitted_flag: The flag value to check (already case-normalized if needed).
        stored_hash: The stored hash to compare against.
        context_id: ID for logging (challenge or flag ID).

    Returns:
        True if the flag matches the hash.
    """
    if BCRYPT_AVAILABLE and stored_hash.startswith("$2"):
        verifier = _verify_bcrypt
    elif stored_hash.startswith("pbkdf2:"):
        verifier = _verify_pbkdf2
    elif stored_hash.startswith("sha256:"):
        verifier = _verify_legacy_sha256
    else:
        logger.error("Unknown hash format for %s", context_id)
        return False
    return verifier(submitted_flag, stored_hash, context_id)


def _verify_regex_flag(flag_obj: CTFFlag, submitted_flag: str) -> bool:
    """Verify a submitted flag against a regex CTFFlag.

    The organizer-authored pattern (stored plaintext in ``flag_hash``) runs on a
    request worker against participant input, so evaluation is bounded and fails
    closed via ``ctf.services.regex_policy`` (issue #1183, ReDoS / CWE-1333).
    """
    from ctf.services.regex_policy import safe_fullmatch

    return safe_fullmatch(flag_obj.flag_hash, submitted_flag, case_sensitive=flag_obj.case_sensitive)


def _verify_programmable_flag(
    flag_obj: CTFFlag,
    submitted_flag: str,
    config: dict[str, Any],
    *,
    server_context: ReceiptSubmissionContext | None,
    evidence_collector: Callable[[VerifiedReceiptEvidence], None] | None,
    sensitive_submission_collector: Callable[[], None] | None,
) -> bool:
    """Verify a submitted flag against a programmable validator CTFFlag."""
    from ctf.validators import get_validator

    validator_name = config.get("validator_name", "")
    validator_func = get_validator(validator_name)
    is_valid = False
    if validator_func is None:
        logger.error("Unknown validator %r for flag %s", validator_name, flag_obj.id)
    else:
        is_valid = _invoke_programmable_validator(
            flag_obj,
            submitted_flag,
            config,
            validator_func,
            server_context=server_context,
            evidence_collector=evidence_collector,
            sensitive_submission_collector=sensitive_submission_collector,
        )
    return is_valid


def _invoke_programmable_validator(
    flag_obj: CTFFlag,
    submitted_flag: str,
    config: dict[str, Any],
    validator_func: Callable[..., object],
    *,
    server_context: ReceiptSubmissionContext | None,
    evidence_collector: Callable[[VerifiedReceiptEvidence], None] | None,
    sensitive_submission_collector: Callable[[], None] | None,
) -> bool:
    """Invoke a registered programmable validator and fail closed."""
    from ctf.validators import validator_supports_server_context

    context_capable = validator_supports_server_context(config.get("validator_name", ""))
    is_valid = False
    try:
        if context_capable:
            if sensitive_submission_collector is not None:
                sensitive_submission_collector()
            receipt_context = _resolve_registered_receipt_context(server_context, config.get("receipt"))
            if receipt_context is not None:
                contextual = cast("Callable[[str, dict[str, Any], ReceiptValidationContext], object]", validator_func)
                result = contextual(submitted_flag, config.get("params", {}), receipt_context)
                is_valid = _accept_registered_evidence(result, receipt_context, evidence_collector)
        else:
            legacy = cast("Callable[[str, dict[str, Any]], bool]", validator_func)
            is_valid = legacy(submitted_flag, config.get("params", {}))
    except Exception:
        if context_capable:
            logger.warning("Context-capable validator failed closed for flag %s", flag_obj.id)
        else:
            logger.exception("Validator failed for flag %s", flag_obj.id)
    return is_valid


def _verify_http_flag(
    flag_obj: CTFFlag,
    submitted_flag: str,
    config: dict[str, Any],
    *,
    server_context: ReceiptSubmissionContext | None,
    receipt_submission: str,
    evidence_collector: Callable[[VerifiedReceiptEvidence], None] | None,
    sensitive_submission_collector: Callable[[], None] | None,
) -> bool:
    """Verify a submitted flag against an HTTP validator CTFFlag."""
    from ctf.validators import validate_http

    try:
        if "protocol" in config:
            is_valid = _verify_receipt_http_flag(
                config,
                server_context,
                receipt_submission,
                evidence_collector,
                sensitive_submission_collector,
            )
        else:
            is_valid = validate_http(submitted_flag, config, flag_obj.challenge_id)
    except Exception:
        # Receipt/provider exceptions may carry URLs, claims, or credentials.
        # Preserve correlation by flag id and expose no nested exception text.
        logger.warning("HTTP validator failed closed for flag %s", flag_obj.id)
        is_valid = False
    return is_valid


def _verify_receipt_http_flag(
    config: dict[str, Any],
    server_context: ReceiptSubmissionContext | None,
    receipt_submission: str,
    evidence_collector: Callable[[VerifiedReceiptEvidence], None] | None,
    sensitive_submission_collector: Callable[[], None] | None,
) -> bool:
    """Verify one receipt-v1 HTTP flag through its registered profile."""
    if sensitive_submission_collector is not None:
        sensitive_submission_collector()
    from ctf.services.challenge._receipt_context import resolve_receipt_validation_context
    from ctf.validators import get_receipt_profile, normalize_http_validator_config, validate_receipt
    from ctf.validators._receipt_profiles import ReceiptVerifierProfile
    from shared.receipt_validation import VerifiedReceiptEvidence

    canonical = normalize_http_validator_config(config, check_destination=False)
    if canonical.get("protocol") != "receipt-v1" or server_context is None:
        return False
    profile = get_receipt_profile(canonical["profile_id"])
    if not isinstance(profile, ReceiptVerifierProfile):
        return False
    receipt_context = resolve_receipt_validation_context(
        server_context,
        profile_id=canonical["profile_id"],
        objective_id=canonical["objective_id"],
    )
    evidence = validate_receipt(receipt_submission, profile, receipt_context)
    if isinstance(evidence, VerifiedReceiptEvidence) and evidence_collector is not None:
        evidence_collector(evidence)
    return isinstance(evidence, VerifiedReceiptEvidence)


def _verify_static_flag(flag_obj: CTFFlag, submitted_flag: str) -> bool:
    """Verify a submitted flag against a static (hashed) CTFFlag."""
    # Static flags: hashed comparison
    value = submitted_flag if flag_obj.case_sensitive else submitted_flag.lower()
    return _verify_hash(value, flag_obj.flag_hash, flag_obj.id)


def _verify_programmable_or_http_flag(
    flag_obj: CTFFlag,
    submitted_flag: str,
    *,
    server_context: ReceiptSubmissionContext | None,
    receipt_submission: str,
    evidence_collector: Callable[[VerifiedReceiptEvidence], None] | None,
    sensitive_submission_collector: Callable[[], None] | None,
) -> bool:
    """Verify a submitted flag against a programmable or HTTP validator CTFFlag."""
    config = flag_obj.validator_config or {}
    if flag_obj.flag_type == "programmable":
        return _verify_programmable_flag(
            flag_obj,
            submitted_flag,
            config,
            server_context=server_context,
            evidence_collector=evidence_collector,
            sensitive_submission_collector=sensitive_submission_collector,
        )
    return _verify_http_flag(
        flag_obj,
        submitted_flag,
        config,
        server_context=server_context,
        receipt_submission=receipt_submission,
        evidence_collector=evidence_collector,
        sensitive_submission_collector=sensitive_submission_collector,
    )


def verify_single_flag(
    flag_obj: CTFFlag,
    submitted_flag: str,
    *,
    server_context: ReceiptSubmissionContext | None = None,
    receipt_submission: str | None = None,
    evidence_collector: Callable[[VerifiedReceiptEvidence], None] | None = None,
    sensitive_submission_collector: Callable[[], None] | None = None,
) -> bool:
    """Verify a submitted flag against a single CTFFlag record.

    Args:
        flag_obj: The CTFFlag instance to verify against.
        submitted_flag: The flag submitted by the participant.

    Returns:
        True if the flag matches.
    """
    # CTF-1401: extension-registered validators win over built-in dispatch.
    from ctf.extensions import flag_validator_supports_server_context, get_flag_validator

    custom = get_flag_validator(flag_obj.flag_type)
    if custom is not None:
        is_valid = _verify_installed_flag(
            flag_obj,
            submitted_flag,
            custom,
            context_capable=flag_validator_supports_server_context(flag_obj.flag_type),
            server_context=server_context,
            evidence_collector=evidence_collector,
            sensitive_submission_collector=sensitive_submission_collector,
        )
    elif flag_obj.flag_type == "regex":
        is_valid = _verify_regex_flag(flag_obj, submitted_flag)
    elif flag_obj.flag_type in ("programmable", "http"):
        is_valid = _verify_programmable_or_http_flag(
            flag_obj,
            submitted_flag,
            server_context=server_context,
            receipt_submission=receipt_submission if receipt_submission is not None else submitted_flag,
            evidence_collector=evidence_collector,
            sensitive_submission_collector=sensitive_submission_collector,
        )
    else:
        is_valid = _verify_static_flag(flag_obj, submitted_flag)
    return is_valid


def _verify_installed_flag(
    flag_obj: CTFFlag,
    submitted_flag: str,
    custom: Callable[..., object],
    *,
    context_capable: bool,
    server_context: ReceiptSubmissionContext | None,
    evidence_collector: Callable[[VerifiedReceiptEvidence], None] | None,
    sensitive_submission_collector: Callable[[], None] | None,
) -> bool:
    """Invoke an installed flag validator and fail closed on any exception."""
    is_valid = False
    try:
        if context_capable:
            if sensitive_submission_collector is not None:
                sensitive_submission_collector()
            receipt_context = _resolve_registered_receipt_context(server_context, flag_obj.validator_config)
            if receipt_context is not None:
                contextual = cast("Callable[[CTFFlag, str, ReceiptValidationContext], object]", custom)
                is_valid = _accept_registered_evidence(
                    contextual(flag_obj, submitted_flag, receipt_context),
                    receipt_context,
                    evidence_collector,
                )
        else:
            legacy = cast("Callable[[CTFFlag, str], bool]", custom)
            is_valid = bool(legacy(flag_obj, submitted_flag))
    except Exception:
        logger.warning("Installed flag validator failed closed for flag %s", flag_obj.id)
    return is_valid


def verify_flag(
    challenge: CTFChallenge,
    submitted_flag: str,
    *,
    server_context: ReceiptSubmissionContext | None = None,
    receipt_submission: str | None = None,
    evidence_collector: Callable[[VerifiedReceiptEvidence], None] | None = None,
    sensitive_submission_collector: Callable[[], None] | None = None,
) -> bool:
    """Verify a submitted flag against a challenge.

    ``CTFFlag`` rows are the sole source of flag truth (any-of semantics, #532).
    A challenge with no active flag rows is unverifiable: every submission is
    rejected and the misconfiguration is logged loudly (there is no legacy
    ``challenge.flag_hash`` fallback).

    Args:
        challenge: The challenge to verify against.
        submitted_flag: The flag submitted by the participant.

    Returns:
        True if the flag is correct, False otherwise.
    """
    flags = list(challenge.flags.all())
    if not flags:
        logger.error(
            "Challenge %s has no flag records; every submission will be rejected. Add at least one flag.",
            challenge.id,
        )
        return False
    return any(
        verify_single_flag(
            flag_obj,
            submitted_flag,
            server_context=server_context,
            receipt_submission=receipt_submission,
            evidence_collector=evidence_collector,
            sensitive_submission_collector=sensitive_submission_collector,
        )
        for flag_obj in flags
    )


def _validate_programmable_config(validator_config: dict[str, Any] | None) -> None:
    """Validate configuration for a programmable flag.

    Args:
        validator_config: The validator configuration dict.

    Raises:
        CTFValidationError: If configuration is invalid.
    """
    from ctf.validators import get_validator, normalize_http_validator_config, validator_supports_server_context

    if validator_config is None or not isinstance(validator_config, dict):
        raise CTFValidationError(
            "validator_config is required for programmable flags",
            details={"missing_fields": ["validator_config"]},
        )
    validator_name = validator_config.get("validator_name", "")
    if not validator_name:
        raise CTFValidationError(
            "validator_config.validator_name is required",
            details={"missing_fields": ["validator_config.validator_name"]},
        )
    if get_validator(validator_name) is None:
        raise CTFValidationError(
            f"Unknown validator: {validator_name}",
            details={"validator_name": validator_name},
        )
    context_capable = validator_supports_server_context(validator_name)
    if not context_capable and "receipt" in validator_config:
        raise CTFValidationError("validator_config.receipt requires a context-capable validator")
    if context_capable:
        if set(validator_config) - {"validator_name", "params", "receipt"}:
            raise CTFValidationError("context-capable validator_config contains unknown fields")
        if not isinstance(validator_config.get("params", {}), dict):
            raise CTFValidationError("validator_config.params must be an object")
        try:
            normalize_http_validator_config(validator_config.get("receipt"))
        except Exception as exc:
            raise CTFValidationError("validator_config.receipt is invalid") from exc


def _resolve_registered_receipt_context(
    server_context: ReceiptSubmissionContext | None,
    selection: object,
) -> ReceiptValidationContext | None:
    """Resolve a closed receipt selection for an explicitly capable callback."""
    from ctf.services.challenge._receipt_context import resolve_registered_receipt_context

    return resolve_registered_receipt_context(server_context, selection)


def _validate_http_config(validator_config: dict[str, Any] | None) -> dict[str, Any]:
    """Validate configuration for an HTTP flag.

    Args:
        validator_config: The validator configuration dict.

    Raises:
        CTFValidationError: If configuration is invalid.
    """
    from ctf.validators import HTTPValidatorConfigError, normalize_http_validator_config

    try:
        return normalize_http_validator_config(validator_config)
    except HTTPValidatorConfigError as exc:
        raise CTFValidationError(str(exc)) from None


def validate_http_flag_config(validator_config: dict[str, Any] | None) -> dict[str, Any]:
    """Return canonical configuration shared by interactive and bundle writes."""
    return _validate_http_config(validator_config)
