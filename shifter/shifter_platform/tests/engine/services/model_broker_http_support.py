"""Real local TLS listeners; only external provider/IAM endpoints are synthetic."""

import asyncio
import fcntl
import ipaddress
import json
import socket
import ssl
import struct
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from google.auth import crypt, jwt

from model_broker.provider_usage import encode_sse
from model_broker.runtime_server import DrainingServer
from shared.model_access import seal_catalog
from shared.model_access.control_identity import verify_google_control_assertion
from shared.model_access.http import body, json_response

PROMPT = "SYNTHETIC-PROMPT-SENTINEL-2122"
ANSWER = "SYNTHETIC-ANSWER-SENTINEL-2122"
ERROR = "SYNTHETIC-PROVIDER-ERROR-2122"
PROOF = "SYNTHETIC-PROVIDER-CREDENTIAL-2122"


def enable_count(allocation):
    """Seal a synthetic catalog explicitly authorizing zero-priced count calls."""
    snapshot = allocation.snapshot
    catalog = snapshot["catalog"]
    catalog["profiles"][0]["capabilities"].append("token-count")
    catalog["shards"][0]["capabilities"].append("token-count")
    catalog["shards"][0]["billing_components"].append("request")
    catalog["price_schedules"][0]["prices"].append(
        {"component": "request", "unit_denominator": 1, "price_micro_units": 0}
    )
    sealed = seal_catalog(catalog)
    snapshot["catalog"] = sealed.model_dump(mode="json")
    snapshot["shards"]["coding-main"] = sealed.shards[0].model_dump(mode="json")
    snapshot["effective_policy"]["catalog_digest"] = sealed.digest
    snapshot["effective_policy"]["effective_profile"]["capabilities"].append("token-count")
    allocation.save(update_fields=["snapshot"])


def private_host():
    """Use a real private interface, including a local container bridge."""
    private = [ipaddress.IPv4Network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as query:
        for _, interface in socket.if_nameindex():
            try:
                # Linux SIOCGIFADDR: read-only IPv4 interface address lookup.
                address = fcntl.ioctl(query.fileno(), 0x8915, struct.pack("256s", interface.encode()[:15]))
            except OSError:
                continue
            host = socket.inet_ntoa(address[20:24])
            if any(ipaddress.IPv4Address(host) in network for network in private):
                return host
    raise RuntimeError("local HTTP qualification needs an RFC1918 interface")


def tls_identity(tmp_path, host):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-control")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPv4Address(host))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "tls.crt", tmp_path / "tls.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    key_path.write_bytes(private)
    signer = crypt.RSASigner.from_string(private, key_id="synthetic")
    certificate = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    async def assertion():
        now = int(datetime.now(UTC).timestamp())
        return (
            "Bearer "
            + jwt.encode(
                signer,
                {
                    "aud": "control-test",
                    "iss": "https://accounts.google.com",
                    "iat": now,
                    "exp": now + 60,
                    "email": "broker@example.invalid",
                    "email_verified": True,
                    "sub": "123456789012345678901",
                },
            ).decode()
        )

    def verify(value, *, operation_id):
        verify_google_control_assertion(
            value,
            audience=f"control-test:enroll:{operation_id}" if operation_id else "control-test",
            expected_subject="provisioner@example.invalid" if operation_id else "broker@example.invalid",
            expected_subject_id="123456789012345678902" if operation_id else "123456789012345678901",
            request=lambda *args, **kwargs: SimpleNamespace(
                status=200, data=json.dumps({"synthetic": certificate.decode()}).encode()
            ),
        )

    return cert_path, key_path, assertion, verify


@asynccontextmanager
async def listener(app, host, cert, key, *, broker=False):
    sock = socket.socket()
    sock.bind((host, 0))
    sock.listen(128)
    sock.setblocking(False)
    port = sock.getsockname()[1]
    server = (DrainingServer if broker else uvicorn.Server)(
        uvicorn.Config(
            app,
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
            lifespan="off",
            access_log=False,
            log_config=None,
            proxy_headers=False,
            http="h11",
            ws="none",
            h11_max_incomplete_event_size=32768,
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(3):
            while not server.started:
                if task.done():
                    task.result()
                await asyncio.sleep(0.01)
        yield f"https://{host}:{port}", server
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 5)
        finally:
            sock.close()


class ProviderTransport(httpx.AsyncBaseTransport):
    """Route fixed external provider requests to the controllable local TLS peer."""

    def __init__(self, origin, cert):
        self.origin = httpx.URL(origin)
        self.transport = httpx.AsyncHTTPTransport(verify=ssl.create_default_context(cafile=str(cert)))

    async def handle_async_request(self, request):
        assert request.url.host in {"aiplatform.eu.rep.googleapis.com", "europe-west4-aiplatform.googleapis.com"}
        url = request.url.copy_with(host=self.origin.host, port=self.origin.port)
        return await self.transport.handle_async_request(
            httpx.Request(
                request.method, url, headers=request.headers, stream=request.stream, extensions=request.extensions
            )
        )

    async def aclose(self):
        await self.transport.aclose()


class ProviderCredentials:
    async def headers(self, target, *, url, body):
        return {"authorization": PROOF, "content-type": "application/json"}


class ProviderServer:
    """Controllable external Messages/count service with observable disconnects."""

    def __init__(self):
        self.mode = "json"
        self.requests = []
        self.started = asyncio.Event()
        self.closed = asyncio.Event()
        self.chunks_sent = 0

    async def __call__(self, scope, receive, send):
        raw = await body(receive, limit=1_000_000)
        self.requests.append((scope["path"], raw, dict(scope["headers"])))
        if "count-tokens" in scope["path"]:
            await json_response(send, 200, {"input_tokens": 5})
            return
        if self.mode in {"error", "redirect"}:
            await send(
                {
                    "type": "http.response.start",
                    "status": 503 if self.mode == "error" else 307,
                    "headers": [(b"x-provider-error", ERROR.encode()), (b"location", b"https://unapproved.invalid")],
                }
            )
            await send({"type": "http.response.body", "body": ERROR.encode()})
            return
        if self.mode == "json":
            await json_response(
                send,
                200,
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": ANSWER}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 5, "output_tokens": 3},
                },
            )
            return
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
        events = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": ANSWER}},
            {"type": "message_delta", "usage": {"output_tokens": 3}},
            {"type": "message_stop"},
        ]
        try:
            if self.mode == "flood":
                await self._flood(events[:2], receive, send)
                return
            for event in events:
                await send({"type": "http.response.body", "body": encode_sse(event), "more_body": True})
                if self.mode == "stall":
                    self.started.set()
                    while (await receive())["type"] != "http.disconnect":
                        pass
                    return
            await send({"type": "http.response.body", "body": b""})
        finally:
            self.closed.set()

    async def _flood(self, events, receive, send):
        async def produce():
            await send({"type": "http.response.body", "body": encode_sse(events[0]), "more_body": True})
            events[1]["delta"]["text"] = ANSWER * 8000
            for _ in range(128):
                await send({"type": "http.response.body", "body": encode_sse(events[1]), "more_body": True})
                self.chunks_sent += 1
                self.started.set()

        task = asyncio.create_task(produce())
        try:
            while (await receive())["type"] != "http.disconnect":
                pass
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError, OSError):
                await task
