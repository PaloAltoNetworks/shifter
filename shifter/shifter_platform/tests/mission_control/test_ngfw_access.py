"""Tests for NGFW secure access functions.

Tests cover:
- connect_ngfw_terminal() - SSH terminal connection to NGFW
- connect_terminal() NGFW fallback - when UUID not in range instances
- get_range_ngfw_context() - NGFW context for terminal page
- get_ngfw_gui_info() - GUI access info via Kali desktop
"""

import logging
from typing import Any
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def user():
    """Return a mock Django User."""
    u = Mock()
    u.id = 1
    u.email = "test@example.com"
    return u


@pytest.fixture
def ngfw_uuid():
    """Return a UUID for an NGFW instance."""
    return str(uuid4())


@pytest.fixture
def ngfw_instance(ngfw_uuid, user):
    """Return a mock engine Instance with NGFW role."""
    from engine.models import Instance

    inst = Mock(spec=Instance)
    inst.uuid = ngfw_uuid
    inst.role = Instance.Role.NGFW
    inst.status = "ready"
    inst.state = {
        "management_ip": "10.1.0.50",
        "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:test-key",
    }
    inst.spec = {"name": "test-ngfw", "ngfw_app": {"name": "My NGFW"}}
    inst.request = Mock()
    inst.request.user_id = user.id
    return inst


# ===========================================================================
# TestConnectNGFWTerminal
# ===========================================================================


@pytest.mark.django_db
class TestConnectNGFWTerminal:
    """Tests for connect_ngfw_terminal() in engine/services.py.

    Tests SERVICE behavior:
    - Looks up Instance by UUID with role=NGFW
    - Validates ownership via Request.user_id
    - Validates NGFW is ready
    - Extracts management_ip and ssh_key_secret_arn from state
    - Returns SSHConnection with admin user and no tmux
    """

    # -----------------------------------------------------------------------
    # Happy path
    # -----------------------------------------------------------------------

    def test_returns_ssh_connection_for_ready_ngfw(self, user, ngfw_uuid, ngfw_instance):
        """Returns SSHConnection configured for PAN-OS admin SSH."""
        from engine.models import Instance
        from engine.services import connect_ngfw_terminal

        mock_qs = Mock()
        mock_qs.select_related.return_value.first.return_value = ngfw_instance

        with (
            patch.object(Instance.objects, "filter", return_value=mock_qs),
            patch("engine.secrets.get_ssh_key", return_value="---PRIVATE KEY---"),
        ):
            conn = connect_ngfw_terminal(user, ngfw_uuid)

        assert conn.host == "10.1.0.50"
        assert conn.username == "admin"
        assert conn.session_id is None  # PAN-OS doesn't support tmux

    def test_calls_get_ssh_key_with_arn(self, user, ngfw_uuid, ngfw_instance):
        """Retrieves SSH key from Secrets Manager using ARN from state."""
        from engine.models import Instance
        from engine.services import connect_ngfw_terminal

        mock_qs = Mock()
        mock_qs.select_related.return_value.first.return_value = ngfw_instance

        with (
            patch.object(Instance.objects, "filter", return_value=mock_qs),
            patch("engine.secrets.get_ssh_key", return_value="---KEY---") as mock_get_key,
        ):
            connect_ngfw_terminal(user, ngfw_uuid)
            mock_get_key.assert_called_once_with(
                "arn:aws:secretsmanager:us-east-2:123:secret:test-key"
            )

    def test_filters_by_uuid_and_ngfw_role(self, user, ngfw_uuid, ngfw_instance):
        """Queries Instance with uuid and role=NGFW filter."""
        from engine.models import Instance
        from engine.services import connect_ngfw_terminal

        mock_qs = Mock()
        mock_qs.select_related.return_value.first.return_value = ngfw_instance

        with (
            patch.object(Instance.objects, "filter", return_value=mock_qs) as mock_filter,
            patch("engine.secrets.get_ssh_key", return_value="---KEY---"),
        ):
            connect_ngfw_terminal(user, ngfw_uuid)
            mock_filter.assert_called_once_with(
                uuid=ngfw_uuid, role=Instance.Role.NGFW
            )

    # -----------------------------------------------------------------------
    # Input validation
    # -----------------------------------------------------------------------

    def test_raises_value_error_when_user_is_none(self, ngfw_uuid):
        """Raises ValueError when user is None."""
        from engine.services import connect_ngfw_terminal

        with pytest.raises(ValueError, match="user is required"):
            connect_ngfw_terminal(None, ngfw_uuid)

    def test_raises_value_error_when_uuid_is_empty(self, user):
        """Raises ValueError when instance_uuid is empty."""
        from engine.services import connect_ngfw_terminal

        with pytest.raises(ValueError, match="instance_uuid is required"):
            connect_ngfw_terminal(user, "")

    # -----------------------------------------------------------------------
    # NGFW not found
    # -----------------------------------------------------------------------

    def test_raises_value_error_when_ngfw_not_found(self, user, ngfw_uuid):
        """Raises ValueError when NGFW instance doesn't exist."""
        from engine.models import Instance
        from engine.services import connect_ngfw_terminal

        mock_qs = Mock()
        mock_qs.select_related.return_value.first.return_value = None

        with (
            patch.object(Instance.objects, "filter", return_value=mock_qs),
            pytest.raises(ValueError, match="not found"),
        ):
            connect_ngfw_terminal(user, ngfw_uuid)

    # -----------------------------------------------------------------------
    # Ownership validation
    # -----------------------------------------------------------------------

    def test_raises_permission_error_for_wrong_user(self, ngfw_uuid, ngfw_instance):
        """Raises PermissionError when user doesn't own the NGFW."""
        from engine.models import Instance
        from engine.services import connect_ngfw_terminal

        other_user = Mock()
        other_user.id = 999

        mock_qs = Mock()
        mock_qs.select_related.return_value.first.return_value = ngfw_instance

        with (
            patch.object(Instance.objects, "filter", return_value=mock_qs),
            pytest.raises(PermissionError, match="does not own"),
        ):
            connect_ngfw_terminal(other_user, ngfw_uuid)

    # -----------------------------------------------------------------------
    # Status validation
    # -----------------------------------------------------------------------

    def test_raises_value_error_when_ngfw_not_ready(self, user, ngfw_uuid, ngfw_instance):
        """Raises ValueError when NGFW is not in ready status."""
        from engine.models import Instance
        from engine.services import connect_ngfw_terminal

        ngfw_instance.status = "provisioning"

        mock_qs = Mock()
        mock_qs.select_related.return_value.first.return_value = ngfw_instance

        with (
            patch.object(Instance.objects, "filter", return_value=mock_qs),
            pytest.raises(ValueError, match="not ready"),
        ):
            connect_ngfw_terminal(user, ngfw_uuid)

    # -----------------------------------------------------------------------
    # Missing state fields
    # -----------------------------------------------------------------------

    def test_raises_value_error_when_no_management_ip(self, user, ngfw_uuid, ngfw_instance):
        """Raises ValueError when management_ip is missing from state."""
        from engine.models import Instance
        from engine.services import connect_ngfw_terminal

        ngfw_instance.state = {"ssh_key_secret_arn": "arn:test"}

        mock_qs = Mock()
        mock_qs.select_related.return_value.first.return_value = ngfw_instance

        with (
            patch.object(Instance.objects, "filter", return_value=mock_qs),
            pytest.raises(ValueError, match="no management IP"),
        ):
            connect_ngfw_terminal(user, ngfw_uuid)

    def test_raises_value_error_when_no_ssh_key_arn(self, user, ngfw_uuid, ngfw_instance):
        """Raises ValueError when ssh_key_secret_arn is missing from state."""
        from engine.models import Instance
        from engine.services import connect_ngfw_terminal

        ngfw_instance.state = {"management_ip": "10.1.0.50"}

        mock_qs = Mock()
        mock_qs.select_related.return_value.first.return_value = ngfw_instance

        with (
            patch.object(Instance.objects, "filter", return_value=mock_qs),
            pytest.raises(ValueError, match="no SSH key"),
        ):
            connect_ngfw_terminal(user, ngfw_uuid)

    # -----------------------------------------------------------------------
    # Logging
    # -----------------------------------------------------------------------

    def test_logs_info_on_successful_connection(
        self, user, ngfw_uuid, ngfw_instance, caplog
    ):
        """Logs info with connection details on success."""
        from engine.models import Instance
        from engine.services import connect_ngfw_terminal

        mock_qs = Mock()
        mock_qs.select_related.return_value.first.return_value = ngfw_instance

        with (
            patch.object(Instance.objects, "filter", return_value=mock_qs),
            patch("engine.secrets.get_ssh_key", return_value="---KEY---"),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            connect_ngfw_terminal(user, ngfw_uuid)

        assert "10.1.0.50" in caplog.text
        assert "admin" in caplog.text

    def test_logs_warning_when_not_found(self, user, ngfw_uuid, caplog):
        """Logs warning when NGFW instance is not found."""
        from engine.models import Instance
        from engine.services import connect_ngfw_terminal

        mock_qs = Mock()
        mock_qs.select_related.return_value.first.return_value = None

        with (
            patch.object(Instance.objects, "filter", return_value=mock_qs),
            caplog.at_level(logging.WARNING, logger="engine"),
            pytest.raises(ValueError),
        ):
            connect_ngfw_terminal(user, ngfw_uuid)

        assert "not found" in caplog.text


# ===========================================================================
# TestConnectTerminalNGFWFallback
# ===========================================================================


@pytest.mark.django_db
class TestConnectTerminalNGFWFallback:
    """Tests for connect_terminal() NGFW fallback behavior.

    When a UUID is not found in any Range.provisioned_instances,
    connect_terminal() should fall back to connect_ngfw_terminal().
    """

    def test_falls_back_to_ngfw_when_uuid_not_in_range(
        self, user, ngfw_uuid, ngfw_instance
    ):
        """Calls connect_ngfw_terminal when UUID not found in range instances."""
        from engine.models import Instance, Range
        from engine.services import connect_terminal

        mock_qs = Mock()
        mock_qs.select_related.return_value.first.return_value = ngfw_instance

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=None))),
            patch.object(Instance.objects, "filter", return_value=mock_qs),
            patch("engine.secrets.get_ssh_key", return_value="---KEY---"),
        ):
            conn = connect_terminal(user, ngfw_uuid)

        assert conn.host == "10.1.0.50"
        assert conn.username == "admin"

    def test_raises_value_error_when_not_in_range_or_ngfw(self, user):
        """Raises ValueError when UUID is neither in range nor NGFW."""
        from engine.models import Instance, Range
        from engine.services import connect_terminal

        unknown_uuid = str(uuid4())

        mock_instance_qs = Mock()
        mock_instance_qs.select_related.return_value.first.return_value = None

        with (
            patch.object(Range.objects, "filter", return_value=Mock(first=Mock(return_value=None))),
            patch.object(Instance.objects, "filter", return_value=mock_instance_qs),
            pytest.raises(ValueError),
        ):
            connect_terminal(user, unknown_uuid)


# ===========================================================================
# TestGetRangeNGFWContext
# ===========================================================================


@pytest.mark.django_db
class TestGetRangeNGFWContext:
    """Tests for get_range_ngfw_context() in engine/services.py.

    Tests SERVICE behavior:
    - Returns NGFW context dict when range has a ready NGFW
    - Returns None when no active range or no NGFW
    - Extracts name from spec
    - Includes management_ip from state
    """

    # -----------------------------------------------------------------------
    # Happy path
    # -----------------------------------------------------------------------

    def test_returns_ngfw_context_for_ready_range_with_ngfw(self, user, ngfw_instance):
        """Returns dict with NGFW info when range has a ready NGFW."""
        from engine.models import Range
        from engine.services import get_range_ngfw_context

        mock_range = Mock(spec=Range)
        mock_range.id = 1
        mock_range.status = Range.Status.READY
        mock_range.ngfw_instance = ngfw_instance

        with patch.object(Range, "get_active_for_user", return_value=mock_range):
            result = get_range_ngfw_context(user)

        assert result is not None
        assert result["uuid"] == str(ngfw_instance.uuid)
        assert result["role"] == "ngfw"
        assert result["os_type"] == "panos"
        assert result["management_ip"] == "10.1.0.50"

    def test_extracts_name_from_ngfw_app_spec(self, user, ngfw_instance):
        """Extracts NGFW name from spec.ngfw_app.name."""
        from engine.models import Range
        from engine.services import get_range_ngfw_context

        mock_range = Mock(spec=Range)
        mock_range.id = 1
        mock_range.status = Range.Status.READY
        mock_range.ngfw_instance = ngfw_instance

        with patch.object(Range, "get_active_for_user", return_value=mock_range):
            result = get_range_ngfw_context(user)

        assert result["name"] == "My NGFW"

    def test_falls_back_to_instance_name_when_no_ngfw_app(self, user, ngfw_instance):
        """Uses spec.name when spec.ngfw_app is not present."""
        from engine.models import Range
        from engine.services import get_range_ngfw_context

        ngfw_instance.spec = {"name": "Fallback Name"}

        mock_range = Mock(spec=Range)
        mock_range.id = 1
        mock_range.status = Range.Status.READY
        mock_range.ngfw_instance = ngfw_instance

        with patch.object(Range, "get_active_for_user", return_value=mock_range):
            result = get_range_ngfw_context(user)

        assert result["name"] == "Fallback Name"

    def test_defaults_to_ngfw_when_no_spec(self, user, ngfw_instance):
        """Uses 'NGFW' when spec is None."""
        from engine.models import Range
        from engine.services import get_range_ngfw_context

        ngfw_instance.spec = None

        mock_range = Mock(spec=Range)
        mock_range.id = 1
        mock_range.status = Range.Status.READY
        mock_range.ngfw_instance = ngfw_instance

        with patch.object(Range, "get_active_for_user", return_value=mock_range):
            result = get_range_ngfw_context(user)

        assert result["name"] == "NGFW"

    # -----------------------------------------------------------------------
    # Returns None
    # -----------------------------------------------------------------------

    def test_returns_none_when_user_is_none(self):
        """Returns None when user is None."""
        from engine.services import get_range_ngfw_context

        assert get_range_ngfw_context(None) is None

    def test_returns_none_when_no_active_range(self, user):
        """Returns None when user has no active range."""
        from engine.models import Range
        from engine.services import get_range_ngfw_context

        with patch.object(Range, "get_active_for_user", return_value=None):
            assert get_range_ngfw_context(user) is None

    def test_returns_none_when_range_not_ready(self, user):
        """Returns None when active range is not READY."""
        from engine.models import Range
        from engine.services import get_range_ngfw_context

        mock_range = Mock(spec=Range)
        mock_range.status = Range.Status.PROVISIONING

        with patch.object(Range, "get_active_for_user", return_value=mock_range):
            assert get_range_ngfw_context(user) is None

    def test_returns_none_when_range_has_no_ngfw(self, user):
        """Returns None when range has no NGFW attached."""
        from engine.models import Range
        from engine.services import get_range_ngfw_context

        mock_range = Mock(spec=Range)
        mock_range.id = 1
        mock_range.status = Range.Status.READY
        mock_range.ngfw_instance = None

        with patch.object(Range, "get_active_for_user", return_value=mock_range):
            assert get_range_ngfw_context(user) is None

    def test_returns_none_when_ngfw_not_ready(self, user, ngfw_instance):
        """Returns None when NGFW is not in ready status."""
        from engine.models import Range
        from engine.services import get_range_ngfw_context

        ngfw_instance.status = "stopped"

        mock_range = Mock(spec=Range)
        mock_range.id = 1
        mock_range.status = Range.Status.READY
        mock_range.ngfw_instance = ngfw_instance

        with patch.object(Range, "get_active_for_user", return_value=mock_range):
            assert get_range_ngfw_context(user) is None


# ===========================================================================
# TestGetNGFWGuiInfo
# ===========================================================================


@pytest.mark.django_db
class TestGetNGFWGuiInfo:
    """Tests for get_ngfw_gui_info() in engine/services.py.

    Tests SERVICE behavior:
    - Looks up NGFW via App UUID
    - Validates ownership
    - Returns management_ip and Kali connection info
    - Requires active range with Kali instance
    """

    @pytest.fixture
    def app_id(self):
        """Return a UUID for an NGFW CMS App."""
        return str(uuid4())

    @pytest.fixture
    def ngfw_app(self, app_id, ngfw_instance):
        """Return a mock engine App with NGFW type."""
        from engine.models import App

        app = Mock(spec=App)
        app.uuid = app_id
        app.app_type = App.AppType.NGFW
        app.instance = ngfw_instance
        return app

    @pytest.fixture
    def ready_range(self):
        """Return a mock Range with Kali instance."""
        from engine.models import Range

        range_obj = Mock(spec=Range)
        range_obj.status = Range.Status.READY
        range_obj.get_instance_by_role.return_value = {
            "uuid": str(uuid4()),
            "private_ip": "10.1.5.10",
            "role": "attacker",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:kali-key",
        }
        return range_obj

    # -----------------------------------------------------------------------
    # Happy path
    # -----------------------------------------------------------------------

    def test_returns_gui_info_with_management_ip_and_kali(
        self, user, app_id, ngfw_app, ready_range
    ):
        """Returns dict with management_ip and Kali connection info."""
        from engine.models import App, Range
        from engine.services import get_ngfw_gui_info

        mock_app_qs = Mock()
        mock_app_qs.select_related.return_value.first.return_value = ngfw_app

        with (
            patch.object(App.objects, "filter", return_value=mock_app_qs),
            patch.object(Range, "get_active_for_user", return_value=ready_range),
            patch("engine.secrets.get_ssh_key", return_value="---KALI-KEY---"),
        ):
            result = get_ngfw_gui_info(user, app_id)

        assert result["management_ip"] == "10.1.0.50"
        assert result["kali_ip"] == "10.1.5.10"
        assert result["kali_ssh_key"] == "---KALI-KEY---"
        assert "connection_name" in result

    # -----------------------------------------------------------------------
    # Input validation
    # -----------------------------------------------------------------------

    def test_raises_value_error_when_user_is_none(self, app_id):
        """Raises ValueError when user is None."""
        from engine.services import get_ngfw_gui_info

        with pytest.raises(ValueError, match="user is required"):
            get_ngfw_gui_info(None, app_id)

    def test_raises_value_error_when_app_id_is_empty(self, user):
        """Raises ValueError when app_id is empty."""
        from engine.services import get_ngfw_gui_info

        with pytest.raises(ValueError, match="app_id is required"):
            get_ngfw_gui_info(user, "")

    # -----------------------------------------------------------------------
    # NGFW not found
    # -----------------------------------------------------------------------

    def test_raises_value_error_when_ngfw_app_not_found(self, user, app_id):
        """Raises ValueError when NGFW App doesn't exist."""
        from engine.models import App
        from engine.services import get_ngfw_gui_info

        mock_app_qs = Mock()
        mock_app_qs.select_related.return_value.first.return_value = None

        with (
            patch.object(App.objects, "filter", return_value=mock_app_qs),
            pytest.raises(ValueError, match="not found"),
        ):
            get_ngfw_gui_info(user, app_id)

    # -----------------------------------------------------------------------
    # Ownership
    # -----------------------------------------------------------------------

    def test_raises_permission_error_for_wrong_user(self, app_id, ngfw_app):
        """Raises PermissionError when user doesn't own the NGFW."""
        from engine.models import App
        from engine.services import get_ngfw_gui_info

        other_user = Mock()
        other_user.id = 999

        mock_app_qs = Mock()
        mock_app_qs.select_related.return_value.first.return_value = ngfw_app

        with (
            patch.object(App.objects, "filter", return_value=mock_app_qs),
            pytest.raises(PermissionError),
        ):
            get_ngfw_gui_info(other_user, app_id)

    # -----------------------------------------------------------------------
    # No active range
    # -----------------------------------------------------------------------

    def test_raises_value_error_when_no_active_range(self, user, app_id, ngfw_app):
        """Raises ValueError when user has no active range."""
        from engine.models import App, Range
        from engine.services import get_ngfw_gui_info

        mock_app_qs = Mock()
        mock_app_qs.select_related.return_value.first.return_value = ngfw_app

        with (
            patch.object(App.objects, "filter", return_value=mock_app_qs),
            patch.object(Range, "get_active_for_user", return_value=None),
            pytest.raises(ValueError, match="No active range"),
        ):
            get_ngfw_gui_info(user, app_id)

    # -----------------------------------------------------------------------
    # No Kali instance
    # -----------------------------------------------------------------------

    def test_raises_value_error_when_no_kali_instance(
        self, user, app_id, ngfw_app, ready_range
    ):
        """Raises ValueError when range has no attacker (Kali) instance."""
        from engine.models import App, Range
        from engine.services import get_ngfw_gui_info

        ready_range.get_instance_by_role.return_value = None

        mock_app_qs = Mock()
        mock_app_qs.select_related.return_value.first.return_value = ngfw_app

        with (
            patch.object(App.objects, "filter", return_value=mock_app_qs),
            patch.object(Range, "get_active_for_user", return_value=ready_range),
            pytest.raises(ValueError, match="No Kali"),
        ):
            get_ngfw_gui_info(user, app_id)


# ===========================================================================
# TestContextProcessorNGFW
# ===========================================================================


@pytest.mark.django_db
class TestContextProcessorNGFW:
    """Tests for NGFW integration in the active_range context processor."""

    @pytest.fixture
    def mock_request(self, user):
        """Return a mock HttpRequest with authenticated user."""
        request = Mock()
        request.user = user
        request.user.is_authenticated = True
        return request

    @pytest.fixture
    def range_context(self):
        """Return a mock RangeContext with instances."""
        from shared.schemas import InstanceContext, RangeContext

        return RangeContext(
            request_id=uuid4(),
            range_id=1,
            user_id=1,
            scenario_id="test-scenario",
            status="ready",
            instances=[
                InstanceContext(
                    uuid=str(uuid4()),
                    name="attacker-kali",
                    role="attacker",
                    os_type="kali",
                ),
            ],
        )

    def test_appends_ngfw_to_instances_when_ready(
        self, mock_request, range_context
    ):
        """Adds NGFW InstanceContext to range instances when NGFW is ready."""
        from mission_control.context_processors import active_range

        ngfw_uuid = str(uuid4())
        ngfw_info = {
            "uuid": ngfw_uuid,
            "name": "Test NGFW",
            "role": "ngfw",
            "os_type": "panos",
            "management_ip": "10.1.0.50",
        }

        with (
            patch("mission_control.context_processors.get_active_range", return_value=range_context),
            patch("mission_control.context_processors.get_scenario", return_value={"name": "Test"}),
            patch("engine.services.get_range_ngfw_context", return_value=ngfw_info),
        ):
            ctx = active_range(mock_request)

        # Should have 2 instances: attacker + NGFW
        assert len(ctx["active_range"].instances) == 2
        ngfw_inst = ctx["active_range"].instances[-1]
        assert ngfw_inst.role == "ngfw"
        assert ngfw_inst.os_type == "panos"
        assert ngfw_inst.uuid == ngfw_uuid

    def test_includes_ngfw_management_ip_in_context(
        self, mock_request, range_context
    ):
        """Includes ngfw_management_ip in template context."""
        from mission_control.context_processors import active_range

        ngfw_info = {
            "uuid": str(uuid4()),
            "name": "Test NGFW",
            "role": "ngfw",
            "os_type": "panos",
            "management_ip": "10.1.0.50",
        }

        with (
            patch("mission_control.context_processors.get_active_range", return_value=range_context),
            patch("mission_control.context_processors.get_scenario", return_value={"name": "Test"}),
            patch("engine.services.get_range_ngfw_context", return_value=ngfw_info),
        ):
            ctx = active_range(mock_request)

        assert ctx["ngfw_management_ip"] == "10.1.0.50"

    def test_no_ngfw_when_range_has_no_ngfw(
        self, mock_request, range_context
    ):
        """Does not add NGFW when get_range_ngfw_context returns None."""
        from mission_control.context_processors import active_range

        with (
            patch("mission_control.context_processors.get_active_range", return_value=range_context),
            patch("mission_control.context_processors.get_scenario", return_value={"name": "Test"}),
            patch("engine.services.get_range_ngfw_context", return_value=None),
        ):
            ctx = active_range(mock_request)

        assert len(ctx["active_range"].instances) == 1
        assert ctx["ngfw_management_ip"] is None

    def test_ngfw_connection_url_included(
        self, mock_request, range_context
    ):
        """NGFW gets a WebSocket terminal URL in connection_urls."""
        from mission_control.context_processors import active_range

        ngfw_uuid = str(uuid4())
        ngfw_info = {
            "uuid": ngfw_uuid,
            "name": "Test NGFW",
            "role": "ngfw",
            "os_type": "panos",
            "management_ip": "10.1.0.50",
        }

        with (
            patch("mission_control.context_processors.get_active_range", return_value=range_context),
            patch("mission_control.context_processors.get_scenario", return_value={"name": "Test"}),
            patch("engine.services.get_range_ngfw_context", return_value=ngfw_info),
        ):
            ctx = active_range(mock_request)

        # connection_urls should include the NGFW
        ngfw_urls = [u for u in ctx["connection_urls"] if u["uuid"] == ngfw_uuid]
        assert len(ngfw_urls) == 1
        assert f"/ws/terminal/{ngfw_uuid}/" in ngfw_urls[0]["terminal_url"]

    def test_returns_ngfw_management_ip_none_when_no_range(self, mock_request):
        """Returns ngfw_management_ip=None when no active range."""
        from mission_control.context_processors import active_range

        with patch("mission_control.context_processors.get_active_range", return_value=None):
            ctx = active_range(mock_request)

        assert ctx["ngfw_management_ip"] is None
