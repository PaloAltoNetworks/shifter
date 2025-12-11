"""Tests for shared/tagging.py."""

import pytest
import sys
import os
from datetime import datetime

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
from tagging import get_resource_tags, get_resource_tags_dict


class TestGetResourceTags:
    """Tests for resource tagging."""

    def test_returns_list_format(self):
        tags = get_resource_tags("range-123", "user-456")
        assert isinstance(tags, list)
        assert all(isinstance(t, dict) for t in tags)
        assert all("Key" in t and "Value" in t for t in tags)

    def test_contains_required_tags(self):
        tags = get_resource_tags("range-123", "user-456")
        tag_keys = {t["Key"] for t in tags}

        assert "shifter:range_id" in tag_keys
        assert "shifter:user_id" in tag_keys
        assert "shifter:created_at" in tag_keys
        assert "Project" in tag_keys
        assert "Environment" in tag_keys
        assert "ManagedBy" in tag_keys

    def test_range_id_value(self):
        tags = get_resource_tags("my-range-id", "user-456")
        range_tag = next(t for t in tags if t["Key"] == "shifter:range_id")
        assert range_tag["Value"] == "my-range-id"

    def test_user_id_value(self):
        tags = get_resource_tags("range-123", "my-user-id")
        user_tag = next(t for t in tags if t["Key"] == "shifter:user_id")
        assert user_tag["Value"] == "my-user-id"

    def test_environment_default(self):
        tags = get_resource_tags("range-123", "user-456")
        env_tag = next(t for t in tags if t["Key"] == "Environment")
        assert env_tag["Value"] == "prod"

    def test_environment_custom(self):
        tags = get_resource_tags("range-123", "user-456", environment="dev")
        env_tag = next(t for t in tags if t["Key"] == "Environment")
        assert env_tag["Value"] == "dev"

    def test_managed_by_value(self):
        tags = get_resource_tags("range-123", "user-456")
        managed_tag = next(t for t in tags if t["Key"] == "ManagedBy")
        assert managed_tag["Value"] == "provisioner-lambda"

    def test_created_at_is_iso_format(self):
        tags = get_resource_tags("range-123", "user-456")
        created_tag = next(t for t in tags if t["Key"] == "shifter:created_at")
        # Should be parseable as ISO format
        datetime.fromisoformat(created_tag["Value"].replace("Z", "+00:00"))


class TestGetResourceTagsDict:
    """Tests for dict format tags."""

    def test_returns_dict_format(self):
        tags = get_resource_tags_dict("range-123", "user-456")
        assert isinstance(tags, dict)

    def test_contains_required_keys(self):
        tags = get_resource_tags_dict("range-123", "user-456")

        assert "shifter:range_id" in tags
        assert "shifter:user_id" in tags
        assert "Project" in tags

    def test_values_match_list_format(self):
        list_tags = get_resource_tags("range-123", "user-456", environment="test")
        dict_tags = get_resource_tags_dict("range-123", "user-456", environment="test")

        for tag in list_tags:
            # Skip created_at as timestamps will differ
            if tag["Key"] != "shifter:created_at":
                assert dict_tags[tag["Key"]] == tag["Value"]
