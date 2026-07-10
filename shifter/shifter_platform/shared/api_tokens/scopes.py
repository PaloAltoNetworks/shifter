"""Central scope registry for platform API tokens (PLAT-102 / PLAT-106).

Scopes are additive HTTP-boundary admission checks of the form
``<resource>:<operation>`` (for example ``risk:read``). They restrict what a
programmatic token may call; they do **not** replace service-layer ownership,
role, or state authorization, which still runs after a token is admitted.

This module is pure (no Django model imports) so it can be imported by the DRF
permission layer today and by the per-app function-view decorators added during
the PLAT-106 migration. New scopes are added here and nowhere else — the
registry is the single extension point.
"""

from __future__ import annotations

from collections.abc import Iterable

# --- Enforced today -----------------------------------------------------------
# Risk register API (the surface PLAT-102 proves end-to-end).
RISK_READ = "risk:read"
RISK_WRITE = "risk:write"

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

# --- Reserved for later PLAT-106 per-app migrations ---------------------------
# Known/valid so tokens can be minted ahead of the CTF/CMS migrations.
CTF_EVENT_READ = "ctf:event:read"
CTF_EVENT_WRITE = "ctf:event:write"
CTF_PLAY_READ = "ctf:play:read"
CTF_PLAY_WRITE = "ctf:play:write"
CMS_AUTHORING_READ = "cms:authoring:read"
CMS_AUTHORING_WRITE = "cms:authoring:write"

KNOWN_SCOPES: frozenset[str] = frozenset(
    {
        RISK_READ,
        RISK_WRITE,
        MISSION_CONTROL_RANGE_READ,
        MISSION_CONTROL_RANGE_WRITE,
        MISSION_CONTROL_UPLOAD_WRITE,
        MISSION_CONTROL_GUACAMOLE_READ,
        MISSION_CONTROL_NGFW_READ,
        MISSION_CONTROL_NGFW_WRITE,
        MISSION_CONTROL_CREDENTIALS_WRITE,
        CTF_EVENT_READ,
        CTF_EVENT_WRITE,
        CTF_PLAY_READ,
        CTF_PLAY_WRITE,
        CMS_AUTHORING_READ,
        CMS_AUTHORING_WRITE,
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
