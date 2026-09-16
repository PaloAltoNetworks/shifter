"""Read the immutable operation-input projection (ADR-043 phase 5, #1837).

The provisioner's only remaining read of Engine-owned state. It selects exactly
one row -- the one keyed by the canonical ``operation_id`` its run was launched
for -- and validates the transport envelope plus every flattened discriminator
before the payload reaches a domain parser.

Two properties are load-bearing:

* **Exact selection, never "latest by request."** A retry of an operation
  generation must consume the input materialized for *that* generation. Reading
  the newest row for the request would silently pick up a registry, binding, or
  backend change made after launch and realize a range the Engine never
  authorized for this episode.
* **No fallback.** When the row is missing or fails validation the operation
  fails closed. Falling back to a direct domain-table read would restore the
  private-schema coupling ADR-043 exists to remove -- and after cutover those
  grants are gone anyway.

``engine_operation_input`` is granted ``SELECT`` to the provisioner principal by
engine migration 0036; nothing here needs any other capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.operation_envelope import (
    ACCEPTED_CONTRACT_VERSIONS,
    OperationEnvelopeError,
    validate_operation_envelope,
)
from shared.raes.operation_input import RaesOperationInput, RaesOperationInputError, parse_raes_operation_input
from shared.warm_pool.activation_input import ActivationInput, ActivationInputError, parse_activation_input

from provisioner_db import get_db_connection

__all__ = [
    "ActivationRun",
    "OperationInputError",
    "RaesOperationRun",
    "ValidatedOperationInput",
    "get_activation_operation_input",
    "get_operation_input",
    "get_raes_operation_input",
]


class OperationInputError(Exception):
    """The operation input is missing, unreadable, or not the row we asked for."""


@dataclass(frozen=True)
class ValidatedOperationInput:
    """One operation input whose identity has been proven, not assumed.

    Callers correlate results from *these* fields rather than from the argv they
    were handed: after validation the two agree, and building refs from the
    proven identity keeps them agreeing if the reader's contract ever changes.
    """

    operation_id: str
    request_id: str
    resource: str
    operation: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RaesOperationRun:
    """The proven identity plus the parsed RAES projection for one generation."""

    operation_id: str
    request_id: str
    input: RaesOperationInput


@dataclass(frozen=True)
class ActivationRun:
    """The proven identity plus the parsed warm-pool activation projection (#28)."""

    operation_id: str
    request_id: str
    input: ActivationInput


_SELECT_OPERATION_INPUT_SQL = """
    SELECT operation_id, request_id, resource, operation, contract_version, envelope
    FROM engine_operation_input
    WHERE operation_id = %s
"""

# The flattened columns the applier and this reader both key on. A row whose
# columns disagree with the signed-shape envelope is not merely redundant -- it
# is a row that would be consumed under the wrong identity.
_DISCRIMINATORS = ("operation_id", "request_id", "resource", "operation", "contract_version")


def get_operation_input(
    *, operation_id: str, request_id: str, resource: str, operation: str
) -> ValidatedOperationInput:
    """Return the validated input for one operation generation, or fail closed.

    The generation identity is compound: ``(operation_id, request_id)``. Argv
    carries both independently, so selecting on ``operation_id`` alone and
    trusting the command's ``request_id`` leaves them unbound -- a caller able
    to influence command arguments could pair one request's operation with
    another request's id. The row is internally self-consistent in that case, so
    checking the row against its own envelope does not catch it; binding both to
    the command does. Result-ownership checks at the applier fire only *after*
    the cloud mutation, so they cannot contain this either.

    Args:
        operation_id: The canonical ADR-043 generation this run was launched for.
        request_id: The request identity supplied on the same command.
        resource: The resource discriminator the caller expects (for example
            ``raes-range``).
        operation: The operation discriminator the caller expects.

    Raises:
        OperationInputError: No row for the generation, an unreadable or invalid
            envelope, an unsupported contract version, any flattened column
            disagreeing with the envelope, or an identity that does not match
            the command's.
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT_OPERATION_INPUT_SQL, (str(operation_id),))
        row = cur.fetchone()

    if not row:
        raise OperationInputError("no operation input is materialized for this operation generation")

    columns = dict(zip(_DISCRIMINATORS, row[: len(_DISCRIMINATORS)], strict=True))
    try:
        envelope = validate_operation_envelope(row[len(_DISCRIMINATORS)])
    except OperationEnvelopeError as exc:
        raise OperationInputError(f"operation input envelope is invalid: {exc}") from None

    if columns["contract_version"] not in ACCEPTED_CONTRACT_VERSIONS:
        raise OperationInputError(f"operation input contract_version {columns['contract_version']} is not supported")

    for field in _DISCRIMINATORS:
        if str(columns[field]) != str(envelope[field]):
            raise OperationInputError(f"operation input {field} does not match the envelope")

    if str(envelope["resource"]) != resource or str(envelope["operation"]) != operation:
        raise OperationInputError(
            f"operation input is for {envelope['resource']}:{envelope['operation']}, not {resource}:{operation}"
        )

    if str(envelope["request_id"]) != str(request_id):
        raise OperationInputError("operation input belongs to a different request than the command supplied")

    return ValidatedOperationInput(
        operation_id=str(envelope["operation_id"]),
        request_id=str(envelope["request_id"]),
        resource=str(envelope["resource"]),
        operation=str(envelope["operation"]),
        payload=envelope["payload"],
    )


def get_raes_operation_input(operation_id: str, *, request_id: str, operation: str) -> RaesOperationRun:
    """Return the proven identity and parsed RAES projection for one generation.

    Runs the closed RAES payload parser on top of the transport and identity
    validation, so a tampered delivery binding, an over-claiming registry row,
    an unbounded collection, or a request/operation pair that were never
    launched together fails here -- before any cloud or guest mutation -- rather
    than part-way through realization.
    """
    validated = get_operation_input(
        operation_id=operation_id, request_id=request_id, resource="raes-range", operation=operation
    )
    try:
        projection = parse_raes_operation_input(validated.payload)
    except RaesOperationInputError as exc:
        raise OperationInputError(f"raes operation input is invalid: {exc}") from None
    return RaesOperationRun(operation_id=validated.operation_id, request_id=validated.request_id, input=projection)


def get_activation_operation_input(operation_id: str, *, request_id: str) -> ActivationRun:
    """Return the proven identity and parsed warm-pool activation projection (#28).

    Runs the closed activation payload parser (claimant projection + the embedded
    ownership-neutral RAES realization projection) on top of the transport and
    identity validation, so a tampered claimant field or a malformed RAES input
    fails here -- before the provisioner scrubs or rotates anything on the claimed
    generation -- rather than part-way through activation.
    """
    validated = get_operation_input(
        operation_id=operation_id, request_id=request_id, resource="raes-range", operation="activate"
    )
    try:
        projection = parse_activation_input(validated.payload)
    except ActivationInputError as exc:
        raise OperationInputError(f"activation operation input is invalid: {exc}") from None
    return ActivationRun(operation_id=validated.operation_id, request_id=validated.request_id, input=projection)
