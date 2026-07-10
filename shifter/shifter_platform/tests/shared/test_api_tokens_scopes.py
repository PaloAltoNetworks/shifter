"""Tests for the platform API-token scope registry (PLAT-102).

The scope registry is the central, pure vocabulary that both the DRF
permission layer (now) and the per-app function-view decorators (PLAT-106
migration) check against. These tests are pure-Python, no DB.
"""

from __future__ import annotations

import pytest

from shared.api_tokens import scopes


class TestKnownScopes:
    def test_risk_scopes_are_enforced_today(self):
        assert scopes.RISK_READ == "risk:read"
        assert scopes.RISK_WRITE == "risk:write"
        assert scopes.RISK_READ in scopes.KNOWN_SCOPES
        assert scopes.RISK_WRITE in scopes.KNOWN_SCOPES

    def test_migration_scopes_are_registered(self):
        # Mission Control scopes are enforced by PLAT-106 issue #1120; CTF/CMS
        # scopes remain registered for their follow-on migrations.
        for reserved in (
            "mission_control:range:read",
            "mission_control:range:write",
            "mission_control:upload:write",
            "mission_control:guacamole:read",
            "mission_control:ngfw:read",
            "mission_control:ngfw:write",
            "mission_control:credentials:write",
            "ctf:event:read",
            "ctf:event:write",
            "ctf:play:read",
            "ctf:play:write",
            "cms:authoring:read",
            "cms:authoring:write",
        ):
            assert reserved in scopes.KNOWN_SCOPES

    def test_every_known_scope_follows_resource_operation_convention(self):
        # <resource>:<operation>, lowercase, no wildcards.
        for scope in scopes.KNOWN_SCOPES:
            assert scope == scope.lower()
            assert "*" not in scope
            assert scope.count(":") >= 1
            assert not scope.startswith(":") and not scope.endswith(":")


class TestValidateScopes:
    def test_normalizes_dedupes_and_sorts(self):
        result = scopes.validate_scopes(["risk:write", "risk:read", "risk:write"])
        assert result == ["risk:read", "risk:write"]

    def test_rejects_empty_selection(self):
        with pytest.raises(scopes.InvalidScopeError):
            scopes.validate_scopes([])

    def test_rejects_unknown_scope(self):
        with pytest.raises(scopes.InvalidScopeError):
            scopes.validate_scopes(["risk:read", "totally:bogus"])

    def test_rejects_wildcard(self):
        with pytest.raises(scopes.InvalidScopeError):
            scopes.validate_scopes(["*"])
        with pytest.raises(scopes.InvalidScopeError):
            scopes.validate_scopes(["risk:*"])

    def test_rejects_blank_entries(self):
        with pytest.raises(scopes.InvalidScopeError):
            scopes.validate_scopes(["risk:read", "  "])


class TestHasScope:
    def test_granted_scope_is_present(self):
        assert scopes.has_scope(["risk:read", "risk:write"], "risk:read") is True

    def test_missing_scope_is_denied(self):
        assert scopes.has_scope(["risk:read"], "risk:write") is False

    def test_no_wildcard_expansion(self):
        # Holding a broad-looking string must not satisfy a specific scope.
        assert scopes.has_scope(["risk:*"], "risk:read") is False

    def test_empty_grant_denies(self):
        assert scopes.has_scope([], "risk:read") is False
