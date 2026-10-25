"""Closed application authorization action catalog (ADR-066, #2315)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class AuthorizationContractError(ValueError):
    """An authorization contract contains an unknown or inconsistent value."""


TargetType = Literal["installation", "account", "organization", "workspace", "event", "range"]


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """Static metadata for one application action understood by Shifter."""

    code: str
    target_type: TargetType
    administrative: bool
    delegable: bool
    requires_administrator: bool = False
    principal_kinds: frozenset[str] = frozenset({"human", "service"})


@dataclass(frozen=True, slots=True)
class PredefinedPolicyDefinition:
    """One closed built-in policy and its native assignment-group contract."""

    code: str
    name: str
    assignment_group_name: str
    target_type: TargetType
    relation: Literal["administrator", "operator"]
    actions: frozenset[str]


def _action(
    code: str,
    target: TargetType,
    *,
    administrative: bool = True,
    delegable: bool = True,
    requires_administrator: bool = False,
) -> ActionDefinition:
    """Build one catalog entry with explicit delegation and administrator semantics."""
    return ActionDefinition(code, target, administrative, delegable, requires_administrator)


# This is the sole application-action vocabulary. S8 maps each protected surface
# to exactly one entry; adding a surface without extending this tuple is caught by
# the coverage tests introduced with that cutover.
ACTION_CATALOG: tuple[ActionDefinition, ...] = (
    _action("installation.use_personal_tokens", "installation", administrative=False),
    _action("installation.revoke_personal_tokens", "installation"),
    _action("installation.manage_service_credentials", "installation"),
    _action("installation.manage_accounts", "installation"),
    _action("installation.manage_principals", "installation"),
    _action("installation.manage_authorization", "installation"),
    _action(
        "installation.delegate_authorization",
        "installation",
        delegable=False,
        requires_administrator=True,
    ),
    _action("installation.read_audit", "installation"),
    _action("installation.manage_adapters", "installation"),
    _action("installation.manage_model_sources", "installation"),
    _action("installation.manage_cloud_authority", "installation"),
    _action("installation.manage_lease_policy", "installation"),
    _action("account.read", "account"),
    _action("account.update", "account"),
    _action("account.delete", "account"),
    _action("account.manage_members", "account"),
    _action("account.manage_organizations", "account"),
    _action("account.manage_authorization", "account"),
    _action("account.create_event", "account"),
    _action("account.delegate_authorization", "account", delegable=False, requires_administrator=True),
    _action("organization.read", "organization"),
    _action("organization.update", "organization"),
    _action("organization.manage_members", "organization"),
    _action("organization.manage_workspaces", "organization"),
    _action("organization.manage_authorization", "organization"),
    _action("organization.create_event", "organization"),
    _action(
        "organization.delegate_authorization",
        "organization",
        delegable=False,
        requires_administrator=True,
    ),
    _action("workspace.read", "workspace"),
    _action("workspace.leave", "workspace", administrative=False),
    _action("workspace.update", "workspace"),
    _action("workspace.archive", "workspace"),
    _action("workspace.restore", "workspace"),
    _action("workspace.transfer", "workspace"),
    _action("workspace.manage_members", "workspace"),
    _action("workspace.manage_invitations", "workspace"),
    _action("workspace.manage_egress", "workspace"),
    _action("workspace.manage_quota", "workspace"),
    _action("workspace.manage_range_scope", "workspace"),
    _action("workspace.manage_authorization", "workspace"),
    _action("workspace.create_event", "workspace"),
    _action("workspace.delegate_authorization", "workspace", delegable=False, requires_administrator=True),
    _action("workspace.launch_range", "workspace", administrative=False),
    _action("workspace.publish_model_access", "workspace"),
    _action("event.read", "event", administrative=False),
    _action("event.participate", "event", administrative=False, delegable=False),
    _action("event.manage", "event"),
    _action("event.manage_config", "event"),
    _action("event.manage_participants", "event"),
    _action("event.manage_challenges", "event"),
    _action("event.manage_teams", "event"),
    _action("event.manage_ranges", "event"),
    _action("event.manage_scoring", "event"),
    _action("event.manage_awards", "event"),
    _action("event.manage_submissions", "event"),
    _action("event.manage_content", "event"),
    _action("event.manage_lifecycle", "event"),
    _action("event.delete", "event"),
    _action("event.manage_staff", "event", delegable=False, requires_administrator=True),
    _action("event.transfer_ownership", "event", delegable=False, requires_administrator=True),
    _action("event.manage_communications", "event"),
    _action("event.delegate_authorization", "event", delegable=False, requires_administrator=True),
    _action("range.read", "range", administrative=False),
    _action("range.manage", "range", administrative=False),
    _action("range.transfer_ownership", "range"),
    _action("range.access", "range", administrative=False, delegable=False),
)

_ACTIONS_BY_CODE = {action.code: action for action in ACTION_CATALOG}
# Import-time invariant: duplicate codes cannot represent a valid catalog.
if len(_ACTIONS_BY_CODE) != len(ACTION_CATALOG):
    raise RuntimeError("authorization action codes must be unique")

APPLICATION_ADMINISTRATOR_ACTIONS = frozenset(action.code for action in ACTION_CATALOG if action.administrative)


def _actions_at_or_below(target_type: TargetType) -> frozenset[str]:
    """Collect the complete action set rooted at a target's hierarchy level."""
    hierarchy = ("installation", "account", "organization", "workspace", "event", "range")
    start = hierarchy.index(target_type)
    descendants = set(hierarchy[start:])
    return frozenset(action.code for action in ACTION_CATALOG if action.target_type in descendants)


def _administrative_actions_at_or_below(target_type: TargetType) -> frozenset[str]:
    """Select administrative actions within a predefined policy's descendant scope."""
    return frozenset(action for action in _actions_at_or_below(target_type) if _ACTIONS_BY_CODE[action].administrative)


_SCOPED_ADMINISTRATOR_TARGETS: tuple[TargetType, ...] = ("account", "organization", "workspace", "event")

PREDEFINED_POLICIES: tuple[PredefinedPolicyDefinition, ...] = (
    PredefinedPolicyDefinition(
        "application_administrator",
        "Application Administrator",
        "Application Administrators",
        "installation",
        "administrator",
        APPLICATION_ADMINISTRATOR_ACTIONS,
    ),
    PredefinedPolicyDefinition(
        "installation_operator",
        "Installation Operator",
        "Installation Operators",
        "installation",
        "operator",
        APPLICATION_ADMINISTRATOR_ACTIONS,
    ),
    *(
        PredefinedPolicyDefinition(
            f"{target}_administrator",
            f"{target.title()} Administrator",
            f"{target.title()} Administrators",
            target,
            "administrator",
            _administrative_actions_at_or_below(target),
        )
        for target in _SCOPED_ADMINISTRATOR_TARGETS
    ),
)

_PREDEFINED_BY_CODE = {policy.code: policy for policy in PREDEFINED_POLICIES}


def action_definition(code: str) -> ActionDefinition:
    """Resolve one action or fail closed on an unregistered value."""
    try:
        return _ACTIONS_BY_CODE[code]
    except (KeyError, TypeError) as exc:
        raise AuthorizationContractError("Unknown authorization action") from exc


def predefined_policy_definition(code: str) -> PredefinedPolicyDefinition:
    """Resolve one built-in policy without accepting a provider relation string."""
    try:
        return _PREDEFINED_BY_CODE[code]
    except (KeyError, TypeError) as exc:
        raise AuthorizationContractError("Unknown predefined authorization policy") from exc
