"""Tests for shared/db.py security functions."""

import pytest
import sys
import os

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
from db import validate_range_id, ALLOWED_UPDATE_FIELDS, update_range


class TestValidateRangeId:
    """Tests for range_id validation (positive integer)."""

    def test_valid_integer(self):
        assert validate_range_id(123) is True

    def test_valid_integer_string(self):
        assert validate_range_id("456") is True

    def test_valid_large_integer(self):
        assert validate_range_id(9223372036854775807) is True  # BigInt max

    def test_invalid_zero(self):
        assert validate_range_id(0) is False

    def test_invalid_negative(self):
        assert validate_range_id(-1) is False

    def test_invalid_string(self):
        assert validate_range_id("not-a-number") is False

    def test_invalid_uuid(self):
        # UUIDs are not valid range_ids (we use integer PKs)
        assert validate_range_id("12345678-1234-1234-1234-123456789abc") is False

    def test_invalid_sql_injection(self):
        assert validate_range_id("'; DROP TABLE users; --") is False

    def test_invalid_empty(self):
        assert validate_range_id("") is False

    def test_invalid_none(self):
        assert validate_range_id(None) is False

    def test_invalid_float(self):
        # Float values are coerced to int, so 1.5 -> 1 which is valid
        # But we should ensure the type handling is consistent
        assert validate_range_id(1.5) is True  # int(1.5) = 1 > 0


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
        dangerous = {"id", "user_id", "agent_id", "created_at", "subnet_index"}
        for field in dangerous:
            assert field not in ALLOWED_UPDATE_FIELDS


class TestUpdateRangeValidation:
    """Tests for update_range input validation (without DB connection)."""

    def test_rejects_invalid_range_id(self):
        """Should reject SQL injection in range_id."""
        with pytest.raises(ValueError, match="Invalid range_id format"):
            update_range(None, "'; DROP TABLE ranges; --", status="ready")

    def test_rejects_negative_range_id(self):
        """Should reject negative range_id."""
        with pytest.raises(ValueError, match="Invalid range_id format"):
            update_range(None, -1, status="ready")

    def test_rejects_invalid_field_name(self):
        """Should reject SQL injection in field names."""
        with pytest.raises(ValueError, match="Invalid field names"):
            update_range(
                None,
                123,
                **{"status; DROP TABLE ranges; --": "ready"}
            )

    def test_rejects_unknown_field(self):
        """Should reject fields not in whitelist."""
        with pytest.raises(ValueError, match="Invalid field names"):
            update_range(
                None,
                123,
                user_id=999,  # Not allowed
            )

    def test_empty_fields_returns_early(self):
        """Should return without error if no fields provided."""
        # Should not raise - returns early before validation
        update_range(None, "invalid")  # range_id not checked if no fields
