"""Join the participant-access sidecar to parsed provisioning truth (#1710, ADR-032-R10).

The sidecar carries compiled *identities* only -- target node address, closed
channel, account address. This module is the cross-contract gate that turns those
identities into realizable access, and it runs **before** any network, VM, Secret
Manager, SSH, or guest mutation so an unrealizable declaration never reaches the
cloud.

It deliberately keeps the two contracts separate: ``raes_plan.parse_plan`` remains
the only ``ProvisioningPlan`` consumer, and participant access stays a separate
process-local value that is *joined* to it, never merged into ``RaesPlan`` or a
node payload.

Every rule here fails closed rather than widening access:

- a target must resolve to exactly one parsed node, and that node must
  materialize exactly one instance -- ``count > 1`` has no authored instance
  selector, so fanning out or silently choosing ``#0`` would invent participant
  semantics;
- an account address is mandatory and must resolve to an enabled, *local*
  account on the same node -- an omitted account is unsupported, never
  permission to broker the reserved provisioner-management user;
- the channel must match the account's authored credential strategy (``ssh`` ->
  ``key``, ``rdp`` -> ``password``), so realization never silently adds a
  second authentication method to an authored account; and
- no endpoint may be declared twice.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from shared.raes.participant_access import ParticipantAccessBinding, ParticipantAccessError

from raes_identity import RESERVED_MANAGEMENT_LOGIN
from raes_plan import RaesPlan

__all__ = ["RaesAccessError", "RealizedAccessBinding", "join_participant_access"]


class RaesAccessError(RuntimeError):
    """The participant-access sidecar cannot be realized against this plan."""


#: The authored credential strategy each channel is brokered through. These are
#: the existing ``raes_account_credentials`` strategies; a new channel extends
#: that realizer and this map together, never this map alone.
_AUTH_METHOD_BY_CHANNEL = {"ssh": "key", "rdp": "password"}


@dataclass(frozen=True)
class RealizedAccessBinding:
    """One declared endpoint bound to the account that realizes it.

    ``username`` is the resolved per-channel login name -- non-secret realization
    metadata, kept per channel so SSH and RDP bindings naming different accounts
    are never conflated into a single instance-wide user.
    """

    target_address: str
    channel: str
    account_address: str
    username: str
    auth_method: str


def _parsed_bindings(transport: Iterable[Mapping[str, object]]) -> tuple[ParticipantAccessBinding, ...]:
    """Re-validate the transport rows through the shared closed parser."""
    bindings: list[ParticipantAccessBinding] = []
    for index, row in enumerate(transport):
        try:
            bindings.append(ParticipantAccessBinding.from_transport(row))
        except ParticipantAccessError as exc:
            raise RaesAccessError(f"participant access binding [{index}] is invalid: {exc}") from None
    return tuple(bindings)


def _resolved_node(binding: ParticipantAccessBinding, nodes_by_address: Mapping[str, object]) -> object:
    """Return the single parsed node a binding targets, or fail closed."""
    node = nodes_by_address.get(binding.target_address)
    if node is None:
        raise RaesAccessError(
            f"participant access target does not resolve to a provisioned node: {binding.target_address}"
        )
    count = getattr(node, "count", 1)
    if count != 1:
        raise RaesAccessError(
            "participant access target must materialize exactly one instance: "
            f"{binding.target_address} declares count={count}"
        )
    return node


def _resolved_account(binding: ParticipantAccessBinding, accounts_by_address: Mapping[str, object]) -> object:
    """Return the enabled local account a binding brokers, or fail closed."""
    account = accounts_by_address.get(binding.account_address)
    if account is None:
        raise RaesAccessError(
            f"participant access account does not resolve to a planned account: {binding.account_address}"
        )
    if getattr(account, "target_address", "") != binding.target_address:
        raise RaesAccessError(
            f"participant access account {binding.account_address} does not target {binding.target_address}"
        )
    if getattr(account, "disabled", False):
        raise RaesAccessError(f"participant access account is disabled: {binding.account_address}")
    if getattr(account, "domain_ref", None) is not None or getattr(account, "domain_id", None) is not None:
        raise RaesAccessError(
            f"participant access requires a local account; {binding.account_address} is domain-scoped"
        )
    # Privilege boundary: an author may declare any local account, including one
    # whose login collides with the provisioner's own management seat. Brokering
    # it would install a participant-controlled credential on the account the
    # provisioner uses for bootstrap, verification, and teardown, handing the
    # range owner management access. Refuse before any credential is installed.
    if getattr(account, "username", "") == RESERVED_MANAGEMENT_LOGIN:
        raise RaesAccessError(
            f"participant access may not broker the reserved management login: {binding.account_address}"
        )
    return account


def _validated_auth_method(binding: ParticipantAccessBinding, account: object) -> str:
    """Return the account auth method, requiring it to match the channel."""
    expected = _AUTH_METHOD_BY_CHANNEL[binding.channel]
    actual = getattr(account, "auth_method", "")
    if actual != expected:
        raise RaesAccessError(
            f"participant access channel {binding.channel} requires an account auth method of "
            f"{expected!r}, but {binding.account_address} authored {actual!r}"
        )
    return actual


def join_participant_access(
    transport: Iterable[Mapping[str, object]],
    raes_plan: RaesPlan,
) -> tuple[RealizedAccessBinding, ...]:
    """Bind every declared endpoint to the plan that realizes it, failing closed.

    ``transport`` is the operation input's ``access_bindings`` rows and
    ``raes_plan`` the separately parsed provisioning plan. Returns the realized
    bindings in declaration order, or ``()`` when the scenario authored none.

    Raises :class:`RaesAccessError` on any binding that is malformed, dangling,
    multi-instance, accountless, foreign, disabled, domain-scoped,
    auth-method-mismatched, or duplicated.
    """
    bindings = _parsed_bindings(transport)
    if not bindings:
        return ()

    nodes_by_address = {node.address: node for node in raes_plan.nodes}
    accounts_by_address = {account.address: account for account in raes_plan.accounts}

    realized: list[RealizedAccessBinding] = []
    seen: set[tuple[str, str]] = set()
    for binding in bindings:
        endpoint = (binding.target_address, binding.channel)
        if endpoint in seen:
            raise RaesAccessError(f"duplicate participant access endpoint: {binding.target_address}/{binding.channel}")
        seen.add(endpoint)
        _resolved_node(binding, nodes_by_address)
        account = _resolved_account(binding, accounts_by_address)
        realized.append(
            RealizedAccessBinding(
                target_address=binding.target_address,
                channel=binding.channel,
                account_address=binding.account_address,
                username=getattr(account, "username", ""),
                auth_method=_validated_auth_method(binding, account),
            )
        )
    return tuple(realized)
