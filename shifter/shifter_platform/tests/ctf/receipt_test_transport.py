"""Real receipt HTTP path driven at external socket and provider-SDK boundaries."""

from __future__ import annotations

import io
import json
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from django.test import override_settings


def _fake_addrinfo(*ips: str) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 443)) for ip in ips]


@dataclass(slots=True)
class ReceiptWire:
    """Inspectable external-boundary fakes used by receipt transport tests."""

    dns: MagicMock
    connect: MagicMock
    tls_socket: MagicMock
    secrets_client: MagicMock
    boto_client_factory: MagicMock

    def request_bytes(self) -> bytes:
        """Return the bytes sent through the real ``http.client`` connection."""
        return b"".join(bytes(call.args[0]) for call in self.tls_socket.sendall.call_args_list)

    def request_json(self) -> dict:
        """Decode the request body written by the real HTTP connection."""
        _headers, body = self.request_bytes().split(b"\r\n\r\n", 1)
        return json.loads(body)


@contextmanager
def receipt_wire(
    response_body: bytes = b'{"valid":false}',
    *,
    status: int = 200,
    ips: tuple[str, ...] = ("8.8.8.8",),
    connection_error: OSError | None = None,
    service_auth: str = "service-auth-value",
    before_response: Callable[[], None] | None = None,
) -> Iterator[ReceiptWire]:
    """Run production DNS/TLS/HTTP/secret adapters over external fakes."""
    reason = b"OK" if status == 200 else b"Service Unavailable"
    response = (
        b"HTTP/1.1 "
        + str(status).encode("ascii")
        + b" "
        + reason
        + b"\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(response_body)).encode("ascii")
        + b"\r\nConnection: close\r\n\r\n"
        + response_body
    )
    plain_socket = MagicMock()
    tls_socket = MagicMock()

    def response_stream(*_args, **_kwargs):
        if before_response is not None:
            before_response()
        return io.BytesIO(response)

    tls_socket.makefile.side_effect = response_stream
    secrets_client = MagicMock()
    secrets_client.get_secret_value.return_value = {"SecretString": service_auth}
    connect_side_effect = connection_error if connection_error is not None else None
    with (
        override_settings(CLOUD_PROVIDER="aws"),
        patch("socket.getaddrinfo", return_value=_fake_addrinfo(*ips)) as dns,
        patch(
            "socket.create_connection",
            return_value=plain_socket,
            side_effect=connect_side_effect,
        ) as connect,
        patch("ssl.SSLContext.wrap_socket", return_value=tls_socket),
        patch("boto3.client", return_value=secrets_client) as boto_client_factory,
    ):
        yield ReceiptWire(
            dns=dns,
            connect=connect,
            tls_socket=tls_socket,
            secrets_client=secrets_client,
            boto_client_factory=boto_client_factory,
        )
