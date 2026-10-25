"""The provider egress listener cannot relay arbitrary hosts or internal IPs."""

import asyncio

import pytest

from model_broker.egress_proxy import connect_host, handle_connect, resolve_public_address


@pytest.mark.parametrize(
    "authority",
    [
        "api.openai.com:443",
        "api.anthropic.com:443",
        "openrouter.ai:443",
        "europe-west4-aiplatform.googleapis.com:443",
        "aiplatform.us.rep.googleapis.com:443",
        "aiplatform.eu.rep.googleapis.com:443",
        "sts.us-east-1.amazonaws.com:443",
        "bedrock-runtime.us-west-2.amazonaws.com:443",
    ],
)
def test_exact_provider_https_origins(authority):
    assert connect_host(f"CONNECT {authority} HTTP/1.1\r\n\r\n".encode()) == authority[:-4]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authority",
    [
        "127.0.0.1:443",
        "169.254.169.254:443",
        "api.openai.com.evil.test:443",
        "api.openai.com:80",
        "user@api.openai.com:443",
        "foreign.example.test:443",
        "oauth2.googleapis.com.:443",
    ],
)
async def test_live_listener_rejects_nonprovider_tunnels(authority):
    server = await asyncio.start_server(handle_connect, "127.0.0.1", 0, limit=4096)
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
        writer.write(f"CONNECT {authority} HTTP/1.1\r\n\r\n".encode())
        await writer.drain()
        assert (await reader.read()).startswith(b"HTTP/1.1 403")
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_dns_answers_cannot_redirect_an_approved_host_to_private_services(monkeypatch):
    loop = asyncio.get_running_loop()

    async def lookup(*args, **kwargs):
        return [(2, 1, 6, "", ("10.2.0.1", 443))]

    monkeypatch.setattr(loop, "getaddrinfo", lookup)
    with pytest.raises(ValueError, match="address unavailable"):
        await resolve_public_address("api.openai.com")


@pytest.mark.asyncio
async def test_approved_tunnel_connects_to_pinned_address_and_relays_bytes(monkeypatch):
    from model_broker import egress_proxy

    real_open = asyncio.open_connection
    dialed = []

    async def echo(reader, writer):
        writer.write(await reader.readexactly(4))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
    async with upstream:

        async def resolve(host):
            assert host == "api.openai.com"
            return "1.1.1.1"

        async def connect(address, port, **kwargs):
            dialed.append((address, port))
            return await real_open("127.0.0.1", upstream.sockets[0].getsockname()[1], **kwargs)

        monkeypatch.setattr(egress_proxy, "resolve_public_address", resolve)
        monkeypatch.setattr(egress_proxy.asyncio, "open_connection", connect)
        server = await asyncio.start_server(handle_connect, "127.0.0.1", 0, limit=4096)
        async with server:
            reader, writer = await real_open("127.0.0.1", server.sockets[0].getsockname()[1])
            writer.write(b"CONNECT api.openai.com:443 HTTP/1.1\r\n\r\n")
            await writer.drain()
            assert (
                await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 2)
                == b"HTTP/1.1 200 Connection Established\r\n\r\n"
            )
            writer.write(b"test")
            await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(4), 2) == b"test"
            writer.close()
            await writer.wait_closed()
    assert dialed == [("1.1.1.1", 443)]


@pytest.mark.asyncio
async def test_private_endpoint_exception_is_exact_and_aws_only(monkeypatch):
    loop = asyncio.get_running_loop()
    address = ["10.2.0.9"]

    async def lookup(*args, **kwargs):
        return [(2, 1, 6, "", (address[0], 443))]

    monkeypatch.setattr(loop, "getaddrinfo", lookup)
    monkeypatch.setenv("MODEL_EGRESS_PRIVATE_CIDRS", "10.2.0.9/32")
    assert await resolve_public_address("bedrock-runtime.us-east-1.amazonaws.com") == "10.2.0.9"
    with pytest.raises(ValueError):
        await resolve_public_address("api.openai.com")
    address[0] = "10.2.0.10"
    with pytest.raises(ValueError):
        await resolve_public_address("bedrock-runtime.us-east-1.amazonaws.com")
