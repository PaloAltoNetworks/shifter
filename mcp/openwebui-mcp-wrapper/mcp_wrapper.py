"""
title: Shifter MCP Tools
author: Shifter Team
author_url: https://github.com/paloaltonetworks/shifter
description: Execute MCP tools on your Shifter Kali range. Enables AI-driven pentesting through the Shifter cyber range platform.
required_open_webui_version: 0.6.31
requirements: httpx>=0.25.0
version: 0.5.0
licence: MIT
"""

import json
from typing import Optional
from pydantic import BaseModel, Field

import httpx


class Tools:
    """
    OpenWebUI Tool wrapper for Shifter MCP integration.

    Forwards the user's OAuth token to mcp-shifter to enable per-user
    MCP sessions scoped to their active Kali range.

    Uses standard MCP protocol:
    1. Send 'initialize' request to create session
    2. Send 'notifications/initialized' to complete handshake
    3. Use mcp-session-id header for subsequent requests
    """

    # MCP protocol version
    MCP_PROTOCOL_VERSION = "2024-11-05"
    CLIENT_NAME = "shifter-openwebui-wrapper"
    CLIENT_VERSION = "0.5.0"

    def __init__(self):
        self.valves = self.Valves()
        self._mcp_session_id: Optional[str] = None
        self._session_token: Optional[str] = None  # Track which token created the session

    class Valves(BaseModel):
        """Admin-configurable settings for the MCP wrapper."""
        mcp_server_url: str = Field(
            default="http://mcp-shifter:3001",
            description="URL of the mcp-shifter server"
        )
        request_timeout: int = Field(
            default=30,
            description="Timeout in seconds for MCP requests"
        )

    def _get_mcp_headers(self, oauth_token: Optional[dict]) -> dict:
        """
        Build headers required by MCP Streamable HTTP transport.

        The Accept header is required for the transport to work correctly.
        """
        if not oauth_token or "access_token" not in oauth_token:
            raise ValueError("Not authenticated. Please log in via SSO.")

        headers = {
            "Authorization": f"Bearer {oauth_token['access_token']}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        # Include session ID if we have one
        if self._mcp_session_id:
            headers["mcp-session-id"] = self._mcp_session_id

        return headers

    async def _send_initialized_notification(
        self,
        oauth_token: Optional[dict],
        client
    ) -> None:
        """
        Send notifications/initialized after successful initialize.

        This completes the MCP handshake per protocol spec.
        """
        headers = self._get_mcp_headers(oauth_token)
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }

        # Notifications don't expect a response body
        await client.post(
            f"{self.valves.mcp_server_url}/mcp",
            headers=headers,
            json=payload
        )

    async def _ensure_initialized(
        self,
        oauth_token: Optional[dict],
        __event_emitter__=None
    ) -> None:
        """
        Ensure we have an initialized MCP session.

        Sends MCP initialize request if needed, which creates the session
        on the server and returns a session ID in the response header.
        """
        access_token = oauth_token.get("access_token") if oauth_token else None

        # Reuse existing session if token matches
        if self._mcp_session_id and self._session_token == access_token:
            return

        # Reset state for new initialization
        self._mcp_session_id = None
        self._session_token = None

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {
                    "description": "Connecting to your Kali range...",
                    "done": False
                }
            })

        # Build headers without session ID (this is the initialize request)
        if not oauth_token or "access_token" not in oauth_token:
            raise ValueError("Not authenticated. Please log in via SSO.")

        headers = {
            "Authorization": f"Bearer {oauth_token['access_token']}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        # MCP initialize request per protocol spec
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": self.MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": self.CLIENT_NAME,
                    "version": self.CLIENT_VERSION
                }
            }
        }

        async with httpx.AsyncClient(timeout=self.valves.request_timeout) as client:
            try:
                response = await client.post(
                    f"{self.valves.mcp_server_url}/mcp",
                    headers=headers,
                    json=payload
                )
            except httpx.ConnectError:
                raise ConnectionError(
                    "Cannot connect to MCP server. The Shifter service may be "
                    "temporarily unavailable. Please try again in a few minutes."
                )
            except httpx.TimeoutException:
                raise TimeoutError(
                    "Connection to MCP server timed out. Please try again."
                )

            if response.status_code == 401:
                raise PermissionError(
                    "Authentication failed. Your session may have expired. "
                    "Please refresh the page and log in again."
                )

            if response.status_code == 404:
                data = response.json()
                if data.get("error") == "no_active_range":
                    raise ValueError(
                        "No active range found. Please launch a range from the "
                        "Shifter portal before using MCP tools."
                    )
                raise ValueError(f"Resource not found: {data.get('message', 'Unknown error')}")

            if response.status_code == 429:
                data = response.json()
                raise RuntimeError(
                    f"Session limit reached ({data.get('sessionsActive', '?')}/{data.get('sessionsMax', '?')} active). "
                    "Please close some browser tabs or wait for sessions to expire."
                )

            if response.status_code >= 400:
                raise RuntimeError(
                    f"Failed to initialize MCP session: {response.status_code} - {response.text}"
                )

            # Extract session ID from response header
            self._mcp_session_id = response.headers.get("mcp-session-id")
            if not self._mcp_session_id:
                raise RuntimeError(
                    "MCP server did not return session ID in response headers"
                )

            self._session_token = access_token

            # Complete the handshake with initialized notification
            await self._send_initialized_notification(oauth_token, client)

            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {
                        "description": "Connected to Kali range",
                        "done": True
                    }
                })

    async def _call_mcp(
        self,
        method: str,
        params: Optional[dict],
        oauth_token: Optional[dict],
        __event_emitter__=None
    ) -> dict:
        """
        Make a JSON-RPC call to the MCP server.

        Ensures initialized first, then sends request with session ID header.
        Handles session expiration by re-initializing.
        """
        await self._ensure_initialized(oauth_token, __event_emitter__)
        headers = self._get_mcp_headers(oauth_token)

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
        }
        if params:
            payload["params"] = params

        async with httpx.AsyncClient(timeout=self.valves.request_timeout) as client:
            try:
                response = await client.post(
                    f"{self.valves.mcp_server_url}/mcp",
                    headers=headers,
                    json=payload
                )
            except httpx.ConnectError:
                raise ConnectionError(
                    "Lost connection to MCP server. Please try again."
                )
            except httpx.TimeoutException:
                raise TimeoutError(
                    "MCP request timed out. The operation may still be running. "
                    "Check your range status before retrying."
                )

            # Session expired or not found - re-initialize
            if response.status_code == 404:
                data = response.json()
                if data.get("error") == "session_not_found":
                    self._mcp_session_id = None
                    self._session_token = None
                    await self._ensure_initialized(oauth_token, __event_emitter__)
                    headers = self._get_mcp_headers(oauth_token)

                    response = await client.post(
                        f"{self.valves.mcp_server_url}/mcp",
                        headers=headers,
                        json=payload
                    )

            if response.status_code == 401:
                raise PermissionError(
                    "Authentication failed. Please refresh and log in again."
                )

            if response.status_code == 403:
                raise PermissionError(
                    "Access denied. This session belongs to another user."
                )

            if response.status_code >= 400:
                raise RuntimeError(
                    f"MCP request failed: {response.status_code} - {response.text}"
                )

            return response.json()

    async def list_mcp_tools(
        self,
        __oauth_token__: Optional[dict] = None,
        __event_emitter__=None
    ) -> str:
        """
        List available MCP tools for your Kali range.

        Returns a list of tools that can be used to interact with your
        Shifter Kali instance, including their names and descriptions.
        """
        try:
            result = await self._call_mcp(
                method="tools/list",
                params=None,
                oauth_token=__oauth_token__,
                __event_emitter__=__event_emitter__
            )

            if "error" in result:
                return f"Error listing tools: {result['error'].get('message', 'Unknown error')}"

            tools = result.get("result", {}).get("tools", [])

            if not tools:
                return "No MCP tools available for your range."

            # Format tool list for display
            lines = ["**Available MCP Tools:**\n"]
            for tool in tools:
                name = tool.get("name", "unknown")
                desc = tool.get("description", "No description")
                lines.append(f"- **{name}**: {desc}")

            return "\n".join(lines)

        except (ValueError, PermissionError, ConnectionError, TimeoutError, RuntimeError) as e:
            return f"Error: {str(e)}"

    async def run_mcp_tool(
        self,
        tool_name: str,
        arguments: str,
        __oauth_token__: Optional[dict] = None,
        __event_emitter__=None
    ) -> str:
        """
        Execute an MCP tool on your Kali range.

        Runs the specified tool with the given arguments on your Shifter
        Kali instance. Use list_mcp_tools first to see available tools.

        :param tool_name: Name of the MCP tool to execute (e.g., "run_command", "nmap_scan")
        :param arguments: JSON string of arguments to pass to the tool
        :return: Tool execution result
        """
        try:
            # Parse arguments
            try:
                args = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                return f"Error: Invalid JSON in arguments. Got: {arguments}"

            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {
                        "description": f"Executing {tool_name}...",
                        "done": False
                    }
                })

            result = await self._call_mcp(
                method="tools/call",
                params={"name": tool_name, "arguments": args},
                oauth_token=__oauth_token__,
                __event_emitter__=__event_emitter__
            )

            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {
                        "description": f"Completed {tool_name}",
                        "done": True
                    }
                })

            if "error" in result:
                error = result["error"]
                return f"Tool execution failed: {error.get('message', 'Unknown error')}"

            # Extract and format result
            tool_result = result.get("result", {})
            content = tool_result.get("content", [])

            if not content:
                return "Tool executed successfully (no output)"

            # Combine all content blocks
            output_parts = []
            for block in content:
                if block.get("type") == "text":
                    output_parts.append(block.get("text", ""))
                elif block.get("type") == "resource":
                    output_parts.append(f"[Resource: {block.get('uri', 'unknown')}]")
                else:
                    output_parts.append(str(block))

            return "\n".join(output_parts)

        except (ValueError, PermissionError, ConnectionError, TimeoutError, RuntimeError) as e:
            return f"Error: {str(e)}"
