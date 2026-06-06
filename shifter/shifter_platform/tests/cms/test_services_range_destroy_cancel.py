"""CMS service interface tests.

Tests service-level behavior only:
- Expected behavior / return values
- Exception handling
- Input validation (service's responsibility)

Does NOT re-test model behavior (filtering, field validation, etc).
"""

from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest

from cms import services
from tests.conftest import INVALID_RANGE_IDS, INVALID_USERS


def make_mock_request(request_id: UUID | None = None) -> Mock:
    """Create a mock Request object with request_id attribute."""
    mock_request = Mock()
    mock_request.request_id = request_id or uuid4()
    return mock_request


def _make_mock_agent(*, pk, name, os_slug, s3_key, original_filename, sha256_hash):
    """Create a mock agent with attributes the service accesses."""
    mock_os = Mock()
    mock_os.slug = os_slug
    agent = Mock()
    agent.pk = pk
    agent.id = pk
    agent.name = name
    agent.os = mock_os
    agent.s3_key = s3_key
    agent.original_filename = original_filename
    agent.sha256_hash = sha256_hash
    return agent


@pytest.fixture
def mock_user():
    user = Mock()
    user.pk = 42
    user.id = 42
    user.email = "test@example.com"
    return user


@pytest.fixture
def mock_windows_agent():
    """Mock Windows agent for testing."""
    return _make_mock_agent(
        pk=10,
        name="Windows Agent",
        os_slug="windows",
        s3_key="agents/123/agent.msi",
        original_filename="cortex_agent.msi",
        sha256_hash="abc123def456",
    )


@pytest.fixture
def mock_linux_agent():
    """Mock Linux agent for testing."""
    return _make_mock_agent(
        pk=20,
        name="Linux Agent",
        os_slug="linux-debian",
        s3_key="agents/456/agent.deb",
        original_filename="cortex_agent.deb",
        sha256_hash="def789ghi012",
    )


@pytest.fixture
def create_range_ctx(mock_user, mock_windows_agent):
    """Fixture providing common mocks for create_range tests.

    Mocks all ORM access so tests run without a database.
    Yields a dict of mock objects; ExitStack is auto-closed on teardown.
    """
    from contextlib import ExitStack

    from shared.schemas import (
        AgentDetails,
        InstanceSpec,
        RangeSpec,
        SubnetSpec,
    )

    mock_template = Mock()
    mock_template.get_agent_requirements.return_value = {
        "requires_windows": False,
        "requires_linux": False,
        "has_from_agent": True,
    }
    mock_template.ngfw = False

    attacker_spec = InstanceSpec(
        name="Attacker",
        uuid=str(uuid4()),
        role="attacker",
        os_type="kali",
    )
    victim_spec = InstanceSpec(
        name="Victim",
        uuid=str(uuid4()),
        role="victim",
        os_type="windows",
        agent=AgentDetails(
            s3_key=mock_windows_agent.s3_key,
            filename=mock_windows_agent.original_filename,
            sha256=mock_windows_agent.sha256_hash,
        ),
    )
    canned_range_spec = RangeSpec(
        uuid=str(uuid4()),
        scenario_id="basic",
        user_id=mock_user.id,
        subnets=[
            SubnetSpec(
                name="default",
                uuid=str(uuid4()),
                instances=[attacker_spec, victim_spec],
                connected_to=[],
            )
        ],
        ngfw=False,
    )

    mock_request = Mock()
    mock_request.request_id = uuid4()
    mock_ri = Mock()

    with ExitStack() as stack:
        mocks = {}
        mocks["active_range"] = stack.enter_context(patch("cms.services.get_active_range", return_value=None))
        mocks["load_scenario"] = stack.enter_context(
            patch("cms.scenarios.registry.load_scenario_template", return_value=mock_template)
        )
        mocks["get_agent"] = stack.enter_context(patch("cms.services.get_agent", return_value=mock_windows_agent))
        mocks["hydrate"] = stack.enter_context(
            patch("cms.scenarios.hydrator.hydrate_scenario", return_value=canned_range_spec)
        )
        mocks["request_create"] = stack.enter_context(
            patch("cms.models.Request.objects.create", return_value=mock_request)
        )
        mocks["engine"] = stack.enter_context(patch("cms.services.engine_create_range"))
        mocks["ri_create"] = stack.enter_context(
            patch("cms.services.RangeInstance.objects.create", return_value=mock_ri)
        )
        mocks["audit"] = stack.enter_context(patch("cms.services.audit_log"))
        mocks["range_spec"] = canned_range_spec
        yield mocks


class TestDestroyRange:
    """Tests for destroy_range() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates ownership via get_range
    - Delegates to engine.orchestration.destroy correctly
    - Returns None (void function)
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service validates ownership and delegates correctly
    # -------------------------------------------------------------------------

    def test_gets_range_to_verify_ownership(self, mock_user):
        """Service fetches RangeInstance and verifies ownership."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range) as mock_get,
            patch("cms.services.engine_destroy_range_by_request"),
        ):
            services.destroy_range(mock_user, 42)
            mock_get.assert_called_once_with(range_id=42)

    def test_updates_status_to_destroying(self, mock_user):
        """Service sets status to DESTROYING and soft deletes before calling engine."""
        from django.utils import timezone

        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()

        mock_now = timezone.now()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_destroy_range_by_request"),
            patch("django.utils.timezone.now", return_value=mock_now),
        ):
            services.destroy_range(mock_user, 42)

            # Verify status was set to DESTROYING
            assert mock_range.status == ResourceStatus.DESTROYING.value
            # Verify deleted_at was set (soft delete)
            assert mock_range.deleted_at == mock_now
            # Verify save was called with both fields
            mock_range.save.assert_called_once_with(update_fields=["status", "deleted_at"])

    def test_calls_engine_destroy_with_request_id(self, mock_user):
        """Service passes request_id (not RangeContext) to engine."""
        from uuid import UUID

        from cms.models import RangeInstance

        mock_request = make_mock_request()
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = mock_request
        mock_range.save = Mock()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_destroy_range_by_request") as mock_destroy,
        ):
            services.destroy_range(mock_user, 42)

            # Verify engine was called with request_id
            mock_destroy.assert_called_once()
            call_arg = mock_destroy.call_args[0][0]
            assert isinstance(call_arg, UUID)
            assert call_arg == mock_request.request_id

    # -------------------------------------------------------------------------
    # Service returns None (void function)
    # -------------------------------------------------------------------------

    def test_returns_none_on_success(self, mock_user):
        """Service returns None on successful destruction."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_destroy_range_by_request"),
        ):
            result = services.destroy_range(mock_user, 42)
            assert result is None

    # -------------------------------------------------------------------------
    # Error handling - CMSError for ownership failures
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_range_not_found(self, mock_user):
        """Service raises CMSError when range doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        with (
            patch(
                "cms.services.RangeInstance.objects.get",
                side_effect=RangeInstance.DoesNotExist,
            ),
            pytest.raises(CMSError, match="Range 999 not found"),
        ):
            services.destroy_range(mock_user, 999)

    def test_raises_cms_error_when_not_owner(self, mock_user):
        """Service raises CMSError when user doesn't own range."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        # Create mock instance owned by different user
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=999, scenario_id="basic")
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            pytest.raises(CMSError, match="Range 42 not found"),
        ):
            services.destroy_range(mock_user, 42)

    # -------------------------------------------------------------------------
    # Error propagation - engine service errors
    # -------------------------------------------------------------------------

    @pytest.mark.parametrize(
        "exc_class,exc_msg",
        [
            pytest.param("EngineError", "No range to destroy", id="engine-error"),
            pytest.param("Exception", "DB connection failed", id="unexpected"),
        ],
    )
    def test_propagates_error(self, mock_user, exc_class, exc_msg):
        """Service propagates errors from engine service."""
        from cms.models import RangeInstance
        from engine import EngineError

        exc_type = EngineError if exc_class == "EngineError" else Exception
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_destroy_range_by_request", side_effect=exc_type(exc_msg)),
            pytest.raises(exc_type, match=exc_msg),
        ):
            services.destroy_range(mock_user, 42)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.destroy_range(range_id=42)

    @pytest.mark.parametrize("invalid_user", INVALID_USERS)
    def test_raises_on_invalid_user(self, invalid_user):
        """Service raises error for invalid user values."""
        with pytest.raises((TypeError, ValueError, AttributeError)):
            services.destroy_range(invalid_user, 42)

    # -------------------------------------------------------------------------
    # Input validation - range_id parameter
    # -------------------------------------------------------------------------

    def test_requires_range_id_argument(self, mock_user):
        """Service raises TypeError if range_id not provided."""
        with pytest.raises(TypeError):
            services.destroy_range(mock_user)

    @pytest.mark.parametrize("invalid_range_id", INVALID_RANGE_IDS)
    def test_raises_on_invalid_range_id(self, mock_user, invalid_range_id):
        """Service raises error for invalid range_id values."""
        with pytest.raises((TypeError, ValueError)):
            services.destroy_range(mock_user, invalid_range_id)


class TestCancelRange:
    """Tests for cancel_range() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates ownership via get_range
    - Updates status to DESTROYED before calling engine
    - Passes RangeContext to engine (not range_id)
    - Returns None (void function)
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service validates ownership and updates status
    # -------------------------------------------------------------------------

    def test_gets_range_to_verify_ownership(self, mock_user):
        """Service calls get_range to verify ownership."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch.object(services, "get_range", return_value=mock_range) as mock_get,
            patch("cms.services.engine_cancel_range_by_request"),
        ):
            services.cancel_range(mock_user, 42)
            mock_get.assert_called_once_with(mock_user, 42)

    def test_updates_status_to_destroyed(self, mock_user):
        """Service sets status to DESTROYED before calling engine."""
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range_by_request"),
        ):
            services.cancel_range(mock_user, 42)

            # Verify status was set
            assert mock_range.status == ResourceStatus.DESTROYED.value
            # Verify save was called with update_fields
            mock_range.save.assert_called_once_with(update_fields=["status"])

    def test_calls_engine_cancel_with_request_id(self, mock_user):
        """Service passes request_id (not RangeContext) to engine."""
        from uuid import UUID

        from cms.models import RangeInstance

        mock_request = make_mock_request()
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = mock_request
        mock_range.save = Mock()
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range_by_request") as mock_cancel,
        ):
            services.cancel_range(mock_user, 42)

            # Verify engine was called with request_id
            mock_cancel.assert_called_once()
            call_arg = mock_cancel.call_args[0][0]
            assert isinstance(call_arg, UUID)
            assert call_arg == mock_request.request_id

    # -------------------------------------------------------------------------
    # Service returns None (void function)
    # -------------------------------------------------------------------------

    def test_returns_none_on_success(self, mock_user):
        """Service returns None on successful cancellation."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range_by_request"),
        ):
            result = services.cancel_range(mock_user, 42)
            assert result is None

    # -------------------------------------------------------------------------
    # Error handling - CMSError for ownership failures
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_range_not_found(self, mock_user):
        """Service raises CMSError when range doesn't exist."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_range", side_effect=CMSError("not found")),
            pytest.raises(CMSError),
        ):
            services.cancel_range(mock_user, 999)

    def test_raises_cms_error_when_not_owner(self, mock_user):
        """Service raises CMSError when user doesn't own range (via get_range)."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_range", side_effect=CMSError("access denied")),
            pytest.raises(CMSError),
        ):
            services.cancel_range(mock_user, 42)

    # -------------------------------------------------------------------------
    # Error propagation - engine service errors
    # -------------------------------------------------------------------------

    @pytest.mark.parametrize(
        "exc_class,exc_msg",
        [
            pytest.param("EngineError", "Cannot cancel range", id="engine-error"),
            pytest.param("Exception", "DB connection failed", id="unexpected"),
        ],
    )
    def test_propagates_error(self, mock_user, exc_class, exc_msg):
        """Service propagates errors from engine service."""
        from cms.models import RangeInstance
        from engine import EngineError

        exc_type = EngineError if exc_class == "EngineError" else Exception
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = make_mock_request()
        mock_range.save = Mock()
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range_by_request", side_effect=exc_type(exc_msg)),
            pytest.raises(exc_type, match=exc_msg),
        ):
            services.cancel_range(mock_user, 42)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.cancel_range(range_id=42)

    @pytest.mark.parametrize("invalid_user", INVALID_USERS)
    def test_raises_on_invalid_user(self, invalid_user):
        """Service raises error for invalid user values."""
        with pytest.raises((TypeError, ValueError, AttributeError)):
            services.cancel_range(invalid_user, 42)

    # -------------------------------------------------------------------------
    # Input validation - range_id parameter
    # -------------------------------------------------------------------------

    def test_requires_range_id_argument(self, mock_user):
        """Service raises TypeError if range_id not provided."""
        with pytest.raises(TypeError):
            services.cancel_range(mock_user)

    @pytest.mark.parametrize("invalid_range_id", INVALID_RANGE_IDS)
    def test_raises_on_invalid_range_id(self, mock_user, invalid_range_id):
        """Service raises error for invalid range_id values."""
        with pytest.raises((TypeError, ValueError)):
            services.cancel_range(mock_user, invalid_range_id)

    # -------------------------------------------------------------------------
    # Audit log (#694)
    # -------------------------------------------------------------------------

    def test_audits_cancel_action(self, mock_user):
        """Service records an AuditLog CANCEL entry on successful cancel."""
        from cms.models import RangeInstance
        from risk_register.models import AuditLog as AuditLogModel
        from shared.enums import ResourceStatus

        mock_request = make_mock_request()
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id, scenario_id="basic")
        mock_range.agent = None
        mock_range.request = mock_request
        mock_range.save = Mock()
        with (
            patch.object(services, "get_range", return_value=mock_range),
            patch("cms.services.engine_cancel_range_by_request"),
            patch("cms.services.audit_log") as mock_audit,
        ):
            services.cancel_range(mock_user, 42)

        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["entity_type"] == AuditLogModel.EntityType.RANGE
        assert kwargs["entity_id"] == 42
        assert kwargs["action"] == AuditLogModel.Action.CANCEL
        assert kwargs["actor_id"] == mock_user.id
        assert kwargs["previous_state"]["scenario"] == "basic"
        assert kwargs["previous_state"]["status"] == ResourceStatus.DESTROYED.value
