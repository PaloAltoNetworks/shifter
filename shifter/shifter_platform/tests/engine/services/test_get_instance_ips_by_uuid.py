"""Tests for get_instance_ips_by_uuid() in engine/services.py."""

from datetime import UTC, datetime
from unittest.mock import Mock, patch


class TestGetInstanceIpsByUuid:
    """Service contract for get_instance_ips_by_uuid.

    - Input: range_id (int)
    - Output: {uuid: ip} mapping for provisioned instances with both fields
    - Missing range, missing UUIDs, or unresolvable IPs are dropped silently
    """

    def _mock_range(self, instances):
        from engine.models import Range

        return Mock(
            spec=Range,
            id=42,
            status=Range.Status.READY,
            error_message="",
            provisioned_instances=instances,
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ready_at=datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC),
        )

    def test_returns_empty_dict_when_range_not_found(self):
        from engine.models import Range
        from engine.services import get_instance_ips_by_uuid

        with patch.object(Range.objects, "get", side_effect=Range.DoesNotExist):
            assert get_instance_ips_by_uuid(999) == {}

    def test_returns_empty_dict_when_no_provisioned_instances(self):
        from engine.models import Range
        from engine.services import get_instance_ips_by_uuid

        with patch.object(Range.objects, "get", return_value=self._mock_range([])):
            assert get_instance_ips_by_uuid(42) == {}

    def test_maps_uuid_to_resolved_host(self):
        from engine.models import Range
        from engine.services import get_instance_ips_by_uuid

        instances = [
            {"uuid": "abc-123", "private_ip": "10.0.1.10"},
            {"uuid": "def-456", "host": "10.0.1.20"},
        ]
        with patch.object(Range.objects, "get", return_value=self._mock_range(instances)):
            result = get_instance_ips_by_uuid(42)
        assert result == {"abc-123": "10.0.1.10", "def-456": "10.0.1.20"}

    def test_skips_instances_without_uuid(self):
        from engine.models import Range
        from engine.services import get_instance_ips_by_uuid

        instances = [
            {"private_ip": "10.0.1.10"},
            {"uuid": "", "private_ip": "10.0.1.11"},
            {"uuid": "abc-123", "private_ip": "10.0.1.12"},
        ]
        with patch.object(Range.objects, "get", return_value=self._mock_range(instances)):
            result = get_instance_ips_by_uuid(42)
        assert result == {"abc-123": "10.0.1.12"}

    def test_skips_instances_without_resolvable_ip(self):
        from engine.models import Range
        from engine.services import get_instance_ips_by_uuid

        instances = [
            {"uuid": "no-ip", "role": "attacker"},
            {"uuid": "blank-ip", "private_ip": "  "},
            {"uuid": "ok", "private_ip": "10.0.1.5"},
        ]
        with patch.object(Range.objects, "get", return_value=self._mock_range(instances)):
            result = get_instance_ips_by_uuid(42)
        assert result == {"ok": "10.0.1.5"}

    def test_resolves_via_provider_metadata(self):
        from engine.models import Range
        from engine.services import get_instance_ips_by_uuid

        instances = [
            {
                "uuid": "gcp-1",
                "cloud_provider": "gcp",
                "provider_metadata": {"gcp": {"private_ip": "10.200.0.1"}},
            },
        ]
        with patch.object(Range.objects, "get", return_value=self._mock_range(instances)):
            result = get_instance_ips_by_uuid(42)
        assert result == {"gcp-1": "10.200.0.1"}

    def test_priority_host_over_private_ip(self):
        """Mirrors _resolve_instance_host priority: top-level host wins over private_ip."""
        from engine.models import Range
        from engine.services import get_instance_ips_by_uuid

        instances = [{"uuid": "x", "host": "10.0.0.99", "private_ip": "10.0.1.1"}]
        with patch.object(Range.objects, "get", return_value=self._mock_range(instances)):
            result = get_instance_ips_by_uuid(42)
        assert result == {"x": "10.0.0.99"}
