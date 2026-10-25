"""An HTTP CONNECT hop must carry provider credentials only inside verified TLS."""

import asyncio
import ssl
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from model_broker import egress_proxy


def _tls_contexts(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "api.openai.com")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=10))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("api.openai.com")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert_path, key_path)
    client = ssl.create_default_context(cafile=str(cert_path))
    return server, client


@pytest.mark.asyncio
async def test_connect_proxy_preserves_verified_tls_and_never_sees_credentials(tmp_path, monkeypatch):
    server_tls, client_tls = _tls_contexts(tmp_path)
    real_connect = asyncio.open_connection
    wire = bytearray()
    received = []

    class RecordingWriter:
        def __init__(self, writer):
            self.writer = writer

        def write(self, chunk):
            wire.extend(chunk)
            self.writer.write(chunk)

        def __getattr__(self, name):
            return getattr(self.writer, name)

    async def provider(reader, writer):
        received.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    upstream = await asyncio.start_server(provider, "127.0.0.1", 0, ssl=server_tls)
    async with upstream:

        async def resolve(host):
            assert host == "api.openai.com"
            return "1.1.1.1"

        async def connect(address, port, **kwargs):
            assert (address, port) == ("1.1.1.1", 443)
            reader, writer = await real_connect("127.0.0.1", upstream.sockets[0].getsockname()[1], **kwargs)
            return reader, RecordingWriter(writer)

        monkeypatch.setattr(egress_proxy, "resolve_public_address", resolve)
        monkeypatch.setattr(egress_proxy.asyncio, "open_connection", connect)
        proxy = await asyncio.start_server(egress_proxy.handle_connect, "127.0.0.1", 0)
        async with proxy:
            proxy_url = f"http://127.0.0.1:{proxy.sockets[0].getsockname()[1]}"
            async with httpx.AsyncClient(proxy=proxy_url, verify=client_tls, trust_env=False) as client:
                response = await client.post(
                    "https://api.openai.com/v1/messages", headers={"Authorization": "Bearer synthetic-tunnel-proof"}
                )
                assert response.status_code == 200
    assert b"Bearer synthetic-tunnel-proof" in received[0]
    assert wire[:2] == b"\x16\x03"  # TLS handshake, before any application records.
    assert b"synthetic-tunnel-proof" not in wire
    assert b"POST /v1/messages" not in wire
