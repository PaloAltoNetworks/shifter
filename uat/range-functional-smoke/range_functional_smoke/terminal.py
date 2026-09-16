"""Terminal check: a real data exchange with the range host, not a handshake.

A completed websocket upgrade proves only that Channels accepted the socket. The
sufficient evidence is a **nonce round-trip**: input sent through the product
path produces matching output from the guest's own shell, which means
``SSHConsumer`` -> ``engine.services.connect_terminal`` -> the realized SSH
binding all worked.

The echo hazard, and why the command looks odd
----------------------------------------------
An interactive shell echoes the characters it receives, so the typed command
comes back on the socket before the shell ever runs it. If the probe simply sent
``echo <nonce>`` and searched the stream for ``<nonce>``, it would match its own
echoed input and report success against a shell that never executed anything —
a false pass on exactly the regression this check exists to catch.

The command is therefore split with a shell string break:

    echo "SMOKE""<nonce>"

The echoed *input* contains ``SMOKE""<nonce>``; only the shell's *output*
contains the joined token ``SMOKE<nonce>``. Matching the joined token cannot be
satisfied by the echo, so a match proves the guest executed the command.

Terminal output is never published: only the pass/fail of the match and bounded
metadata leave this module.
"""

from __future__ import annotations

import json
import re
import secrets

#: Marker joined to the nonce. Alphanumeric so no shell quoting or ANSI
#: sequence can split it, and distinctive enough not to occur in a prompt.
NONCE_PREFIX = "SMOKE"

#: Cap on retained output. A chatty MOTD or a scrolling prompt must not let the
#: probe accumulate unbounded memory; the tail is what carries the answer.
MAX_BUFFER_CHARS = 65536

# CSI / OSC escape sequences plus carriage returns: a prompt redraw can split a
# token across a control sequence, so they are removed before matching.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")


def make_nonce() -> str:
    """Return a fresh, bounded, alphanumeric nonce.

    Alphanumeric by design: no shell metacharacter, no regex metacharacter, and
    nothing an ANSI filter could rewrite.
    """
    return secrets.token_hex(8)


def joined_token(nonce: str) -> str:
    """The token that may only appear in the guest's *output*."""
    return f"{NONCE_PREFIX}{nonce}"


def input_command(nonce: str) -> str:
    """The harmless, idempotent command whose echo cannot satisfy the match."""
    return f'echo "{NONCE_PREFIX}""{nonce}"\n'


def input_frame(nonce: str) -> str:
    """The exact websocket text frame ``SSHConsumer.receive`` expects."""
    return json.dumps({"type": "input", "data": input_command(nonce)})


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences and carriage returns before matching."""
    return _ANSI.sub("", text).replace("\r", "")


def output_text(frame: str | bytes) -> str:
    """Extract the payload of an ``output`` frame; other frame types yield ''.

    A frame that is not JSON, not a dict, or not of type ``output`` contributes
    nothing rather than raising — the consumer legitimately emits other message
    types, and a malformed frame must not abort a bounded wait.
    """
    if isinstance(frame, bytes):
        try:
            frame = frame.decode("utf-8", "replace")
        except Exception:
            return ""
    try:
        message = json.loads(frame)
    except (TypeError, ValueError):
        return ""
    if not isinstance(message, dict) or message.get("type") != "output":
        return ""
    data = message.get("data", "")
    return data if isinstance(data, str) else ""


def accumulate(buffer: str, chunk: str) -> str:
    """Append a chunk, keeping the retained tail bounded."""
    combined = buffer + chunk
    if len(combined) <= MAX_BUFFER_CHARS:
        return combined
    return combined[-MAX_BUFFER_CHARS:]


def nonce_observed(buffer: str, nonce: str) -> bool:
    """True when the guest's output carries the joined token.

    Matching happens on the ANSI-stripped accumulation, so a token split across
    frames or interrupted by a prompt redraw still matches.
    """
    return joined_token(nonce) in strip_ansi(buffer)


def terminal_ws_url(origin: str, instance_uuid: str) -> str:
    """Build the routed consumer URL for an instance, mirroring the browser path."""
    scheme = "wss" if origin.startswith("https://") else "ws"
    host = origin.split("://", 1)[1]
    return f"{scheme}://{host}/ws/terminal/{instance_uuid}/"
