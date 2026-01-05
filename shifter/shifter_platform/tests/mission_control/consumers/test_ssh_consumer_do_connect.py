"""Tests for SSHConsumer._do_connect.

Tests the internal connection handler that performs authentication,
ownership verification, and SSH connection establishment.

Contract being tested:
- Inputs: WebSocket scope (user, url_route with instance_uuid)
- Outputs: None (sets up ssh_conn, starts _read_task)
- Side effects:
  - Closes with NOT_AUTHENTICATED if user not authenticated
  - Closes with INVALID_REQUEST if no instance_uuid
  - Closes with NOT_FOUND if no active range
  - Closes with NOT_FOUND if range not ready
  - Closes with NOT_FOUND if instance not in range
  - Closes with PERMISSION_DENIED if PermissionError from connect_terminal
  - Closes with SSH_CONNECTION_FAILED if SSH connection fails
  - Accepts WebSocket and starts read task on success
- Errors: Various close codes for different failure modes
- Logging: Logs debug, warning, and info messages at various points
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.enums import RangeStatus, WebSocketCloseCode
from shared.schemas import InstanceContext, RangeContext


@pytest.mark.asyncio
class TestSSHConsumerDoConnectAuthentication:
    """Tests for SSHConsumer._do_connect authentication handling."""

    # -------------------------------------------------------------------------
    # Authentication - user verification
    # -------------------------------------------------------------------------

    async def test_closes_with_not_authenticated_when_user_is_none(self, ssh_consumer_factory, websocket_scope_no_user):
        """_do_connect() closes with NOT_AUTHENTICATED when user is None."""
        consumer = ssh_consumer_factory(websocket_scope_no_user)

        await consumer._do_connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_AUTHENTICATED)

    async def test_closes_with_not_authenticated_for_anonymous_user(
        self, ssh_consumer_factory, websocket_scope_unauthenticated
    ):
        """_do_connect() closes with NOT_AUTHENTICATED for AnonymousUser."""
        consumer = ssh_consumer_factory(websocket_scope_unauthenticated)

        await consumer._do_connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_AUTHENTICATED)

    async def test_logs_warning_for_unauthenticated_attempt(
        self, ssh_consumer_factory, websocket_scope_unauthenticated
    ):
        """_do_connect() logs warning for unauthenticated connection attempt."""
        consumer = ssh_consumer_factory(websocket_scope_unauthenticated)

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer._do_connect()

        mock_logger.warning.assert_called()
        call_args = str(mock_logger.warning.call_args)
        assert "Unauthenticated" in call_args or "unauthenticated" in call_args.lower()


@pytest.mark.asyncio
class TestSSHConsumerDoConnectInstanceUUID:
    """Tests for SSHConsumer._do_connect instance UUID handling."""

    # -------------------------------------------------------------------------
    # Instance UUID - URL parameter validation
    # -------------------------------------------------------------------------

    async def test_closes_with_invalid_request_when_no_instance_uuid(
        self, ssh_consumer_factory, websocket_scope_no_instance_uuid
    ):
        """_do_connect() closes with INVALID_REQUEST when instance_uuid missing."""
        consumer = ssh_consumer_factory(websocket_scope_no_instance_uuid)

        await consumer._do_connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.INVALID_REQUEST)

    async def test_sets_instance_uuid_from_url_route(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() sets instance_uuid from URL route kwargs."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
        ):
            mock_ssh = AsyncMock()
            mock_connect.return_value = mock_ssh

            await consumer._do_connect()

        assert consumer.instance_uuid == "test-instance-uuid-1234"

    async def test_logs_warning_for_missing_instance_uuid(self, ssh_consumer_factory, websocket_scope_no_instance_uuid):
        """_do_connect() logs warning when instance_uuid is missing."""
        consumer = ssh_consumer_factory(websocket_scope_no_instance_uuid)

        with patch("mission_control.consumers.logger") as mock_logger:
            await consumer._do_connect()

        mock_logger.warning.assert_called()
        call_args = str(mock_logger.warning.call_args)
        assert "instance_uuid" in call_args.lower()


@pytest.mark.asyncio
class TestSSHConsumerDoConnectRangeValidation:
    """Tests for SSHConsumer._do_connect range validation."""

    # -------------------------------------------------------------------------
    # Range lookup - CMS interaction
    # -------------------------------------------------------------------------

    async def test_closes_with_not_found_when_no_active_range(
        self, ssh_consumer_factory, websocket_scope_authenticated
    ):
        """_do_connect() closes with NOT_FOUND when user has no active range."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with patch("cms.get_active_range", return_value=None):
            await consumer._do_connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_FOUND)

    async def test_logs_warning_for_no_active_range(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_do_connect() logs warning when user has no active range."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with (
            patch("cms.get_active_range", return_value=None),
            patch("mission_control.consumers.logger") as mock_logger,
        ):
            await consumer._do_connect()

        mock_logger.warning.assert_called()
        call_args = str(mock_logger.warning.call_args)
        assert "no active range" in call_args.lower()

    async def test_closes_with_not_found_when_range_not_ready(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context_not_ready
    ):
        """_do_connect() closes with NOT_FOUND when range is not READY."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with patch("cms.get_active_range", return_value=mock_range_context_not_ready):
            await consumer._do_connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_FOUND)

    async def test_logs_warning_for_range_not_ready(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context_not_ready
    ):
        """_do_connect() logs warning when range is not ready."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with (
            patch("cms.get_active_range", return_value=mock_range_context_not_ready),
            patch("mission_control.consumers.logger") as mock_logger,
        ):
            await consumer._do_connect()

        mock_logger.warning.assert_called()
        call_args = str(mock_logger.warning.call_args)
        assert "not ready" in call_args.lower()

    async def test_sets_range_id_from_range_context(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() sets range_id from the range context."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
        ):
            mock_ssh = AsyncMock()
            mock_connect.return_value = mock_ssh

            await consumer._do_connect()

        assert consumer.range_id == 42


@pytest.mark.asyncio
class TestSSHConsumerDoConnectInstanceValidation:
    """Tests for SSHConsumer._do_connect instance validation."""

    # -------------------------------------------------------------------------
    # Instance verification - instance exists in range
    # -------------------------------------------------------------------------

    async def test_closes_with_not_found_when_instance_not_in_range(
        self, ssh_consumer_factory, websocket_scope_authenticated
    ):
        """_do_connect() closes with NOT_FOUND when instance UUID not in range."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        # Create range context with different instance UUID
        range_ctx = RangeContext(
            range_id=42,
            scenario_id="test-scenario",
            user_id=1,
            status=RangeStatus.READY,
            instances=[
                InstanceContext(
                    uuid="different-uuid",
                    role="attacker",
                    os_type="kali",
                )
            ],
        )

        with patch("cms.get_active_range", return_value=range_ctx):
            await consumer._do_connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_FOUND)

    async def test_logs_warning_for_instance_not_found(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_do_connect() logs warning when instance not found in range."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        range_ctx = RangeContext(
            range_id=42,
            scenario_id="test-scenario",
            user_id=1,
            status=RangeStatus.READY,
            instances=[
                InstanceContext(
                    uuid="different-uuid",
                    role="attacker",
                    os_type="kali",
                )
            ],
        )

        with (
            patch("cms.get_active_range", return_value=range_ctx),
            patch("mission_control.consumers.logger") as mock_logger,
        ):
            await consumer._do_connect()

        mock_logger.warning.assert_called()
        call_args = str(mock_logger.warning.call_args)
        assert "instance not found" in call_args.lower() or "not found" in call_args.lower()


@pytest.mark.asyncio
class TestSSHConsumerDoConnectSSHConnection:
    """Tests for SSHConsumer._do_connect SSH connection handling."""

    # -------------------------------------------------------------------------
    # SSH connection - engine interaction
    # -------------------------------------------------------------------------

    async def test_calls_connect_terminal_with_correct_args(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context, mock_user
    ):
        """_do_connect() calls connect_terminal with user, range_id, instance_uuid."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
        ):
            mock_ssh = AsyncMock()
            mock_connect.return_value = mock_ssh

            await consumer._do_connect()

        mock_connect.assert_called_once()
        call_args = mock_connect.call_args
        assert call_args[0][0] == mock_user  # user
        assert call_args[0][1] == 42  # range_id
        assert call_args[0][2] == "test-instance-uuid-1234"  # instance_uuid

    async def test_closes_with_permission_denied_on_permission_error(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() closes with PERMISSION_DENIED on PermissionError."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal", side_effect=PermissionError("Not allowed")),
        ):
            await consumer._do_connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.PERMISSION_DENIED)

    async def test_logs_warning_for_permission_error(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() logs warning on PermissionError."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal", side_effect=PermissionError("Not allowed")),
            patch("mission_control.consumers.logger") as mock_logger,
        ):
            await consumer._do_connect()

        mock_logger.warning.assert_called()
        call_args = str(mock_logger.warning.call_args)
        assert "permission" in call_args.lower()

    async def test_closes_with_ssh_connection_failed_on_connect_error(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() closes with SSH_CONNECTION_FAILED on connection error."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
        ):
            mock_ssh = AsyncMock()
            mock_ssh.connect.side_effect = ConnectionError("SSH failed")
            mock_connect.return_value = mock_ssh

            await consumer._do_connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.SSH_CONNECTION_FAILED)

    async def test_logs_exception_for_ssh_connection_error(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() logs exception on SSH connection error."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
            patch("mission_control.consumers.logger") as mock_logger,
        ):
            mock_ssh = AsyncMock()
            mock_ssh.connect.side_effect = Exception("SSH failed")
            mock_connect.return_value = mock_ssh

            await consumer._do_connect()

        mock_logger.exception.assert_called_once()


@pytest.mark.asyncio
class TestSSHConsumerDoConnectSuccess:
    """Tests for SSHConsumer._do_connect success path."""

    # -------------------------------------------------------------------------
    # Success path - full connection flow
    # -------------------------------------------------------------------------

    async def test_accepts_websocket_on_success(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() accepts WebSocket connection on success."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
        ):
            mock_ssh = AsyncMock()
            mock_connect.return_value = mock_ssh

            await consumer._do_connect()

        consumer.accept.assert_awaited_once()

    async def test_sets_ssh_conn_on_success(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() sets ssh_conn attribute on success."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
        ):
            mock_ssh = AsyncMock()
            mock_connect.return_value = mock_ssh

            await consumer._do_connect()

        assert consumer.ssh_conn is mock_ssh

    async def test_starts_read_task_on_success(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() creates background read task on success."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._read_ssh_output = AsyncMock()

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
            patch("asyncio.create_task") as mock_create_task,
        ):
            mock_ssh = AsyncMock()
            mock_connect.return_value = mock_ssh
            mock_create_task.return_value = MagicMock()

            await consumer._do_connect()

        mock_create_task.assert_called_once()

    async def test_sets_read_task_on_success(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() sets _read_task attribute on success."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._read_ssh_output = AsyncMock()

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
            patch("asyncio.create_task") as mock_create_task,
        ):
            mock_ssh = AsyncMock()
            mock_connect.return_value = mock_ssh
            mock_task = MagicMock()
            mock_create_task.return_value = mock_task

            await consumer._do_connect()

        assert consumer._read_task is mock_task

    async def test_logs_info_on_successful_connection(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() logs INFO on successful connection."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._read_ssh_output = AsyncMock()

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
            patch("asyncio.create_task"),
            patch("mission_control.consumers.logger") as mock_logger,
        ):
            mock_ssh = AsyncMock()
            mock_connect.return_value = mock_ssh

            await consumer._do_connect()

        mock_logger.info.assert_called()
        call_args = str(mock_logger.info.call_args)
        assert "connected" in call_args.lower()

    async def test_does_not_close_on_success(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() does not close WebSocket on success."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._read_ssh_output = AsyncMock()

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
            patch("asyncio.create_task"),
        ):
            mock_ssh = AsyncMock()
            mock_connect.return_value = mock_ssh

            await consumer._do_connect()

        consumer.close.assert_not_awaited()


@pytest.mark.asyncio
class TestSSHConsumerDoConnectLogging:
    """Tests for SSHConsumer._do_connect logging behavior."""

    # -------------------------------------------------------------------------
    # Logging - debug messages
    # -------------------------------------------------------------------------

    async def test_logs_debug_on_connection_requested(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() logs DEBUG when terminal connection is requested."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._read_ssh_output = AsyncMock()

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
            patch("asyncio.create_task"),
            patch("mission_control.consumers.logger") as mock_logger,
        ):
            mock_ssh = AsyncMock()
            mock_connect.return_value = mock_ssh

            await consumer._do_connect()

        # Should have debug call early in the flow
        mock_logger.debug.assert_called()
        debug_calls = [str(call) for call in mock_logger.debug.call_args_list]
        assert any("connection requested" in call.lower() or "terminal" in call.lower() for call in debug_calls)


@pytest.mark.asyncio
class TestSSHConsumerDoConnectEdgeCases:
    """Tests for SSHConsumer._do_connect edge cases."""

    # -------------------------------------------------------------------------
    # Edge cases - various boundary conditions
    # -------------------------------------------------------------------------

    async def test_handles_multiple_instances_finds_correct_one(
        self, ssh_consumer_factory, websocket_scope_authenticated
    ):
        """_do_connect() finds correct instance among multiple instances."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._read_ssh_output = AsyncMock()

        range_ctx = RangeContext(
            range_id=42,
            scenario_id="test-scenario",
            user_id=1,
            status=RangeStatus.READY,
            instances=[
                InstanceContext(uuid="other-uuid-1", role="victim", os_type="windows"),
                InstanceContext(uuid="test-instance-uuid-1234", role="attacker", os_type="kali"),
                InstanceContext(uuid="other-uuid-2", role="dc", os_type="windows"),
            ],
        )

        with (
            patch("cms.get_active_range", return_value=range_ctx),
            patch("engine.connect_terminal") as mock_connect,
            patch("asyncio.create_task"),
        ):
            mock_ssh = AsyncMock()
            mock_connect.return_value = mock_ssh

            await consumer._do_connect()

        # Should succeed - instance was found
        consumer.accept.assert_awaited_once()
        consumer.close.assert_not_awaited()

    async def test_handles_empty_instances_list(self, ssh_consumer_factory, websocket_scope_authenticated):
        """_do_connect() closes with NOT_FOUND when instances list is empty."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)

        range_ctx = RangeContext(
            range_id=42,
            scenario_id="test-scenario",
            user_id=1,
            status=RangeStatus.READY,
            instances=[],
        )

        with patch("cms.get_active_range", return_value=range_ctx):
            await consumer._do_connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_FOUND)

    async def test_calls_ssh_connect_method(
        self, ssh_consumer_factory, websocket_scope_authenticated, mock_range_context
    ):
        """_do_connect() calls connect() on the SSH connection object."""
        consumer = ssh_consumer_factory(websocket_scope_authenticated)
        consumer._read_ssh_output = AsyncMock()

        with (
            patch("cms.get_active_range", return_value=mock_range_context),
            patch("engine.connect_terminal") as mock_connect,
            patch("asyncio.create_task"),
        ):
            mock_ssh = AsyncMock()
            mock_connect.return_value = mock_ssh

            await consumer._do_connect()

        mock_ssh.connect.assert_awaited_once()
