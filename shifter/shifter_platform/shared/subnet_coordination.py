"""Closed, versioned contract for synchronous subnet/CIDR reservation (ADR-043-R6).

Reservation is *pre-mutation coordination*, not an eventual provisioner result:
the CIDRs must be decided and durably reserved before Terraform creates anything,
under the PostgreSQL serialization that has always guarded them. So this contract
is deliberately not the operation input/result contract in
``shared.operation_envelope`` / ``shared.operation_results`` -- those are the
asynchronous launch and result-inbox workflows, and conflating them would give one
operation two authoritative paths.

What crosses this boundary is a request to an Engine-owned privileged database
routine. The routine runs as its definer, so everything the caller supplies is
untrusted input to a privileged context. That is why the bounds below are enforced
here, again inside the routine, and never inferred from a dataclass field, a type
hint, or a SQL cast.

The contract carries only correlation UUIDs, a provider-neutral network identity,
CIDRs, counts, and versions. It is secret-free by construction and adds no
environment variable, credential, or secret reference.

This module stays dependency-light -- the standalone provisioner image imports it
without Django -- and reuses the one existing boundary error rather than adding a
parallel exception hierarchy.
"""

from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass
from uuid import UUID

from shared.exceptions import ValidationError as SubnetCoordinationError

__all__ = [
    "ACCEPTED_COORDINATION_VERSIONS",
    "COORDINATION_CONTRACT_VERSION",
    "MAX_OBSERVED_CIDRS",
    "MAX_SUBNET_COUNT",
    "MAX_SUBNET_LABEL_LENGTH",
    "READ_SQL",
    "REASON_CONFLICT",
    "REASON_EXHAUSTED",
    "REASON_INVALID_REQUEST",
    "REASON_OPERATION_NOT_PERMITTED",
    "REASON_STALE_GENERATION",
    "REASON_UNKNOWN_OPERATION",
    "RELEASE_SQL",
    "RESERVE_SQL",
    "SUPPORTED_PREFIX_LENGTHS",
    "SubnetCoordinationError",
    "SubnetReservationRequest",
    "build_reservation_request",
    "observations_as_pg_array",
    "parse_reservation_result",
    "reason_for_sqlstate",
    "reservation_shape_fingerprint",
]

# Versioned independently of the operation contract and of application/image
# releases: the reservation boundary and the launch/result boundary evolve for
# different reasons and must be able to move separately (ADR-043-R2).
COORDINATION_CONTRACT_VERSION = "1"
ACCEPTED_COORDINATION_VERSIONS = frozenset({"1"})

# The two prefix lengths the allocation policy has always supported. Kept a
# parameter rather than hard-coding the /28 current Cyberscript ranges request, so
# the existing /24 policy or another provider reuses this boundary unchanged.
SUPPORTED_PREFIX_LENGTHS = frozenset({24, 28})

# Bounds, not guesses: a range's authored subnet list is small, and the provider
# observation is one network's subnets. Both cap what a single privileged call can
# be asked to do.
MAX_SUBNET_COUNT = 64
MAX_OBSERVED_CIDRS = 4096
MAX_NETWORK_ID_LENGTH = 255
MAX_SUBNET_LABEL_LENGTH = 128

# "sha256:" + 64 hex, matching the operation-envelope digest spelling.
_DIGEST_PREFIX = "sha256:"

# Fixed reason codes. The adapter maps a routine failure to one of these once;
# SQL text, routine names, table names, and raw driver exceptions never travel
# further than that mapping.
REASON_CONFLICT = "subnet_reservation_conflict"
REASON_EXHAUSTED = "subnet_pool_exhausted"
REASON_STALE_GENERATION = "stale_operation_generation"
REASON_UNKNOWN_OPERATION = "unknown_operation"
REASON_INVALID_REQUEST = "invalid_reservation_request"
# The generation is current, but it belongs to an operation this verb may not be
# invoked for -- for example a destroy generation attempting to reserve.
REASON_OPERATION_NOT_PERMITTED = "operation_not_permitted"

# Mirrors the SQLSTATEs raised by engine migration 0046. Both callers -- the Engine
# service facade and the provisioner adapter -- map through this one table, so the
# routines have a single wire meaning. Keying on the code rather than the message
# leaves the routine's diagnostics free text rather than a parsed interface.
_REASON_BY_SQLSTATE = {
    "SH001": REASON_CONFLICT,
    "SH002": REASON_EXHAUSTED,
    "SH003": REASON_STALE_GENERATION,
    "SH004": REASON_UNKNOWN_OPERATION,
    "SH005": REASON_INVALID_REQUEST,
    "SH006": REASON_OPERATION_NOT_PERMITTED,
}

# The statements are part of the contract, not per-caller detail: two spellings
# would be two APIs onto one privileged surface.
RESERVE_SQL = (
    "SELECT ordinal, subnet_cidr FROM engine_reserve_subnet_cidrs("
    "%s, %s::uuid, %s::uuid, %s, %s::cidr, %s, %s, %s::cidr[], %s)"
)
READ_SQL = "SELECT ordinal, subnet_cidr FROM engine_read_subnet_reservation(%s, %s::uuid, %s::uuid)"
RELEASE_SQL = "SELECT engine_release_subnet_reservation(%s, %s::uuid, %s::uuid)"


def reason_for_sqlstate(sqlstate: object) -> str | None:
    """Return the fixed reason code for a coordination SQLSTATE, if recognized.

    An unrecognized state is not translated: a genuine infrastructure failure must
    not be laundered into a domain reason code that suggests the reservation was
    merely refused.
    """
    if not isinstance(sqlstate, str):
        return None
    return _REASON_BY_SQLSTATE.get(sqlstate)


def observations_as_pg_array(cidrs: tuple[str, ...]) -> str:
    """Render validated observed CIDRs as a PostgreSQL array literal.

    Every element has already been proven a canonical IPv4 network by
    ``build_reservation_request``, so the literal cannot carry a quote, brace, or
    comma. Callers must not pass unvalidated strings here.
    """
    return "{" + ",".join(cidrs) + "}"


@dataclass(frozen=True)
class SubnetReservationRequest:
    """One validated reservation request for a single operation generation."""

    contract_version: str
    operation_id: str
    request_id: str
    network_id: str
    network_cidr: str
    prefix_length: int
    subnets: tuple[str, ...]
    observed_cidrs: tuple[str, ...]
    shape_fingerprint: str

    @property
    def subnet_count(self) -> int:
        """How many CIDRs this request reserves."""
        return len(self.subnets)


def reservation_shape_fingerprint(
    *,
    network_id: str,
    network_cidr: str,
    prefix_length: int,
    subnets: tuple[str, ...],
) -> str:
    """Return the canonical fingerprint of everything a reservation realizes.

    A retry is only the *same* request if it would realize the same thing. Count
    alone is not that: the same number of subnets in a different base network, at
    a different prefix length, or in a different authored order describes a
    different realization, and returning the first batch for it would zip old
    CIDRs positionally onto a new authored order -- silently handing a subnet the
    wrong network.

    Order is significant and deliberately not sorted: position *is* the binding
    between an authored subnet and its CIDR.
    """
    # Newline-separated: subnet labels are validated to exclude control
    # characters, so no component can forge a field boundary.
    canonical = "\n".join(
        [
            COORDINATION_CONTRACT_VERSION,
            network_id,
            network_cidr,
            str(prefix_length),
            *subnets,
        ]
    )
    return _DIGEST_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_uuid(value: object, field: str) -> str:
    """Return the canonical string form of a UUID or raise a contract error."""
    if isinstance(value, UUID):
        return str(value)
    if not isinstance(value, str) or not value:
        raise SubnetCoordinationError(f"{field} must be a UUID string")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise SubnetCoordinationError(f"{field} must be a valid UUID") from exc


def _require_network(value: object, field: str) -> ipaddress.IPv4Network:
    """Return a canonical IPv4 network, rejecting host bits and non-IPv4 input."""
    if not isinstance(value, str) or not value:
        raise SubnetCoordinationError(f"{field} must be an IPv4 CIDR string")
    try:
        # strict=True rejects host bits: "10.1.0.1/16" names a host, not the
        # network the caller means, and letting it through would derive
        # candidates from a network nobody authorized.
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as exc:
        raise SubnetCoordinationError(f"{field} must be a valid IPv4 CIDR") from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise SubnetCoordinationError(f"{field} must be IPv4")
    return network


def _require_bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    """Return an int within an inclusive range or raise a contract error."""
    # bool is an int subclass; accepting it would let True mean 1.
    if not isinstance(value, int) or isinstance(value, bool):
        raise SubnetCoordinationError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise SubnetCoordinationError(f"{field} must be between {minimum} and {maximum}")
    return value


def _require_observations(value: object) -> tuple[str, ...]:
    """Return canonical, de-duplicated observed CIDRs in stable order.

    Order is normalized (not caller-preserved) so an identical observation set
    produces an identical request regardless of the provider's listing order.
    """
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, list | tuple):
        raise SubnetCoordinationError("observed_cidrs must be a list of IPv4 CIDR strings")
    if len(value) > MAX_OBSERVED_CIDRS:
        raise SubnetCoordinationError(f"observed_cidrs must contain at most {MAX_OBSERVED_CIDRS} entries")

    networks: set[ipaddress.IPv4Network] = set()
    for entry in value:
        networks.add(_require_network(entry, "observed_cidrs entry"))
    return tuple(str(network) for network in sorted(networks))


def _require_subnet_label(value: object) -> str:
    """Return one authored subnet identity, or raise a contract error."""
    if not isinstance(value, str) or not value or len(value) > MAX_SUBNET_LABEL_LENGTH:
        raise SubnetCoordinationError("each subnet identity must be a non-empty bounded string")
    # Control characters would let one label forge a field boundary in the
    # newline-separated fingerprint.
    if any(char < " " or char == "\x7f" for char in value):
        raise SubnetCoordinationError("subnet identities must not contain control characters")
    return value


def _require_subnets(value: object) -> tuple[str, ...]:
    """Return the ordered authored subnet identities, or raise a contract error.

    Order is preserved exactly: the reservation result is bound to these
    positionally, so reordering them describes a different realization.
    """
    if isinstance(value, str) or not isinstance(value, list | tuple):
        raise SubnetCoordinationError("subnets must be a list of authored subnet identities")
    if not value or len(value) > MAX_SUBNET_COUNT:
        raise SubnetCoordinationError(f"subnets must contain between 1 and {MAX_SUBNET_COUNT} entries")

    labels = tuple(_require_subnet_label(entry) for entry in value)
    if len(set(labels)) != len(labels):
        raise SubnetCoordinationError("subnet identities must be unique within a reservation")
    return labels


def _require_prefix_length(value: object, network: ipaddress.IPv4Network) -> int:
    """Return a supported prefix length carvable from ``network``."""
    prefix = _require_bounded_int(value, "prefix_length", 0, 32)
    if prefix not in SUPPORTED_PREFIX_LENGTHS:
        raise SubnetCoordinationError(
            f"prefix_length must be one of: {', '.join(str(p) for p in sorted(SUPPORTED_PREFIX_LENGTHS))}"
        )
    if prefix < network.prefixlen:
        raise SubnetCoordinationError("prefix_length must not be shorter than the network it is carved from")
    return prefix


def build_reservation_request(
    *,
    operation_id: object,
    request_id: object,
    network_id: object,
    network_cidr: object,
    prefix_length: object,
    subnets: object,
    observed_cidrs: object = (),
) -> SubnetReservationRequest:
    """Validate and normalize one reservation request.

    Raises:
        SubnetCoordinationError: Any field outside the closed contract. There is
            deliberately no lenient path and no fallback for a missing operation
            generation: without it the routine cannot fence the reservation to a
            current, Engine-authorized episode.
    """
    if not isinstance(network_id, str) or not network_id or len(network_id) > MAX_NETWORK_ID_LENGTH:
        raise SubnetCoordinationError("network_id must be a non-empty identifier")

    network = _require_network(network_cidr, "network_cidr")
    prefix = _require_prefix_length(prefix_length, network)

    normalized_subnets = _require_subnets(subnets)
    return SubnetReservationRequest(
        # The producer always emits the version it was built with; a caller does
        # not get to choose one, so it is not a parameter.
        contract_version=COORDINATION_CONTRACT_VERSION,
        operation_id=_require_uuid(operation_id, "operation_id"),
        request_id=_require_uuid(request_id, "request_id"),
        network_id=network_id,
        network_cidr=str(network),
        prefix_length=prefix,
        subnets=normalized_subnets,
        observed_cidrs=_require_observations(observed_cidrs),
        shape_fingerprint=reservation_shape_fingerprint(
            network_id=network_id,
            network_cidr=str(network),
            prefix_length=prefix,
            subnets=normalized_subnets,
        ),
    )


def parse_reservation_result(rows: object, *, expected_count: int) -> tuple[str, ...]:
    """Return the reserved CIDRs in ordinal order, or fail closed.

    A reservation batch is all-or-nothing, so a short, long, gapped, or repeated
    result is a contract violation rather than a partially satisfied request --
    accepting one would hand the caller fewer subnets than the range needs while
    reporting success.
    """
    if not isinstance(rows, list | tuple):
        raise SubnetCoordinationError("reservation result must be a sequence of (ordinal, cidr) rows")
    if len(rows) != expected_count:
        raise SubnetCoordinationError(f"reservation result must contain exactly {expected_count} entries")

    by_ordinal: dict[int, str] = {}
    seen: set[ipaddress.IPv4Network] = set()
    for row in rows:
        if not isinstance(row, list | tuple) or len(row) != 2:
            raise SubnetCoordinationError("reservation result rows must be (ordinal, cidr) pairs")
        ordinal = _require_bounded_int(row[0], "reservation result ordinal", 1, expected_count)
        network = _require_network(row[1], "reservation result cidr")
        if ordinal in by_ordinal:
            raise SubnetCoordinationError("reservation result has a duplicate ordinal")
        if network in seen:
            raise SubnetCoordinationError("reservation result has a duplicate cidr")
        by_ordinal[ordinal] = str(network)
        seen.add(network)

    # Contiguity is what makes ordinals usable as authored-subnet positions.
    if sorted(by_ordinal) != list(range(1, expected_count + 1)):
        raise SubnetCoordinationError("reservation result ordinals must be contiguous from 1")

    return tuple(by_ordinal[ordinal] for ordinal in range(1, expected_count + 1))
