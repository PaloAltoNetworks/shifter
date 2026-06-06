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


class TestPauseRange:
    """Tests for pause_range() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates ownership via RangeInstance lookup
    - Delegates to engine.pause_range correctly
    - Raises CMSError when engine returns False
    """

    def test_gets_range_to_verify_ownership(self, mock_user):
        """Service fetches RangeInstance and verifies ownership."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range) as mock_get,
            patch("cms.services.engine_pause_range", return_value=True),
        ):
            services.pause_range(mock_user, 42)
            mock_get.assert_called_once_with(range_id=42)

    def test_calls_engine_pause_with_request_id(self, mock_user):
        """Service passes request_id to engine.pause_range."""
        from uuid import UUID

        from cms.models import RangeInstance

        mock_request = make_mock_request()
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = mock_request
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_pause_range", return_value=True) as mock_pause,
        ):
            services.pause_range(mock_user, 42)

            mock_pause.assert_called_once()
            call_arg = mock_pause.call_args[0][0]
            assert isinstance(call_arg, UUID)
            assert call_arg == mock_request.request_id

    def test_raises_cms_error_when_engine_returns_false(self, mock_user):
        """Service raises CMSError when engine returns False."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_pause_range", return_value=False),
            pytest.raises(CMSError, match="cannot be paused"),
        ):
            services.pause_range(mock_user, 42)

    def test_raises_cms_error_when_range_not_found(self, mock_user):
        """Service raises CMSError when range doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        with (
            patch("cms.services.RangeInstance.objects.get", side_effect=RangeInstance.DoesNotExist),
            pytest.raises(CMSError, match="not found"),
        ):
            services.pause_range(mock_user, 42)

    def test_raises_cms_error_when_not_owner(self, mock_user):
        """Service raises CMSError when user doesn't own the range."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id + 1)  # Different user
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            pytest.raises(CMSError, match="not found"),
        ):
            services.pause_range(mock_user, 42)

    def test_sets_status_to_pausing_before_engine_call(self, mock_user):
        """Service sets CMS status to PAUSING before calling engine."""
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        statuses_at_engine_call = []

        def capture_status(request_id):
            statuses_at_engine_call.append(mock_range.status)
            return True

        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_pause_range", side_effect=capture_status),
        ):
            services.pause_range(mock_user, 42)

        assert statuses_at_engine_call == [ResourceStatus.PAUSING.value]

    def test_reverts_status_to_ready_when_engine_returns_false(self, mock_user):
        """Service reverts CMS status to READY when engine returns False."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_pause_range", return_value=False),
            pytest.raises(CMSError, match="cannot be paused"),
        ):
            services.pause_range(mock_user, 42)

        assert mock_range.status == ResourceStatus.READY.value


class TestResumeRange:
    """Tests for resume_range() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates ownership via RangeInstance lookup
    - Delegates to engine.resume_range correctly
    - Raises CMSError when engine returns False
    """

    def test_gets_range_to_verify_ownership(self, mock_user):
        """Service fetches RangeInstance and verifies ownership."""
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range) as mock_get,
            patch("cms.services.engine_resume_range", return_value=True),
        ):
            services.resume_range(mock_user, 42)
            mock_get.assert_called_once_with(range_id=42)

    def test_calls_engine_resume_with_request_id(self, mock_user):
        """Service passes request_id to engine.resume_range."""
        from uuid import UUID

        from cms.models import RangeInstance

        mock_request = make_mock_request()
        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = mock_request
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_resume_range", return_value=True) as mock_resume,
        ):
            services.resume_range(mock_user, 42)

            mock_resume.assert_called_once()
            call_arg = mock_resume.call_args[0][0]
            assert isinstance(call_arg, UUID)
            assert call_arg == mock_request.request_id

    def test_raises_cms_error_when_engine_returns_false(self, mock_user):
        """Service raises CMSError when engine returns False."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_resume_range", return_value=False),
            pytest.raises(CMSError, match="cannot be resumed"),
        ):
            services.resume_range(mock_user, 42)

    def test_raises_cms_error_when_range_not_found(self, mock_user):
        """Service raises CMSError when range doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        with (
            patch("cms.services.RangeInstance.objects.get", side_effect=RangeInstance.DoesNotExist),
            pytest.raises(CMSError, match="not found"),
        ):
            services.resume_range(mock_user, 42)

    def test_raises_cms_error_when_not_owner(self, mock_user):
        """Service raises CMSError when user doesn't own the range."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id + 1)  # Different user
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            pytest.raises(CMSError, match="not found"),
        ):
            services.resume_range(mock_user, 42)

    def test_sets_status_to_resuming_before_engine_call(self, mock_user):
        """Service sets CMS status to RESUMING before calling engine."""
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        statuses_at_engine_call = []

        def capture_status(request_id):
            statuses_at_engine_call.append(mock_range.status)
            return True

        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_resume_range", side_effect=capture_status),
        ):
            services.resume_range(mock_user, 42)

        assert statuses_at_engine_call == [ResourceStatus.RESUMING.value]

    def test_reverts_status_to_paused_when_engine_returns_false(self, mock_user):
        """Service reverts CMS status to PAUSED when engine returns False."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=RangeInstance, range_id=42, user_id=mock_user.id)
        mock_range.request = make_mock_request()
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=mock_range),
            patch("cms.services.engine_resume_range", return_value=False),
            pytest.raises(CMSError, match="cannot be resumed"),
        ):
            services.resume_range(mock_user, 42)

        assert mock_range.status == ResourceStatus.PAUSED.value


class TestPauseRangeByRequestId:
    """Tests for pause_range_by_request_id() service function."""

    def test_calls_engine_with_request_id(self, mock_user):
        """Service passes request_id to engine.pause_range."""
        from cms.models import RangeInstance

        request_id = uuid4()
        mock_request = make_mock_request(request_id)
        mock_range = Mock(spec=RangeInstance, user_id=mock_user.id)
        mock_range.request = mock_request
        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            patch("cms.services.engine_pause_range", return_value=True) as mock_pause,
        ):
            mock_filter.return_value.first.return_value = mock_range
            services.pause_range_by_request_id(mock_user, str(request_id))

            mock_pause.assert_called_once_with(request_id)

    def test_sets_status_to_pausing_before_engine_call(self, mock_user):
        """Service sets CMS status to PAUSING before calling engine."""
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        request_id = uuid4()
        mock_request = make_mock_request(request_id)
        mock_range = Mock(spec=RangeInstance, user_id=mock_user.id)
        mock_range.request = mock_request
        statuses_at_engine_call = []

        def capture_status(req_id):
            statuses_at_engine_call.append(mock_range.status)
            return True

        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            patch("cms.services.engine_pause_range", side_effect=capture_status),
        ):
            mock_filter.return_value.first.return_value = mock_range
            services.pause_range_by_request_id(mock_user, str(request_id))

        assert statuses_at_engine_call == [ResourceStatus.PAUSING.value]

    def test_reverts_status_to_ready_when_engine_returns_false(self, mock_user):
        """Service reverts CMS status to READY when engine returns False."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        request_id = uuid4()
        mock_request = make_mock_request(request_id)
        mock_range = Mock(spec=RangeInstance, user_id=mock_user.id)
        mock_range.request = mock_request
        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            patch("cms.services.engine_pause_range", return_value=False),
            pytest.raises(CMSError, match="cannot be paused"),
        ):
            mock_filter.return_value.first.return_value = mock_range
            services.pause_range_by_request_id(mock_user, str(request_id))

        assert mock_range.status == ResourceStatus.READY.value

    def test_raises_cms_error_when_not_found(self, mock_user):
        """Service raises CMSError when range not found."""
        from cms.exceptions import CMSError

        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            pytest.raises(CMSError, match="not found"),
        ):
            mock_filter.return_value.first.return_value = None
            services.pause_range_by_request_id(mock_user, str(uuid4()))


class TestResumeRangeByRequestId:
    """Tests for resume_range_by_request_id() service function."""

    def test_calls_engine_with_request_id(self, mock_user):
        """Service passes request_id to engine.resume_range."""
        from cms.models import RangeInstance

        request_id = uuid4()
        mock_request = make_mock_request(request_id)
        mock_range = Mock(spec=RangeInstance, user_id=mock_user.id)
        mock_range.request = mock_request
        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            patch("cms.services.engine_resume_range", return_value=True) as mock_resume,
        ):
            mock_filter.return_value.first.return_value = mock_range
            services.resume_range_by_request_id(mock_user, str(request_id))

            mock_resume.assert_called_once_with(request_id)

    def test_sets_status_to_resuming_before_engine_call(self, mock_user):
        """Service sets CMS status to RESUMING before calling engine."""
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        request_id = uuid4()
        mock_request = make_mock_request(request_id)
        mock_range = Mock(spec=RangeInstance, user_id=mock_user.id)
        mock_range.request = mock_request
        statuses_at_engine_call = []

        def capture_status(req_id):
            statuses_at_engine_call.append(mock_range.status)
            return True

        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            patch("cms.services.engine_resume_range", side_effect=capture_status),
        ):
            mock_filter.return_value.first.return_value = mock_range
            services.resume_range_by_request_id(mock_user, str(request_id))

        assert statuses_at_engine_call == [ResourceStatus.RESUMING.value]

    def test_reverts_status_to_paused_when_engine_returns_false(self, mock_user):
        """Service reverts CMS status to PAUSED when engine returns False."""
        from cms.exceptions import CMSError
        from cms.models import RangeInstance
        from shared.enums import ResourceStatus

        request_id = uuid4()
        mock_request = make_mock_request(request_id)
        mock_range = Mock(spec=RangeInstance, user_id=mock_user.id)
        mock_range.request = mock_request
        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            patch("cms.services.engine_resume_range", return_value=False),
            pytest.raises(CMSError, match="cannot be resumed"),
        ):
            mock_filter.return_value.first.return_value = mock_range
            services.resume_range_by_request_id(mock_user, str(request_id))

        assert mock_range.status == ResourceStatus.PAUSED.value

    def test_raises_cms_error_when_not_found(self, mock_user):
        """Service raises CMSError when range not found."""
        from cms.exceptions import CMSError

        with (
            patch("cms.services.RangeInstance.objects.filter") as mock_filter,
            pytest.raises(CMSError, match="not found"),
        ):
            mock_filter.return_value.first.return_value = None
            services.resume_range_by_request_id(mock_user, str(uuid4()))
