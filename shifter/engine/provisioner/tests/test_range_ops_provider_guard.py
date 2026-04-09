"""Tests for provider guards in range_ops.py."""

from unittest.mock import patch

import pytest

from range_ops import get_range_instance_ids


class TestRangeOpsProviderGuard:
    """Ensure AWS-only lifecycle code fails fast for non-AWS providers."""

    def test_get_range_instance_ids_rejects_gcp_instances(self):
        rows = [
            (
                "instance-uuid-123",
                {
                    "cloud_provider": "gcp",
                    "instance_id": "vmrt-vm-1",
                    "provider_metadata": {"gdc": {"vm_name": "vmrt-vm-1"}},
                },
                "victim",
            )
        ]

        with patch("range_ops.get_db_connection") as mock_get_db_connection:
            conn = mock_get_db_connection.return_value.__enter__.return_value
            cursor = conn.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = rows

            with pytest.raises(NotImplementedError, match="AWS-only"):
                get_range_instance_ids("req-123")
