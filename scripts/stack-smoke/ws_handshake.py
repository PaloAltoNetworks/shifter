#!/usr/bin/env python3
"""Authenticated websocket handshake probe for the built-image stack smoke (#922).

Proves that the *built portal image*, booted under its real ``entrypoint.sh``,
serves websockets through the production ASGI stack:
``AllowedHostsOriginValidator`` -> ``AuthMiddlewareStack`` -> ``URLRouter`` -> a
real routed consumer. Routed consumers require authentication to accept, so the
caller creates a throwaway Django session in the smoke database and passes its
``sessionid`` cookie here. A completed OPEN handshake (HTTP 101 + the consumer
calling ``accept()``) plus a live ping/pong is the success signal; an
unauthenticated rejection, a missing route, or a dead channel layer all fail.

Run via ``uv run --with 'websockets==12.0' python ws_handshake.py ...`` so the
hosted runner needs no pre-installed websocket client. No secret value is
printed: the session key is read from argv only and never echoed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import websockets


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="ws:// URL of the routed consumer")
    parser.add_argument("--session", required=True, help="Django session key (sessionid cookie value)")
    parser.add_argument("--origin", default="http://localhost", help="Origin header (must be an ALLOWED_HOST)")
    parser.add_argument("--cookie-name", default="sessionid", help="Session cookie name")
    parser.add_argument("--timeout", type=float, default=15.0, help="Handshake/ping timeout in seconds")
    return parser.parse_args()


async def _handshake(args: argparse.Namespace) -> None:
    headers = [
        ("Origin", args.origin),
        ("Cookie", f"{args.cookie_name}={args.session}"),
    ]
    async with websockets.connect(
        args.url,
        extra_headers=headers,
        open_timeout=args.timeout,
        close_timeout=args.timeout,
    ) as ws:
        # Reaching here means the consumer accepted: the full middleware/router
        # chain ran. Confirm the socket is actually live end-to-end.
        pong_waiter = await ws.ping()
        await asyncio.wait_for(pong_waiter, timeout=args.timeout)
    print("ws-handshake: OPEN ok")


def main() -> int:
    args = _parse_args()
    try:
        asyncio.run(asyncio.wait_for(_handshake(args), timeout=args.timeout * 2))
    except Exception as exc:  # noqa: BLE001 - any failure is a smoke failure
        print(f"ws-handshake: FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
