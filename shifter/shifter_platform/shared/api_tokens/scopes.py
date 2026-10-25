"""Central scope registry for platform API tokens (PLAT-102 / PLAT-106).

Scopes are additive HTTP-boundary admission checks of the form
``<resource>:<operation>``. They restrict what a
programmatic token may call; they do **not** replace service-layer ownership,
role, or state authorization, which still runs after a token is admitted.

This module is pure (no Django model imports) so it can be imported by the DRF
permission layer today and by the per-app function-view decorators added during
the PLAT-106 migration. New scopes are added here and nowhere else — the
registry is the single extension point.
"""

from __future__ import annotations

from collections.abc import Iterable

from shared.authorization import ACTION_CATALOG, CredentialCeiling, TargetRef

# --- Mission Control API (PLAT-106 / issue #1120) -----------------------------
# Wired by subsurface instead of overloading a single coarse Mission Control
# token audience.
MISSION_CONTROL_RANGE_READ = "mission_control:range:read"
MISSION_CONTROL_RANGE_WRITE = "mission_control:range:write"
MISSION_CONTROL_UPLOAD_WRITE = "mission_control:upload:write"
MISSION_CONTROL_GUACAMOLE_READ = "mission_control:guacamole:read"
MISSION_CONTROL_NGFW_READ = "mission_control:ngfw:read"
MISSION_CONTROL_NGFW_WRITE = "mission_control:ngfw:write"
MISSION_CONTROL_CREDENTIALS_WRITE = "mission_control:credentials:write"
MISSION_CONTROL_VPN_PROFILE_READ = "mission_control:vpn-profile:read"

# --- Reserved for later PLAT-106 per-app migrations ---------------------------
# Known/valid so tokens can be minted ahead of the CTF/CMS migrations.
CTF_EVENT_READ = "ctf:event:read"
CTF_EVENT_WRITE = "ctf:event:write"
CTF_PLAY_READ = "ctf:play:read"
CTF_PLAY_WRITE = "ctf:play:write"
CTF_COMMUNICATION_READ = "ctf:communication:read"
CTF_COMMUNICATION_WRITE = "ctf:communication:write"
CTF_VPN_PROFILE_READ = "ctf:vpn-profile:read"
CMS_AUTHORING_READ = "cms:authoring:read"
CMS_AUTHORING_WRITE = "cms:authoring:write"
CMS_PREPARATION_ADAPTERS_READ = "cms:preparation-adapters:read"
CMS_PREPARATION_ADAPTERS_WRITE = "cms:preparation-adapters:write"
CMS_PREPARATION_READ = "cms:preparation:read"
CMS_PREPARATION_WRITE = "cms:preparation:write"

# --- Workspace membership API (#1326) ----------------------------------------
WORKSPACES_MEMBERSHIP_READ = "workspaces:membership:read"
WORKSPACES_MEMBERSHIP_WRITE = "workspaces:membership:write"

# --- Application authorization API (#2315) ----------------------------------
# One exact credential scope per closed action. A token cannot use a broader
# administration scope to delegate an action it was not explicitly issued.
AUTHORIZATION_ACTION_SCOPES = {action.code: f"authorization:{action.code}" for action in ACTION_CATALOG}

# --- Scoped model-access management (M09, #2126 / PLAT-202) -------------------
# Exact per-audience scopes for the management projection surface. Each audience
# has its own read/write pair so a token is admitted only to the surface it was
# minted for; a broad CTF/CMS scope never substitutes (management-preflight-2126.md).
MODEL_ACCESS_OPERATOR_READ = "model-access:operator:read"
MODEL_ACCESS_OPERATOR_WRITE = "model-access:operator:write"
MODEL_ACCESS_SHARING_READ = "model-access:sharing:read"
MODEL_ACCESS_SHARING_WRITE = "model-access:sharing:write"
MODEL_ACCESS_EVENT_READ = "model-access:event:read"
MODEL_ACCESS_EVENT_WRITE = "model-access:event:write"
MODEL_ACCESS_RANGE_READ = "model-access:range:read"
MODEL_ACCESS_RANGE_WRITE = "model-access:range:write"
MODEL_ACCESS_PARTICIPANT_READ = "model-access:participant:read"

KNOWN_SCOPES: frozenset[str] = frozenset(
    {
        MISSION_CONTROL_RANGE_READ,
        MISSION_CONTROL_RANGE_WRITE,
        MISSION_CONTROL_UPLOAD_WRITE,
        MISSION_CONTROL_GUACAMOLE_READ,
        MISSION_CONTROL_NGFW_READ,
        MISSION_CONTROL_NGFW_WRITE,
        MISSION_CONTROL_CREDENTIALS_WRITE,
        MISSION_CONTROL_VPN_PROFILE_READ,
        CTF_EVENT_READ,
        CTF_EVENT_WRITE,
        CTF_PLAY_READ,
        CTF_PLAY_WRITE,
        CTF_COMMUNICATION_READ,
        CTF_COMMUNICATION_WRITE,
        CTF_VPN_PROFILE_READ,
        CMS_AUTHORING_READ,
        CMS_AUTHORING_WRITE,
        CMS_PREPARATION_ADAPTERS_READ,
        CMS_PREPARATION_ADAPTERS_WRITE,
        CMS_PREPARATION_READ,
        CMS_PREPARATION_WRITE,
        WORKSPACES_MEMBERSHIP_READ,
        WORKSPACES_MEMBERSHIP_WRITE,
        *AUTHORIZATION_ACTION_SCOPES.values(),
        MODEL_ACCESS_OPERATOR_READ,
        MODEL_ACCESS_OPERATOR_WRITE,
        MODEL_ACCESS_SHARING_READ,
        MODEL_ACCESS_SHARING_WRITE,
        MODEL_ACCESS_EVENT_READ,
        MODEL_ACCESS_EVENT_WRITE,
        MODEL_ACCESS_RANGE_READ,
        MODEL_ACCESS_RANGE_WRITE,
        MODEL_ACCESS_PARTICIPANT_READ,
    }
)


class InvalidScopeError(ValueError):
    """Raised when a scope selection is empty, malformed, or unknown."""


def validate_scopes(values: Iterable[str]) -> list[str]:
    """Return a normalized, de-duplicated, sorted list of valid scopes.

    Rejects an empty selection, blank entries, wildcards, and any scope not in
    :data:`KNOWN_SCOPES`. Wildcards are refused outright — a token grants an
    explicit set of scopes, never ``*`` (preflight guardrail: no wildcard scopes
    by default).
    """
    normalized: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise InvalidScopeError(f"scope must be a string, got {type(raw).__name__}")
        scope = raw.strip()
        if not scope:
            raise InvalidScopeError("blank scope is not allowed")
        if "*" in scope:
            raise InvalidScopeError(f"wildcard scopes are not allowed: {scope!r}")
        if scope not in KNOWN_SCOPES:
            raise InvalidScopeError(f"unknown scope: {scope!r}")
        normalized.add(scope)
    if not normalized:
        raise InvalidScopeError("at least one scope is required")
    return sorted(normalized)


def has_scope(granted_scopes: Iterable[str], required_scope: str) -> bool:
    """Return True iff ``required_scope`` is among ``granted_scopes``.

    Exact membership only — there is no wildcard expansion, so holding a
    broad-looking string never satisfies a specific required scope.
    """
    return required_scope in set(granted_scopes)


def credential_ceiling(scopes: Iterable[str], *, target: TargetRef | None = None) -> CredentialCeiling:
    """Project registered action scopes without inferring broad legacy authority."""
    by_scope = {scope: action for action, scope in AUTHORIZATION_ACTION_SCOPES.items()}
    # Exact incumbent CTF operation correspondence. Other legacy scopes remain
    # HTTP limits until their owning S4-S6 action mapping is delivered.
    by_scope.update({CTF_EVENT_READ: "event.read", CTF_EVENT_WRITE: "event.manage"})
    return CredentialCeiling(frozenset(by_scope[scope] for scope in scopes if scope in by_scope), target)
