"""Participant interactive-access sidecar contract (#1710, ADR-032-R10).

RAES ``agents.*.interactive_access`` is PARTICIPANT-domain intent. It is
deliberately absent from the ``ProvisioningPlan`` -- Shifter publishes a
provisioning-only backend and claims no ``participant_runtime`` capability -- so
it can never be injected into the serialized plan, ``RaesPlan``, node payloads,
the backend manifest, or the redacted runtime snapshot.

This module owns the only sanctioned lowering: the released compiler's typed
``ParticipantBehaviorRuntime.interactive_access`` projection becomes a versioned,
bounded, non-secret sidecar of resolved compiled identities -- target node
address, closed channel, and account address. It rides *beside* the serialized
plan exactly as ``DeliveryBinding`` does (ADR-032-R3), never inside it, and
carries no locator, port, credential, credential reference, username, or
realization claim.

**Participant invariance.** RAES interactive access is participant-local, while
the current Mission Control / CTF model authorizes a Shifter *range owner* with
no trusted actor-to-participant mapping. Unioning red, blue, and other agents
would widen every actor to the most privileged agent, so a scenario is
realizable only when every compiled participant declares the same normalized
binding set. Divergence -- including one participant bearing access beside an
empty one -- fails closed before dispatch. Server-derived participant selection
is the declared future seam; union is never the fallback.

Pure: no I/O, no ``cms`` / ``engine`` import, no cloud SDK.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "ACCESS_BINDING_VERSION",
    "MAX_ACCESS_BINDINGS",
    "SUPPORTED_ACCESS_CHANNELS",
    "ParticipantAccessBinding",
    "ParticipantAccessError",
    "project_participant_access",
]


class ParticipantAccessError(Exception):
    """The authored participant access is not a realizable, bounded sidecar."""


#: Rolling-deploy seam: persisted / transported bindings carry this version and
#: readers reject any version they do not explicitly support (ADR-032-R10).
ACCESS_BINDING_VERSION = 1

#: The closed channel vocabulary, matching the RAES authored enum and the
#: existing ``shared.range_cells`` range-cell channels. A new channel extends the
#: upstream vocabulary, the range-cell policy, the broker, and the network rules
#: together -- never this set alone.
SUPPORTED_ACCESS_CHANNELS = frozenset({"ssh", "rdp"})

#: The sidecar is a bounded reference projection, never a topology dump.
MAX_ACCESS_BINDINGS = 256

_TRANSPORT_KEYS = frozenset({"target_address", "channel", "account_address", "binding_version"})


def _require(condition: bool, message: str) -> None:
    """Raise :class:`ParticipantAccessError` when ``condition`` does not hold."""
    if not condition:
        raise ParticipantAccessError(message)


def _required_text(value: object, field: str) -> str:
    """Return a non-empty compiled identity, failing closed on anything else."""
    _require(isinstance(value, str) and value.strip() != "", f"participant access {field} must be a non-empty string")
    return str(value).strip()


def _validated_channel(value: object) -> str:
    """Return a channel inside the closed vocabulary."""
    channel = _required_text(value, "channel")
    _require(channel in SUPPORTED_ACCESS_CHANNELS, f"participant access channel is unsupported: {channel}")
    return channel


@dataclass(frozen=True, order=True)
class ParticipantAccessBinding:
    """One resolved, non-secret participant-access identity beside the plan.

    Compiled identities only. It is not a host locator, port, credential,
    credential reference, login name, portal session, or realization claim: the
    provisioner resolves all of those from provisioning truth after joining this
    binding to the separately parsed plan.
    """

    target_address: str
    channel: str
    account_address: str
    binding_version: int = ACCESS_BINDING_VERSION

    def to_transport(self) -> dict[str, object]:
        """Return the JSON-serialisable transport shape (identity only)."""
        _require(
            self.binding_version == ACCESS_BINDING_VERSION,
            f"unsupported participant access binding version {self.binding_version!r}",
        )
        return {
            "target_address": self.target_address,
            "channel": self.channel,
            "account_address": self.account_address,
            "binding_version": self.binding_version,
        }

    @classmethod
    def from_transport(cls, raw: Mapping[str, object]) -> ParticipantAccessBinding:
        """Rebuild a binding from transport, failing closed on any tamper.

        Rejects unknown keys -- so a smuggled address, port, username, or
        credential reference cannot ride along -- plus an unsupported version,
        an unsupported channel, and any blank compiled identity.
        """
        _require(isinstance(raw, Mapping), "participant access binding transport shape is invalid")
        _require(
            frozenset(raw) == _TRANSPORT_KEYS,
            "participant access binding transport carries unexpected or missing keys",
        )
        version = raw["binding_version"]
        # Narrowed inline rather than through ``_require``: a bool is an int
        # subclass, so ``True`` would otherwise pass as version 1.
        if not isinstance(version, int) or isinstance(version, bool) or version != ACCESS_BINDING_VERSION:
            raise ParticipantAccessError(f"unsupported participant access binding version {version!r}")
        return cls(
            target_address=_required_text(raw["target_address"], "target_address"),
            channel=_validated_channel(raw["channel"]),
            account_address=_required_text(raw["account_address"], "account_address"),
            binding_version=version,
        )


def _participant_bindings(
    behavior: object,
    *,
    node_addresses: frozenset[str],
) -> frozenset[ParticipantAccessBinding]:
    """Normalize one compiled participant's declared access, failing closed.

    Every declaration must resolve to a declared provisioning node and name an
    explicit account: an omitted account is unsupported, never permission to
    choose a default OS user or the reserved provisioner-management account.
    """
    bindings: set[ParticipantAccessBinding] = set()
    seen: set[tuple[str, str]] = set()
    for access in getattr(behavior, "interactive_access", ()):
        target = _required_text(getattr(access, "target_address", ""), "target address")
        _require(
            target in node_addresses,
            f"participant access target does not resolve to a declared provisioning node: {target}",
        )
        channel = _validated_channel(getattr(access, "channel", ""))
        account = _required_text(getattr(access, "account_address", ""), "account address")
        endpoint = (target, channel)
        _require(endpoint not in seen, f"duplicate participant access declaration: {target}/{channel}")
        seen.add(endpoint)
        bindings.add(ParticipantAccessBinding(target_address=target, channel=channel, account_address=account))
    return frozenset(bindings)


def project_participant_access(
    participant_behaviors: Mapping[str, object],
    *,
    node_addresses: frozenset[str],
) -> tuple[ParticipantAccessBinding, ...]:
    """Lower compiled participant interactive access into the bounded sidecar.

    ``participant_behaviors`` is ``RuntimeModel.participant_behaviors`` and
    ``node_addresses`` the declared provisioning node addresses of the same
    compiled plan. Returns the deterministic, sorted binding set, or ``()`` when
    the scenario authored none.

    Raises :class:`ParticipantAccessError` when the scenario is not realizable
    under the current product contract: divergent participant policies, an
    unresolved or dangling target, an unsupported channel, an omitted account, a
    duplicate endpoint, or an unbounded binding set.
    """
    normalized = {
        name: _participant_bindings(behavior, node_addresses=node_addresses)
        for name, behavior in participant_behaviors.items()
    }
    if not normalized:
        return ()

    distinct = set(normalized.values())
    _require(
        len(distinct) == 1,
        "participant access must be participant-invariant: compiled participants declare different access sets",
    )

    bindings = distinct.pop()
    _require(
        len(bindings) <= MAX_ACCESS_BINDINGS,
        f"participant access must stay bounded: {len(bindings)} exceeds {MAX_ACCESS_BINDINGS}",
    )
    return tuple(sorted(bindings))
