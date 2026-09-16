"""Tests for the platform API-token scope registry (PLAT-102).

The scope registry is the central, pure vocabulary that both the DRF
permission layer (now) and the per-app function-view decorators (PLAT-106
migration) check against. These tests are pure-Python, no DB.
"""

from __future__ import annotations

import pytest

from shared.api_tokens import scopes


class TestKnownScopes:
    def test_range_scopes_are_enforced_today(self):
        assert scopes.MISSION_CONTROL_RANGE_READ == "mission_control:range:read"
        assert scopes.MISSION_CONTROL_RANGE_WRITE == "mission_control:range:write"
        assert scopes.MISSION_CONTROL_RANGE_READ in scopes.KNOWN_SCOPES
        assert scopes.MISSION_CONTROL_RANGE_WRITE in scopes.KNOWN_SCOPES

    def test_workspace_membership_scopes_are_registered(self):
        assert scopes.WORKSPACES_MEMBERSHIP_READ == "workspaces:membership:read"
        assert scopes.WORKSPACES_MEMBERSHIP_WRITE == "workspaces:membership:write"
        assert scopes.WORKSPACES_MEMBERSHIP_READ in scopes.KNOWN_SCOPES
        assert scopes.WORKSPACES_MEMBERSHIP_WRITE in scopes.KNOWN_SCOPES

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
            "mission_control:vpn-profile:read",
            "ctf:event:read",
            "ctf:event:write",
            "ctf:play:read",
            "ctf:play:write",
            "ctf:vpn-profile:read",
            "cms:authoring:read",
            "cms:authoring:write",
            "workspaces:membership:read",
            "workspaces:membership:write",
        ):
            assert reserved in scopes.KNOWN_SCOPES

    def test_every_known_scope_follows_resource_operation_convention(self):
        # <resource>:<operation>, lowercase, no wildcards.
        for scope in scopes.KNOWN_SCOPES:
            assert scope == scope.lower()
            assert "*" not in scope
            assert scope.count(":") >= 1
            assert not scope.startswith(":")
            assert not scope.endswith(":")


class TestValidateScopes:
    def test_normalizes_dedupes_and_sorts(self):
        result = scopes.validate_scopes(
            ["mission_control:range:write", "mission_control:range:read", "mission_control:range:write"]
        )
        assert result == ["mission_control:range:read", "mission_control:range:write"]

    def test_rejects_empty_selection(self):
        with pytest.raises(scopes.InvalidScopeError):
            scopes.validate_scopes([])

    def test_rejects_unknown_scope(self):
        with pytest.raises(scopes.InvalidScopeError):
            scopes.validate_scopes(["mission_control:range:read", "totally:bogus"])

    def test_rejects_wildcard(self):
        with pytest.raises(scopes.InvalidScopeError):
            scopes.validate_scopes(["*"])
        with pytest.raises(scopes.InvalidScopeError):
            scopes.validate_scopes(["resource:*"])

    def test_rejects_blank_entries(self):
        with pytest.raises(scopes.InvalidScopeError):
            scopes.validate_scopes(["mission_control:range:read", "  "])


class TestHasScope:
    def test_granted_scope_is_present(self):
        assert (
            scopes.has_scope(
                ["mission_control:range:read", "mission_control:range:write"],
                "mission_control:range:read",
            )
            is True
        )

    def test_missing_scope_is_denied(self):
        assert scopes.has_scope(["mission_control:range:read"], "mission_control:range:write") is False

    def test_no_wildcard_expansion(self):
        # Holding a broad-looking string must not satisfy a specific scope.
        assert scopes.has_scope(["resource:*"], "mission_control:range:read") is False

    def test_empty_grant_denies(self):
        assert scopes.has_scope([], "mission_control:range:read") is False
