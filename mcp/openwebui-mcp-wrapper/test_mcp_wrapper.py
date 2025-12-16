"""
Unit tests for mcp_wrapper.py

Uses mocks to test the Tools class without requiring mcp-shifter or OAuth.
Tests the standard MCP protocol flow: initialize -> notifications/initialized -> tools/*
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from mcp_wrapper import Tools


@pytest.fixture
def tools():
    """Create a fresh Tools instance for each test."""
    return Tools()


@pytest.fixture
def valid_oauth_token():
    """Valid OAuth token fixture."""
    return {
        "access_token": "test-access-token-12345",
        "id_token": "test-id-token",
        "token_type": "Bearer"
    }


@pytest.fixture
def mock_event_emitter():
    """Mock event emitter that tracks calls."""
    return AsyncMock()


class TestGetMcpHeaders:
    """Tests for _get_mcp_headers method."""

    def test_valid_token_returns_headers(self, tools, valid_oauth_token):
        headers = tools._get_mcp_headers(valid_oauth_token)

        assert headers["Authorization"] == "Bearer test-access-token-12345"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json, text/event-stream"

    def test_includes_session_id_when_set(self, tools, valid_oauth_token):
        tools._mcp_session_id = "session-abc-123"
        headers = tools._get_mcp_headers(valid_oauth_token)

        assert headers["mcp-session-id"] == "session-abc-123"

    def test_no_session_id_header_when_not_set(self, tools, valid_oauth_token):
        headers = tools._get_mcp_headers(valid_oauth_token)

        assert "mcp-session-id" not in headers

    def test_none_token_raises_error(self, tools):
        with pytest.raises(ValueError, match="Not authenticated"):
            tools._get_mcp_headers(None)

    def test_empty_token_raises_error(self, tools):
        with pytest.raises(ValueError, match="Not authenticated"):
            tools._get_mcp_headers({})

    def test_token_without_access_token_raises_error(self, tools):
        with pytest.raises(ValueError, match="Not authenticated"):
            tools._get_mcp_headers({"id_token": "some-id"})


class TestEnsureInitialized:
    """Tests for _ensure_initialized method."""

    @pytest.mark.asyncio
    async def test_sends_initialize_request(self, tools, valid_oauth_token, mock_event_emitter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"mcp-session-id": "session-123"}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "mcp-shifter", "version": "0.1.0"}
            }
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            await tools._ensure_initialized(valid_oauth_token, mock_event_emitter)

        assert tools._mcp_session_id == "session-123"
        assert tools._session_token == "test-access-token-12345"

        # Verify initialize request was sent
        first_call = mock_client.post.call_args_list[0]
        assert first_call[0][0].endswith("/mcp")
        payload = first_call[1]["json"]
        assert payload["method"] == "initialize"
        assert payload["params"]["protocolVersion"] == "2024-11-05"

        # Verify initialized notification was sent
        second_call = mock_client.post.call_args_list[1]
        assert second_call[1]["json"]["method"] == "notifications/initialized"

    @pytest.mark.asyncio
    async def test_reuses_existing_session(self, tools, valid_oauth_token):
        # Pre-set session
        tools._mcp_session_id = "existing-session"
        tools._session_token = "test-access-token-12345"

        with patch("httpx.AsyncClient") as mock_client_class:
            await tools._ensure_initialized(valid_oauth_token)

        # Should not have made any HTTP calls
        mock_client_class.assert_not_called()
        assert tools._mcp_session_id == "existing-session"

    @pytest.mark.asyncio
    async def test_creates_new_session_if_token_changed(self, tools, valid_oauth_token):
        # Pre-set session with different token
        tools._mcp_session_id = "old-session"
        tools._session_token = "different-token"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"mcp-session-id": "new-session"}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2024-11-05"}
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            await tools._ensure_initialized(valid_oauth_token)

        assert tools._mcp_session_id == "new-session"

    @pytest.mark.asyncio
    async def test_handles_401_unauthorized(self, tools, valid_oauth_token):
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(PermissionError, match="Authentication failed"):
                await tools._ensure_initialized(valid_oauth_token)

    @pytest.mark.asyncio
    async def test_handles_404_no_range(self, tools, valid_oauth_token):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {
            "error": "no_active_range",
            "message": "No active range found"
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ValueError, match="No active range found"):
                await tools._ensure_initialized(valid_oauth_token)

    @pytest.mark.asyncio
    async def test_handles_429_session_limit(self, tools, valid_oauth_token):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.json.return_value = {
            "error": "session_limit_reached",
            "sessionsActive": 500,
            "sessionsMax": 500
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(RuntimeError, match="Session limit reached"):
                await tools._ensure_initialized(valid_oauth_token)

    @pytest.mark.asyncio
    async def test_handles_connection_error(self, tools, valid_oauth_token):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ConnectionError, match="Cannot connect to MCP server"):
                await tools._ensure_initialized(valid_oauth_token)

    @pytest.mark.asyncio
    async def test_handles_timeout(self, tools, valid_oauth_token):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.TimeoutException("Timeout")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(TimeoutError, match="timed out"):
                await tools._ensure_initialized(valid_oauth_token)

    @pytest.mark.asyncio
    async def test_handles_missing_session_id_header(self, tools, valid_oauth_token):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}  # No mcp-session-id header
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(RuntimeError, match="did not return session ID"):
                await tools._ensure_initialized(valid_oauth_token)

    @pytest.mark.asyncio
    async def test_emits_status_events(self, tools, valid_oauth_token, mock_event_emitter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"mcp-session-id": "session-123"}
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            await tools._ensure_initialized(valid_oauth_token, mock_event_emitter)

        # Should have emitted connecting and connected status
        assert mock_event_emitter.call_count == 2

        first_call = mock_event_emitter.call_args_list[0][0][0]
        assert first_call["type"] == "status"
        assert first_call["data"]["done"] is False

        second_call = mock_event_emitter.call_args_list[1][0][0]
        assert second_call["type"] == "status"
        assert second_call["data"]["done"] is True


class TestCallMcp:
    """Tests for _call_mcp method."""

    @pytest.mark.asyncio
    async def test_makes_jsonrpc_call(self, tools, valid_oauth_token):
        # Pre-set session
        tools._mcp_session_id = "session-123"
        tools._session_token = "test-access-token-12345"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": []}
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await tools._call_mcp("tools/list", None, valid_oauth_token)

        assert result["result"]["tools"] == []

        # Verify the call was made correctly - now uses /mcp with session ID header
        call_args = mock_client.post.call_args
        assert call_args[0][0].endswith("/mcp")
        assert call_args[1]["headers"]["mcp-session-id"] == "session-123"
        assert call_args[1]["json"]["method"] == "tools/list"
        assert call_args[1]["json"]["jsonrpc"] == "2.0"

    @pytest.mark.asyncio
    async def test_includes_params_when_provided(self, tools, valid_oauth_token):
        tools._mcp_session_id = "session-123"
        tools._session_token = "test-access-token-12345"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            await tools._call_mcp(
                "tools/call",
                {"name": "test_tool", "arguments": {"arg1": "value1"}},
                valid_oauth_token
            )

        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["params"]["name"] == "test_tool"

    @pytest.mark.asyncio
    async def test_retries_on_session_expired(self, tools, valid_oauth_token):
        tools._mcp_session_id = "old-session"
        tools._session_token = "test-access-token-12345"

        # First call returns 404 (session expired)
        mock_404_response = MagicMock()
        mock_404_response.status_code = 404
        mock_404_response.json.return_value = {
            "error": "session_not_found",
            "message": "Session not found"
        }

        # Initialize response for new session
        mock_init_response = MagicMock()
        mock_init_response.status_code = 200
        mock_init_response.headers = {"mcp-session-id": "new-session"}
        mock_init_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {}}

        # Notification response (no body needed)
        mock_notify_response = MagicMock()
        mock_notify_response.status_code = 202

        # Success response after re-init
        mock_success_response = MagicMock()
        mock_success_response.status_code = 200
        mock_success_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            # First call 404, then init, notify, then retry succeeds
            mock_client.post.side_effect = [
                mock_404_response,
                mock_init_response,
                mock_notify_response,
                mock_success_response
            ]
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await tools._call_mcp("tools/list", None, valid_oauth_token)

        assert result["result"] == {}
        assert tools._mcp_session_id == "new-session"

    @pytest.mark.asyncio
    async def test_handles_403_forbidden(self, tools, valid_oauth_token):
        tools._mcp_session_id = "session-123"
        tools._session_token = "test-access-token-12345"

        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(PermissionError, match="Access denied"):
                await tools._call_mcp("tools/list", None, valid_oauth_token)


class TestListMcpTools:
    """Tests for list_mcp_tools method."""

    @pytest.mark.asyncio
    async def test_returns_formatted_tool_list(self, tools, valid_oauth_token):
        tools._mcp_session_id = "session-123"
        tools._session_token = "test-access-token-12345"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "run_command", "description": "Run a shell command"},
                    {"name": "nmap_scan", "description": "Run nmap scan"}
                ]
            }
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await tools.list_mcp_tools(__oauth_token__=valid_oauth_token)

        assert "**Available MCP Tools:**" in result
        assert "**run_command**" in result
        assert "Run a shell command" in result
        assert "**nmap_scan**" in result

    @pytest.mark.asyncio
    async def test_handles_empty_tool_list(self, tools, valid_oauth_token):
        tools._mcp_session_id = "session-123"
        tools._session_token = "test-access-token-12345"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": []}
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await tools.list_mcp_tools(__oauth_token__=valid_oauth_token)

        assert "No MCP tools available" in result

    @pytest.mark.asyncio
    async def test_returns_error_message_on_failure(self, tools, valid_oauth_token):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await tools.list_mcp_tools(__oauth_token__=valid_oauth_token)

        assert "Error:" in result
        assert "Cannot connect" in result


class TestRunMcpTool:
    """Tests for run_mcp_tool method."""

    @pytest.mark.asyncio
    async def test_executes_tool_with_arguments(self, tools, valid_oauth_token, mock_event_emitter):
        tools._mcp_session_id = "session-123"
        tools._session_token = "test-access-token-12345"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {"type": "text", "text": "Command output here"}
                ]
            }
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await tools.run_mcp_tool(
                tool_name="run_command",
                arguments='{"command": "whoami"}',
                __oauth_token__=valid_oauth_token,
                __event_emitter__=mock_event_emitter
            )

        assert result == "Command output here"

        # Verify correct params sent
        call_args = mock_client.post.call_args
        params = call_args[1]["json"]["params"]
        assert params["name"] == "run_command"
        assert params["arguments"]["command"] == "whoami"

    @pytest.mark.asyncio
    async def test_handles_invalid_json_arguments(self, tools, valid_oauth_token):
        result = await tools.run_mcp_tool(
            tool_name="run_command",
            arguments="not valid json",
            __oauth_token__=valid_oauth_token
        )

        assert "Error: Invalid JSON" in result

    @pytest.mark.asyncio
    async def test_handles_empty_arguments(self, tools, valid_oauth_token):
        tools._mcp_session_id = "session-123"
        tools._session_token = "test-access-token-12345"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": []}
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await tools.run_mcp_tool(
                tool_name="list_files",
                arguments="",
                __oauth_token__=valid_oauth_token
            )

        assert "no output" in result.lower()

    @pytest.mark.asyncio
    async def test_handles_tool_error_response(self, tools, valid_oauth_token):
        tools._mcp_session_id = "session-123"
        tools._session_token = "test-access-token-12345"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32000,
                "message": "Tool execution failed: command not found"
            }
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await tools.run_mcp_tool(
                tool_name="bad_command",
                arguments="{}",
                __oauth_token__=valid_oauth_token
            )

        assert "Tool execution failed" in result
        assert "command not found" in result

    @pytest.mark.asyncio
    async def test_handles_multiple_content_blocks(self, tools, valid_oauth_token):
        tools._mcp_session_id = "session-123"
        tools._session_token = "test-access-token-12345"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {"type": "text", "text": "Line 1"},
                    {"type": "text", "text": "Line 2"},
                    {"type": "resource", "uri": "file:///tmp/output.txt"}
                ]
            }
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await tools.run_mcp_tool(
                tool_name="complex_output",
                arguments="{}",
                __oauth_token__=valid_oauth_token
            )

        assert "Line 1" in result
        assert "Line 2" in result
        assert "[Resource:" in result

    @pytest.mark.asyncio
    async def test_emits_status_events(self, tools, valid_oauth_token, mock_event_emitter):
        tools._mcp_session_id = "session-123"
        tools._session_token = "test-access-token-12345"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "done"}]}
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            await tools.run_mcp_tool(
                tool_name="test_tool",
                arguments="{}",
                __oauth_token__=valid_oauth_token,
                __event_emitter__=mock_event_emitter
            )

        # Should emit "Executing..." and "Completed" status events
        assert mock_event_emitter.call_count == 2

        first_call = mock_event_emitter.call_args_list[0][0][0]
        assert "Executing test_tool" in first_call["data"]["description"]

        second_call = mock_event_emitter.call_args_list[1][0][0]
        assert "Completed test_tool" in second_call["data"]["description"]


class TestValves:
    """Tests for Valves configuration."""

    def test_default_values(self, tools):
        assert tools.valves.mcp_server_url == "http://mcp-shifter:3001"
        assert tools.valves.request_timeout == 30

    def test_custom_values(self):
        tools = Tools()
        tools.valves.mcp_server_url = "http://custom-server:8080"
        tools.valves.request_timeout = 60

        assert tools.valves.mcp_server_url == "http://custom-server:8080"
        assert tools.valves.request_timeout == 60


class TestProtocolConstants:
    """Tests for MCP protocol constants."""

    def test_protocol_version(self, tools):
        assert tools.MCP_PROTOCOL_VERSION == "2024-11-05"

    def test_client_info(self, tools):
        assert tools.CLIENT_NAME == "shifter-openwebui-wrapper"
        # Don't test version - it changes with releases
