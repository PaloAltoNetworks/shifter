"""CONNECT-only provider egress, with fixed origins and pinned public DNS answers.

TLS terminates at the provider. This process has no cloud identity, credentials,
Django configuration, or access to the control listener.
"""

import asyncio
import ipaddress
import os
import re
import socket
from contextlib import suppress

_ALLOWED_HOSTS = frozenset(
    {"api.openai.com", "api.anthropic.com", "openrouter.ai", "oauth2.googleapis.com", "iamcredentials.googleapis.com"}
)
_CLOUD_HOST = re.compile(
    r"(?:[a-z][a-z0-9-]{1,62}-aiplatform\.googleapis\.com|aiplatform\.(?:us|eu)\.rep\.googleapis\.com|"
    r"(?:sts|bedrock-runtime)\.[a-z]{2}(?:-gov)?-[a-z]+-\d\.amazonaws\.com)"
)
_MAX_CONNECTIONS = 256
_active = 0


def connect_host(header: bytes) -> str:
    """Accept only an exact approved HTTPS authority, never a URL or userinfo."""
    if len(header) > 4096:
        raise ValueError("invalid CONNECT request")
    line = header.split(b"\r\n", 1)[0].decode("ascii")
    method, authority, version = line.split(" ")
    if method != "CONNECT" or version != "HTTP/1.1" or not authority.endswith(":443"):
        raise ValueError("invalid CONNECT request")
    host = authority[:-4]
    if host not in _ALLOWED_HOSTS and _CLOUD_HOST.fullmatch(host) is None:
        raise ValueError("provider origin unavailable")
    return host


async def resolve_public_address(host: str) -> str:
    """Resolve once and connect to the admitted IP, preventing DNS rebinding."""
    addresses = await asyncio.get_running_loop().getaddrinfo(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)
    private = tuple(
        ipaddress.IPv4Network(value, strict=True)
        for value in os.environ.get("MODEL_EGRESS_PRIVATE_CIDRS", "").split(",")
        if value
    )

    def allowed(value: str) -> bool:
        """Allow public addresses or explicitly admitted AWS private endpoints."""
        address = ipaddress.ip_address(value)
        return address.is_global or (host.endswith(".amazonaws.com") and any(address in network for network in private))

    public = [item[4][0] for item in addresses if allowed(item[4][0])]
    if not public or len(public) != len(addresses):
        raise ValueError("provider address unavailable")
    return public[0]


async def _relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Relay bounded opaque TLS chunks with downstream backpressure."""
    while chunk := await reader.read(16384):
        writer.write(chunk)
        await writer.drain()


async def handle_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Bound headers, connection count, setup time, lifetime, and relay buffers."""
    global _active
    if _active >= _MAX_CONNECTIONS:
        writer.close()
        return
    _active += 1
    upstream = None
    established = False
    try:
        async with asyncio.timeout(8):
            host = connect_host(await reader.readuntil(b"\r\n\r\n"))
            address = await resolve_public_address(host)
            remote, upstream = await asyncio.open_connection(address, 443, limit=32768)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            established = True
        tasks = [asyncio.create_task(_relay(reader, upstream)), asyncio.create_task(_relay(remote, writer))]
        try:
            async with asyncio.timeout(900):
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except (ValueError, OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        if not established:
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            with suppress(OSError):
                await writer.drain()
    finally:
        _active -= 1
        writer.close()
        if upstream is not None:
            upstream.close()
        with suppress(OSError):
            await writer.wait_closed()


async def main() -> None:
    """Listen on the configured private address with bounded CONNECT headers."""
    from shared.model_access.network import private_listener_address

    address = private_listener_address(os.environ["MODEL_EGRESS_BIND_ADDRESS"])
    server = await asyncio.start_server(handle_connect, address, 3128, limit=4096)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
