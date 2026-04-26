"""Custom text-over-TCP brain controller protocol.

Reads configuration from /generated/config.json (seeded by the json content
generator). Supports an XOR challenge-response handshake derived from the
configured serial numbers + a simple text command protocol thereafter.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path


CONFIG_PATH = Path("/generated/config.json")
DEFAULT_CONFIG = {
    "listen": "0.0.0.0:9100",
    "auth_token": "change-me",
    "serials": [],
    "controller_addresses": {},
    "override_code": "",
}


def _load_config() -> dict:
    if CONFIG_PATH.is_file():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return dict(DEFAULT_CONFIG)


def _derive_handshake_key(serials: list[str]) -> bytes:
    joined = "".join(serials).encode("utf-8")
    return hashlib.sha256(joined).digest()


async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    cfg = _load_config()
    key = _derive_handshake_key(cfg.get("serials", []))
    challenge = os.urandom(16)
    writer.write(b"CHALLENGE " + challenge.hex().encode() + b"\n")
    await writer.drain()

    response_line = await reader.readline()
    expected = bytes(a ^ b for a, b in zip(challenge, key)).hex()
    if response_line.strip().decode(errors="replace") != f"RESPONSE {expected}":
        writer.write(b"ERR handshake\n")
        await writer.drain()
        writer.close()
        return

    writer.write(b"OK authenticated\n")
    await writer.drain()

    while True:
        line = await reader.readline()
        if not line:
            break
        parts = line.strip().decode(errors="replace").split()
        if not parts:
            continue
        cmd = parts[0].lower()
        if cmd == "status":
            writer.write(
                b"STATUS controllers=" + str(cfg.get("controller_addresses", {})).encode() + b"\n"
            )
        elif cmd == "override" and len(parts) >= 2:
            if parts[1] == cfg.get("override_code"):
                writer.write(b"OVERRIDE accepted\n")
            else:
                writer.write(b"OVERRIDE rejected\n")
        elif cmd == "quit":
            writer.write(b"BYE\n")
            await writer.drain()
            break
        else:
            writer.write(b"ERR unknown-command\n")
        await writer.drain()

    writer.close()


async def _main() -> None:
    cfg = _load_config()
    host, _, port = cfg.get("listen", "0.0.0.0:9100").partition(":")
    server = await asyncio.start_server(_handle_client, host=host, port=int(port or 9100))
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_main())
