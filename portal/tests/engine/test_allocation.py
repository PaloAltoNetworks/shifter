"""Tests for engine.services.allocation module."""

import pytest
from django.contrib.auth import get_user_model

from engine.services.allocation import AllocationError, allocate_subnet_index
from mission_control.models import AgentConfig, OperatingSystem, Range

User = get_user_model()


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def windows_os(db):
    """Get the Windows operating system."""
    return OperatingSystem.objects.get(slug="windows")


@pytest.fixture
def agent(db, user, windows_os):
    """Create a test agent."""
    return AgentConfig.objects.create(
        user=user,
        os=windows_os,
        name="Test Agent",
        s3_key="agents/1/test.msi",
        original_filename="test.msi",
        file_size_bytes=1024,
        sha256_hash="abc123",
    )


def create_range(user, agent, status, subnet_index):
    """Helper to create a range with specific status and subnet index."""
    return Range.objects.create(
        user=user,
        agent=agent,
        status=status,
        subnet_index=subnet_index,
        instance_config=[{"role": "attacker", "os_type": "kali"}],
    )


# -----------------------------------------------------------------------------
# Tests for allocate_subnet_index
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestAllocateSubnetIndex:
    """Tests for allocate_subnet_index function."""

    def test_returns_one_when_no_ranges_exist(self):
        """First allocation should return 1."""
        index = allocate_subnet_index()
        assert index == 1

    def test_returns_next_available_index(self, user, agent):
        """Should return next index after used ones."""
        create_range(user, agent, Range.Status.READY, subnet_index=1)

        index = allocate_subnet_index()
        assert index == 2

    def test_reuses_destroyed_range_index(self, user, agent):
        """Destroyed ranges should release their subnet index."""
        create_range(user, agent, Range.Status.DESTROYED, subnet_index=1)

        index = allocate_subnet_index()
        assert index == 1  # Should reuse index 1

    def test_reuses_failed_range_index(self, user, agent):
        """Failed ranges should release their subnet index."""
        create_range(user, agent, Range.Status.FAILED, subnet_index=1)

        index = allocate_subnet_index()
        assert index == 1  # Should reuse index 1

    def test_fills_gaps_in_allocation(self, user, agent):
        """Should fill gaps rather than always using next highest."""
        create_range(user, agent, Range.Status.READY, subnet_index=1)
        create_range(user, agent, Range.Status.READY, subnet_index=3)
        # Gap at index 2

        index = allocate_subnet_index()
        assert index == 2  # Should fill the gap

    def test_skips_provisioning_ranges(self, user, agent):
        """Provisioning ranges should hold their index."""
        create_range(user, agent, Range.Status.PROVISIONING, subnet_index=1)

        index = allocate_subnet_index()
        assert index == 2

    def test_skips_ready_ranges(self, user, agent):
        """Ready ranges should hold their index."""
        create_range(user, agent, Range.Status.READY, subnet_index=1)

        index = allocate_subnet_index()
        assert index == 2

    def test_skips_paused_ranges(self, user, agent):
        """Paused ranges should hold their index."""
        create_range(user, agent, Range.Status.PAUSED, subnet_index=1)

        index = allocate_subnet_index()
        assert index == 2

    def test_skips_resuming_ranges(self, user, agent):
        """Resuming ranges should hold their index."""
        create_range(user, agent, Range.Status.RESUMING, subnet_index=1)

        index = allocate_subnet_index()
        assert index == 2

    def test_skips_destroying_ranges(self, user, agent):
        """Destroying ranges should hold their index (still have resources)."""
        create_range(user, agent, Range.Status.DESTROYING, subnet_index=1)

        index = allocate_subnet_index()
        assert index == 2

    def test_skips_pending_ranges(self, user, agent):
        """Pending ranges should hold their index."""
        create_range(user, agent, Range.Status.PENDING, subnet_index=1)

        index = allocate_subnet_index()
        assert index == 2

    def test_raises_when_all_indices_exhausted(self, user, agent):
        """Should raise AllocationError when all 254 indices are in use."""
        # Create ranges for all 254 indices
        for i in range(1, 255):
            create_range(user, agent, Range.Status.READY, subnet_index=i)

        with pytest.raises(AllocationError) as exc_info:
            allocate_subnet_index()

        assert "254" in str(exc_info.value)  # Should mention the limit
        assert "available" in str(exc_info.value).lower()

    def test_handles_null_subnet_index(self, user, agent):
        """Ranges with null subnet_index should be ignored."""
        # Create a range with null subnet_index (edge case)
        Range.objects.create(
            user=user,
            agent=agent,
            status=Range.Status.PENDING,
            subnet_index=None,
            instance_config=[],
        )

        index = allocate_subnet_index()
        assert index == 1  # Should still return 1

    def test_returns_integer(self):
        """Verify return type is int, not string or other."""
        index = allocate_subnet_index()
        assert isinstance(index, int)

    def test_returns_within_valid_range(self, user, agent):
        """All returned indices should be between 1 and 254."""
        # Use a few indices
        create_range(user, agent, Range.Status.READY, subnet_index=1)
        create_range(user, agent, Range.Status.READY, subnet_index=2)

        index = allocate_subnet_index()
        assert 1 <= index <= 254


class TestAllocationError:
    """Tests for the AllocationError exception class."""

    def test_is_exception(self):
        """AllocationError should be an Exception."""
        error = AllocationError("Test error")
        assert isinstance(error, Exception)

    def test_message_accessible_via_str(self):
        """Error message should be accessible via str()."""
        error = AllocationError("No capacity")
        assert str(error) == "No capacity"

    def test_can_be_raised_and_caught(self):
        """Should be raisable and catchable."""
        with pytest.raises(AllocationError):
            raise AllocationError("Test")
