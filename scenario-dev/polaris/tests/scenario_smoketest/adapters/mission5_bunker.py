"""Mission 5 (Bunker) adapters — Bunker-chain credential-gate verification (#707).

Challenge 31 (Underground Signals) is the boundary that proves the splice flip
opened the participant's path from a14-kali through ``splice-relay`` into the
Bunker OT controllers. The adapter exercises the full participant chain:

  1. The discoverability evidence — the SSH private key staged on a14-kali by
     the range bootstrap (issue #707) — exists and is mode ``0600``. Missing
     evidence or wrong permissions is the bake defect this adapter exists to
     catch.
  2. ``ssh root@splice-relay true`` from a14-kali authenticates with the staged
     key (``~/.ssh/config`` resolves the IdentityFile). Auth refusal short-
     circuits — no downstream OT probe is attempted, no stderr leaks into the
     report.
  3. From the splice-relay shell, ``modbus_client.py <host> devid`` is run
     against the three Aurora controllers. Each ``ProductName`` is parsed and
     concatenated in the canonical (tail, leg, arms) order; the harness'
     ``answer`` comparator checks the result against the expected concatenation
     declared on the adapter, and the compare layer redacts both sides on
     mismatch.

All exec calls originate from a14-kali. The Modbus probes are issued *through*
the SSH tunnel, so a regression on either the key staging or the A9 sshd auth
configuration fails the adapter before any controller is touched.
"""

from __future__ import annotations

import re

from . import AdapterContext, Produced, register

RUNNER = "a14-kali"
_KEY_PATH = "/home/kali/.ssh/splice_relay"
_REQUIRED_PERMS = "600"
_SPLICE_TARGET = "root@splice-relay"

# Order matters: the flag-31 answer is the (tail, leg, arms) concatenation.
_CONTROLLERS = ("tail-ctrl", "leg-ctrl", "arms-ctrl")
_EXPECTED_ANSWER = "AHS-TAIL-7741AHS-LEG-MN07AHS-ARM-AL42"

_SSH_AUTH_ARGV = (
    "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
    "-o", "StrictHostKeyChecking=accept-new",
    _SPLICE_TARGET, "true",
)
_SSH_REMOTE_PREFIX = (
    "ssh", "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    _SPLICE_TARGET,
)

_PRODUCT_NAME_RE = re.compile(r"^\s*ProductName:\s*(\S+)\s*$", re.MULTILINE)


def _extract_product_name(devid_body: str) -> str | None:
    """Return the ProductName value from a ``modbus_client.py ... devid`` body."""
    match = _PRODUCT_NAME_RE.search(devid_body or "")
    return match.group(1) if match else None


@register(31, runner=RUNNER, value_kind="answer", expected_answer=_EXPECTED_ANSWER)
def challenge_31(ctx: AdapterContext) -> Produced:
    """Underground Signals — concatenate A10/A11/A12 ProductName via the splice."""
    # 1. Discoverability evidence on a14-kali.
    present = ctx.runner.exec(RUNNER, ["test", "-f", _KEY_PATH])
    if present.returncode != 0:
        return Produced(None, "answer", "splice key evidence missing on a14-kali")

    perms = ctx.runner.exec(RUNNER, ["stat", "-c", "%a", _KEY_PATH])
    observed = perms.stdout.strip()
    if observed != _REQUIRED_PERMS:
        return Produced(
            None, "answer",
            f"splice key wrong perms (expected {_REQUIRED_PERMS}, got {observed!r})",
        )

    # 2. Auth opens via the staged key.
    auth = ctx.runner.exec(RUNNER, list(_SSH_AUTH_ARGV))
    if auth.returncode != 0:
        return Produced(None, "answer", "splice-relay ssh auth refused")

    # 3. Modbus device-id probes through the SSH tunnel; collect ProductNames.
    models: list[str] = []
    for host in _CONTROLLERS:
        probe = ctx.runner.exec(
            RUNNER,
            [
                *_SSH_REMOTE_PREFIX,
                "python3", "/usr/local/bin/modbus_client.py", host, "devid",
            ],
        )
        if probe.returncode != 0:
            return Produced(None, "answer", f"modbus devid probe failed for {host}")
        model = _extract_product_name(probe.stdout)
        if not model:
            return Produced(
                None, "answer",
                f"modbus devid response missing ProductName for {host}",
            )
        models.append(model)

    return Produced(
        "".join(models),
        "answer",
        "splice-relay auth opened; three ProductName values recovered via ssh",
    )
