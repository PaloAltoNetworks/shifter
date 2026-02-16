"""Integration tests for range lifecycle operations.

Tests engine service functions with real database operations.
AWS services (ECS, Secrets Manager) are mocked as they require infrastructure.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model

from engine.models import Range, Request
from engine.services import (
    cancel_range,
    cancel_range_by_request,
    destroy_range,
    destroy_range_by_request,
    get_range_status,
    get_rdp_connection_info,
)
from shared.enums import RequestType, ResourceStatus
from shared.schemas import RangeContext

User = get_user_model()


def make_range_context(
    range_id: int | None = None,
    request_id=None,
    user_id: int = 1,
    status: str = "ready",
) -> RangeContext:
    """Create a valid RangeContext with all required fields."""
    import uuid as uuid_module

    return RangeContext(
        request_id=request_id or uuid_module.uuid4(),
        range_id=range_id,
        scenario_id="test_scenario",
        user_id=user_id,
        status=ResourceStatus(status),
        instances=[],
    )


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser@example.com",
        email="testuser@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_user(db):
    """Create another test user for ownership tests."""
    return User.objects.create_user(
        username="otheruser@example.com",
        email="otheruser@example.com",
        password="otherpass123",
    )


@pytest.fixture
def request_obj(db, user):
    """Create a test Request."""
    return Request.objects.create(
        request_id=uuid.uuid4(),
        request_type=RequestType.RANGE.value,
        user=user,
    )


@pytest.fixture
def range_ready(db, user, request_obj):
    """Create a ready range with provisioned instances."""
    return Range.objects.create(
        uuid=uuid.uuid4(),
        user=user,
        request=request_obj,
        status=Range.Status.READY,
        subnet_index=1,
        provisioned_instances=[
            {
                "uuid": "attacker-uuid-123",
                "role": "attacker",
                "os_type": "kali",
                "private_ip": "10.1.1.10",
                "ssh_key_secret_arn": ("arn:aws:secretsmanager:us-east-2:123:secret:key"),
            },
            {
                "uuid": "victim-uuid-456",
                "role": "victim",
                "os_type": "windows",
                "private_ip": "10.1.1.20",
                "ssh_key_secret_arn": ("arn:aws:secretsmanager:us-east-2:123:secret:key2"),
            },
        ],
    )


@pytest.fixture
def range_pending(db, user, request_obj):
    """Create a pending range."""
    return Range.objects.create(
        uuid=uuid.uuid4(),
        user=user,
        request=request_obj,
        status=Range.Status.PENDING,
        subnet_index=2,
    )


@pytest.fixture
def range_provisioning(db, user):
    """Create a provisioning range without request (legacy pattern)."""
    return Range.objects.create(
        uuid=uuid.uuid4(),
        user=user,
        status=Range.Status.PROVISIONING,
        subnet_index=3,
    )


# =============================================================================
# get_range_status integration tests
# =============================================================================


@pytest.mark.django_db
class TestGetRangeStatusIntegration:
    """Integration tests for get_range_status with real DB."""

    def test_returns_status_for_existing_range(self, range_ready):
        """get_range_status returns correct data from database."""
        result = get_range_status(range_ready.id)

        assert result is not None
        assert result["status"] == "ready"
        assert result["error_message"] == ""
        assert len(result["instances"]) == 2

    def test_returns_none_for_nonexistent_range(self):
        """get_range_status returns None for missing range."""
        result = get_range_status(99999)
        assert result is None

    def test_returns_instances_with_correct_structure(self, range_ready):
        """get_range_status returns instance data with expected fields."""
        result = get_range_status(range_ready.id)

        instances = result["instances"]
        attacker = next(i for i in instances if i["role"] == "attacker")

        assert attacker["uuid"] == "attacker-uuid-123"
        assert attacker["os_type"] == "kali"
        assert attacker["private_ip"] == "10.1.1.10"

    def test_returns_empty_instances_when_not_provisioned(self, range_pending):
        """get_range_status returns empty list when no instances."""
        result = get_range_status(range_pending.id)

        assert result["status"] == "pending"
        assert result["instances"] == []

    def test_returns_timestamps_in_iso_format(self, range_ready):
        """get_range_status returns timestamps in ISO format."""
        result = get_range_status(range_ready.id)

        assert result["created_at"] is not None
        # ISO format should contain T separator
        assert "T" in result["created_at"]


# =============================================================================
# destroy_range integration tests
# =============================================================================


@pytest.mark.django_db
class TestDestroyRangeIntegration:
    """Integration tests for destroy_range with real DB."""

    def test_sets_status_to_destroying(self, range_ready):
        """destroy_range updates status in database."""
        context = make_range_context(
            range_id=range_ready.id,
            request_id=range_ready.request.request_id,
            user_id=range_ready.user.id,
            status=range_ready.status,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("engine.ecs.start_teardown", lambda *args: None)
            result = destroy_range(context)

        assert result is True

        # Verify DB was updated
        range_ready.refresh_from_db()
        assert range_ready.status == Range.Status.DESTROYING

    def test_returns_false_for_nonexistent_range(self):
        """destroy_range returns False for missing range."""
        context = make_range_context(range_id=99999, user_id=1, status="ready")

        result = destroy_range(context)
        assert result is False

    def test_returns_false_for_already_destroyed(self, user, request_obj):
        """destroy_range returns False when already destroyed."""
        range_obj = Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            request=request_obj,
            status=Range.Status.DESTROYED,
            subnet_index=10,
        )

        context = make_range_context(
            range_id=range_obj.id,
            request_id=range_obj.request.request_id,
            user_id=user.id,
            status=range_obj.status,
        )

        result = destroy_range(context)
        assert result is False

    def test_returns_true_for_already_destroying(self, user, request_obj):
        """destroy_range is idempotent when already destroying."""
        range_obj = Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            request=request_obj,
            status=Range.Status.DESTROYING,
            subnet_index=11,
        )

        context = make_range_context(
            range_id=range_obj.id,
            request_id=range_obj.request.request_id,
            user_id=user.id,
            status=range_obj.status,
        )

        result = destroy_range(context)
        assert result is True

    def test_delegates_to_request_id_when_range_id_none(self, range_ready):
        """destroy_range delegates to destroy_range_by_request."""
        context = make_range_context(
            range_id=None,
            request_id=range_ready.request.request_id,
            user_id=range_ready.user.id,
            status=range_ready.status,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("engine.ecs.start_range_teardown", lambda *args: None)
            result = destroy_range(context)

        assert result is True

        range_ready.refresh_from_db()
        assert range_ready.status == Range.Status.DESTROYING


# =============================================================================
# cancel_range integration tests
# =============================================================================


@pytest.mark.django_db
class TestCancelRangeIntegration:
    """Integration tests for cancel_range with real DB."""

    def test_cancels_pending_range(self, range_pending):
        """cancel_range sets DESTROYING status for PENDING range."""
        context = make_range_context(
            range_id=range_pending.id,
            request_id=range_pending.request.request_id,
            user_id=range_pending.user.id,
            status=range_pending.status,
        )

        cancel_range(context)

        range_pending.refresh_from_db()
        assert range_pending.status == Range.Status.DESTROYING

    def test_cancels_provisioning_range(self, range_provisioning):
        """cancel_range sets DESTROYING status for PROVISIONING range."""
        context = make_range_context(
            range_id=range_provisioning.id,
            user_id=range_provisioning.user.id,
            status=range_provisioning.status,
        )

        cancel_range(context)

        range_provisioning.refresh_from_db()
        assert range_provisioning.status == Range.Status.DESTROYING

    def test_does_not_cancel_ready_range(self, range_ready):
        """cancel_range does not affect READY range."""
        context = make_range_context(
            range_id=range_ready.id,
            request_id=range_ready.request.request_id,
            user_id=range_ready.user.id,
            status=range_ready.status,
        )

        cancel_range(context)

        range_ready.refresh_from_db()
        assert range_ready.status == Range.Status.READY

    def test_raises_type_error_for_none_context(self):
        """cancel_range raises TypeError for None context."""
        with pytest.raises(TypeError, match="cannot be None"):
            cancel_range(None)

    def test_raises_type_error_for_invalid_context_type(self):
        """cancel_range raises TypeError for non-RangeContext."""
        with pytest.raises(TypeError, match="must be RangeContext"):
            cancel_range({"range_id": 1})

    def test_raises_validation_error_for_negative_range_id(self, user):
        """RangeContext raises ValidationError for negative range_id."""
        from pydantic import ValidationError

        # Validation happens at schema level, not in cancel_range
        with pytest.raises(ValidationError, match="range_id must be a positive"):
            make_range_context(range_id=-1, user_id=user.id, status="pending")


# =============================================================================
# Range.allocate_subnet_index integration tests
# =============================================================================


@pytest.mark.django_db(transaction=True)
class TestSubnetAllocationIntegration:
    """Integration tests for Range.allocate_subnet_index with real DB."""

    def test_allocates_first_available_index(self, user):
        """allocate_subnet_index returns 1 when no ranges exist."""
        index = Range.allocate_subnet_index()
        assert index == 1

    def test_allocates_next_index_after_existing(self, user):
        """allocate_subnet_index returns next available index."""
        Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            status=Range.Status.READY,
            subnet_index=1,
        )

        index = Range.allocate_subnet_index()
        assert index == 2

    def test_reuses_index_from_destroyed_range(self, user):
        """allocate_subnet_index reuses index from DESTROYED range."""
        Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            status=Range.Status.DESTROYED,
            subnet_index=1,
        )

        index = Range.allocate_subnet_index()
        assert index == 1

    def test_reuses_index_from_failed_range(self, user):
        """allocate_subnet_index reuses index from FAILED range."""
        Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            status=Range.Status.FAILED,
            subnet_index=1,
        )

        index = Range.allocate_subnet_index()
        assert index == 1

    def test_fills_gap_in_indices(self, user):
        """allocate_subnet_index fills gaps in index sequence."""
        Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            status=Range.Status.READY,
            subnet_index=1,
        )
        Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            status=Range.Status.READY,
            subnet_index=3,
        )

        index = Range.allocate_subnet_index()
        assert index == 2


# =============================================================================
# Range.get_active_for_user integration tests
# =============================================================================


@pytest.mark.django_db
class TestGetActiveForUserIntegration:
    """Integration tests for Range.get_active_for_user with real DB."""

    def test_returns_ready_range(self, range_ready):
        """get_active_for_user returns READY range."""
        result = Range.get_active_for_user(range_ready.user)
        assert result == range_ready

    def test_returns_pending_range(self, range_pending):
        """get_active_for_user returns PENDING range."""
        result = Range.get_active_for_user(range_pending.user)
        assert result == range_pending

    def test_returns_provisioning_range(self, range_provisioning):
        """get_active_for_user returns PROVISIONING range."""
        result = Range.get_active_for_user(range_provisioning.user)
        assert result == range_provisioning

    def test_excludes_destroyed_range(self, user):
        """get_active_for_user excludes DESTROYED ranges."""
        Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            status=Range.Status.DESTROYED,
            subnet_index=100,
        )

        result = Range.get_active_for_user(user)
        assert result is None

    def test_excludes_failed_range(self, user):
        """get_active_for_user excludes FAILED ranges."""
        Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            status=Range.Status.FAILED,
            subnet_index=101,
        )

        result = Range.get_active_for_user(user)
        assert result is None

    def test_excludes_destroying_range(self, user):
        """get_active_for_user excludes DESTROYING ranges."""
        Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            status=Range.Status.DESTROYING,
            subnet_index=102,
        )

        result = Range.get_active_for_user(user)
        assert result is None

    def test_returns_none_for_user_with_no_ranges(self, other_user):
        """get_active_for_user returns None when user has no ranges."""
        result = Range.get_active_for_user(other_user)
        assert result is None


# =============================================================================
# get_rdp_connection_info integration tests
# =============================================================================


@pytest.mark.django_db
class TestGetRdpConnectionInfoIntegration:
    """Integration tests for get_rdp_connection_info with real DB."""

    def test_returns_connection_info_for_windows_instance(self, range_ready):
        """get_rdp_connection_info returns correct info for Windows."""
        result = get_rdp_connection_info(
            user=range_ready.user,
            instance_uuid="victim-uuid-456",
        )

        assert result["private_ip"] == "10.1.1.20"
        assert result["os_type"] == "windows"
        assert result["rdp_username"] == "Administrator"
        assert "connection_name" in result

    def test_returns_connection_info_for_kali_instance(self, range_ready):
        """get_rdp_connection_info returns correct info for Kali."""
        result = get_rdp_connection_info(
            user=range_ready.user,
            instance_uuid="attacker-uuid-123",
        )

        assert result["private_ip"] == "10.1.1.10"
        assert result["os_type"] == "kali"
        assert result["rdp_username"] == "kali"

    def test_raises_for_nonexistent_instance(self, range_ready):
        """get_rdp_connection_info raises for unknown instance UUID."""
        with pytest.raises(ValueError, match="not found"):
            get_rdp_connection_info(
                user=range_ready.user,
                instance_uuid="nonexistent-uuid",
            )

    def test_raises_for_no_active_range(self, other_user):
        """get_rdp_connection_info raises when user has no active range."""
        with pytest.raises(ValueError, match="No active range"):
            get_rdp_connection_info(
                user=other_user,
                instance_uuid="any-uuid",
            )

    def test_raises_for_range_not_ready(self, range_pending):
        """get_rdp_connection_info raises when range not READY."""
        with pytest.raises(ValueError, match="not ready"):
            get_rdp_connection_info(
                user=range_pending.user,
                instance_uuid="any-uuid",
            )

    def test_returns_ubuntu_rdp_credentials(self, user, request_obj):
        """get_rdp_connection_info returns credentials for Ubuntu (has GUI via xrdp)."""
        Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            request=request_obj,
            status=Range.Status.READY,
            subnet_index=50,
            provisioned_instances=[
                {
                    "uuid": "ubuntu-uuid",
                    "role": "victim",
                    "os_type": "ubuntu",
                    "private_ip": "10.1.1.30",
                },
            ],
        )

        result = get_rdp_connection_info(user=user, instance_uuid="ubuntu-uuid")

        assert result["os_type"] == "ubuntu"
        assert result["rdp_username"] == "ubuntu"
        assert result["rdp_password"] == "ubuntu"
        assert result["private_ip"] == "10.1.1.30"

    def test_raises_for_none_user(self, range_ready):
        """get_rdp_connection_info raises for None user."""
        with pytest.raises(ValueError, match="user is required"):
            get_rdp_connection_info(user=None, instance_uuid="any-uuid")

    def test_raises_for_empty_instance_uuid(self, range_ready):
        """get_rdp_connection_info raises for empty instance_uuid."""
        with pytest.raises(ValueError, match="instance_uuid is required"):
            get_rdp_connection_info(user=range_ready.user, instance_uuid="")


# =============================================================================
# destroy_range_by_request integration tests
# =============================================================================


@pytest.mark.django_db
class TestDestroyRangeByRequestIntegration:
    """Integration tests for destroy_range_by_request with real DB."""

    def test_destroys_range_via_request_id(self, range_ready):
        """destroy_range_by_request finds and destroys range."""
        request_id = range_ready.request.request_id

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("engine.ecs.start_range_teardown", lambda *args: None)
            result = destroy_range_by_request(request_id)

        assert result is True

        range_ready.refresh_from_db()
        assert range_ready.status == Range.Status.DESTROYING

    def test_returns_false_for_unknown_request_id(self):
        """destroy_range_by_request returns False for unknown request."""
        result = destroy_range_by_request(uuid.uuid4())
        assert result is False


# =============================================================================
# cancel_range_by_request integration tests
# =============================================================================


@pytest.mark.django_db
class TestCancelRangeByRequestIntegration:
    """Integration tests for cancel_range_by_request with real DB."""

    def test_cancels_pending_range_via_request_id(self, range_pending):
        """cancel_range_by_request cancels PENDING range."""
        request_id = range_pending.request.request_id

        result = cancel_range_by_request(request_id)

        assert result is True

        range_pending.refresh_from_db()
        assert range_pending.status == Range.Status.DESTROYING

    def test_does_not_cancel_ready_range(self, range_ready):
        """cancel_range_by_request does not cancel READY range."""
        request_id = range_ready.request.request_id

        result = cancel_range_by_request(request_id)

        assert result is False

        range_ready.refresh_from_db()
        assert range_ready.status == Range.Status.READY

    def test_returns_false_for_unknown_request_id(self):
        """cancel_range_by_request returns False for unknown request."""
        result = cancel_range_by_request(uuid.uuid4())
        assert result is False
