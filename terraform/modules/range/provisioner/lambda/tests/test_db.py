"""Tests for shared/db.py security functions."""

import pytest
import sys
import os

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
from db import validate_uuid, ALLOWED_UPDATE_FIELDS, update_range


class TestValidateUuid:
    """Tests for UUID validation."""

    def test_valid_uuid_lowercase(self):
        assert validate_uuid("12345678-1234-1234-1234-123456789abc") is True

    def test_valid_uuid_uppercase(self):
        assert validate_uuid("12345678-1234-1234-1234-123456789ABC") is True

    def test_valid_uuid_mixed_case(self):
        assert validate_uuid("12345678-ABCD-1234-abcd-123456789AbC") is True

    def test_invalid_uuid_too_short(self):
        assert validate_uuid("12345678-1234-1234-1234-12345678") is False

    def test_invalid_uuid_too_long(self):
        assert validate_uuid("12345678-1234-1234-1234-123456789abcdef") is False

    def test_invalid_uuid_wrong_format(self):
        assert validate_uuid("not-a-valid-uuid-at-all") is False

    def test_invalid_uuid_no_hyphens(self):
        assert validate_uuid("123456781234123412341234567890ab") is False

    def test_invalid_uuid_sql_injection(self):
        assert validate_uuid("'; DROP TABLE users; --") is False

    def test_invalid_uuid_empty(self):
        assert validate_uuid("") is False

    def test_invalid_uuid_spaces(self):
        assert validate_uuid("12345678-1234-1234-1234-123456789abc ") is False


class TestAllowedUpdateFields:
    """Tests for allowed field whitelist."""

    def test_contains_expected_fields(self):
        expected = {
            "status",
            "subnet_id",
            "subnet_cidr",
            "victim_ip",
            "victim_instance_id",
            "chat_url",
            "error_message",
            "ready_at",
            "destroyed_at",
        }
        assert ALLOWED_UPDATE_FIELDS == expected

    def test_does_not_contain_dangerous_fields(self):
        dangerous = {"id", "user_id", "agent_config_id", "created_at", "subnet_index"}
        for field in dangerous:
            assert field not in ALLOWED_UPDATE_FIELDS


class TestUpdateRangeValidation:
    """Tests for update_range input validation (without DB connection)."""

    def test_rejects_invalid_uuid(self):
        """Should reject SQL injection in range_id."""
        with pytest.raises(ValueError, match="Invalid range_id format"):
            update_range(None, "'; DROP TABLE ranges; --", status="ready")

    def test_rejects_invalid_field_name(self):
        """Should reject SQL injection in field names."""
        with pytest.raises(ValueError, match="Invalid field names"):
            update_range(
                None,
                "12345678-1234-1234-1234-123456789abc",
                **{"status; DROP TABLE ranges; --": "ready"}
            )

    def test_rejects_unknown_field(self):
        """Should reject fields not in whitelist."""
        with pytest.raises(ValueError, match="Invalid field names"):
            update_range(
                None,
                "12345678-1234-1234-1234-123456789abc",
                user_id=999,  # Not allowed
            )

    def test_empty_fields_returns_early(self):
        """Should return without error if no fields provided."""
        # Should not raise - returns early before validation
        update_range(None, "invalid-uuid")  # UUID not checked if no fields
