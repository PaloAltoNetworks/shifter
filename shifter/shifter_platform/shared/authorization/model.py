"""Pinned OpenFGA model source and catalog coverage checks (#2315)."""

from __future__ import annotations

import re

from .catalog import ACTION_CATALOG, APPLICATION_ADMINISTRATOR_ACTIONS, AuthorizationContractError

MODEL_SERVER_VERSION = "1.20.0"
MODEL_SDK_VERSION = "0.10.4"
MODEL_SCHEMA_VERSION = "1.1"
_RELATIONS_HEADER = "  relations"
_RELATIONSHIP_SUBJECTS = "principal, group#member, role#assignee, authorization_binding#active"


def _action_token(code: str) -> str:
    """Validate a catalog action before encoding it as a relation identifier."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", code):
        raise AuthorizationContractError("Invalid authorization action code")
    return code.replace(".", "_")


def grant_relation_for_action(code: str) -> str:
    """Name the positive assignment relation for a catalog action."""
    return f"grant_{_action_token(code)}"


def deny_relation_for_action(code: str) -> str:
    """Name the explicit exclusion relation for a catalog action."""
    return f"deny_{_action_token(code)}"


def decision_relation_for_action(code: str) -> str:
    """Name the effective permission relation for a catalog action."""
    return f"can_{_action_token(code)}"


def _action_relations(target_type: str) -> list[str]:
    """Render assignment, exclusion, and decision relations for one target type."""
    lines: list[str] = []
    for action in ACTION_CATALOG:
        if action.target_type != target_type:
            continue
        grant = grant_relation_for_action(action.code)
        deny = deny_relation_for_action(action.code)
        decision = decision_relation_for_action(action.code)
        if action.requires_administrator:
            base = "administrator or operator"
        elif action.administrative:
            base = f"{grant} or administrator or operator"
        else:
            base = grant
        lines.extend(
            [
                f"    define {grant}: [{_RELATIONSHIP_SUBJECTS}]",
                f"    define {deny}: [{_RELATIONSHIP_SUBJECTS}]",
                f"    define {decision}: ({base}) but not ({deny} or excluded)",
            ]
        )
    return lines


def _scoped_type(name: str, parent: str) -> list[str]:
    """Render inherited administration and explicit exclusions for a scoped type."""
    return [
        f"type {name}",
        _RELATIONS_HEADER,
        f"    define {parent}: [{parent}]",
        f"    define operator: operator from {parent}",
        f"    define direct_administrator: [{_RELATIONSHIP_SUBJECTS}]",
        f"    define deny_administrator: [{_RELATIONSHIP_SUBJECTS}]",
        f"    define administrator: (direct_administrator but not deny_administrator) or administrator from {parent}",
        f"    define excluded: [principal, group#member, role#assignee] or excluded from {parent}",
        *_action_relations(name),
        "",
    ]


def _event_type() -> list[str]:
    """Let an event inherit from its one validated customer placement."""
    parents = ("account", "organization", "workspace")
    return [
        "type event",
        _RELATIONS_HEADER,
        *(f"    define {parent}: [{parent}]" for parent in parents),
        "    define operator: " + " or ".join(f"operator from {parent}" for parent in parents),
        f"    define direct_administrator: [{_RELATIONSHIP_SUBJECTS}]",
        f"    define deny_administrator: [{_RELATIONSHIP_SUBJECTS}]",
        "    define administrator: (direct_administrator but not deny_administrator) or "
        + " or ".join(f"administrator from {parent}" for parent in parents),
        "    define excluded: [principal, group#member, role#assignee] or "
        + " or ".join(f"excluded from {parent}" for parent in parents),
        *_action_relations("event"),
        "",
    ]


def _build_model() -> str:
    """Assemble the pinned model from the closed application action catalog."""
    lines = [
        "model",
        f"  schema {MODEL_SCHEMA_VERSION}",
        "",
        "type principal",
        "",
        "type authorization_binding",
        _RELATIONS_HEADER,
        "    define candidate: [principal, group#member, role#assignee]",
        "    define superseded: [principal, group#member, role#assignee]",
        "    define active: candidate but not superseded",
        "",
        "type group",
        _RELATIONS_HEADER,
        "    define direct_member: [principal, authorization_binding#active]",
        "    define excluded: [principal, authorization_binding#active]",
        "    define member: direct_member but not excluded",
        "",
        "type role",
        _RELATIONS_HEADER,
        "    define direct_assignee: [principal, group#member, authorization_binding#active]",
        "    define excluded: [principal, group#member, authorization_binding#active]",
        "    define assignee: direct_assignee but not excluded",
        "",
        "type installation",
        _RELATIONS_HEADER,
        f"    define direct_operator: [{_RELATIONSHIP_SUBJECTS}]",
        f"    define deny_operator: [{_RELATIONSHIP_SUBJECTS}]",
        "    define operator: direct_operator but not deny_operator",
        f"    define direct_administrator: [{_RELATIONSHIP_SUBJECTS}]",
        f"    define deny_administrator: [{_RELATIONSHIP_SUBJECTS}]",
        "    define administrator: direct_administrator but not deny_administrator",
        f"    define excluded: [{_RELATIONSHIP_SUBJECTS}]",
        *_action_relations("installation"),
        "",
        *_scoped_type("account", "installation"),
        *_scoped_type("organization", "account"),
        *_scoped_type("workspace", "organization"),
        *_event_type(),
        "type range",
        _RELATIONS_HEADER,
        "    define workspace: [workspace]",
        "    define event: [event]",
        "    define operator: operator from workspace or operator from event",
        f"    define direct_administrator: [{_RELATIONSHIP_SUBJECTS}]",
        f"    define deny_administrator: [{_RELATIONSHIP_SUBJECTS}]",
        "    define administrator: (direct_administrator but not deny_administrator) "
        "or administrator from workspace or administrator from event",
        f"    define excluded: [{_RELATIONSHIP_SUBJECTS}] or excluded from workspace or excluded from event",
        *_action_relations("range"),
        "",
    ]
    return "\n".join(lines)


MODEL_DSL = _build_model()


def validate_model_coverage() -> None:
    """Fail when catalog/model coverage or full-administrator coverage drifts."""
    if not APPLICATION_ADMINISTRATOR_ACTIONS:
        raise AuthorizationContractError("ApplicationAdministrator must cover administrative actions")
    for action in ACTION_CATALOG:
        marker = f"define {decision_relation_for_action(action.code)}:"
        if MODEL_DSL.count(marker) != 1:
            raise AuthorizationContractError(f"OpenFGA model coverage missing for {action.code}")


validate_model_coverage()
