"""Execution seams for the backend-aware ``doctor`` UX (#727): tool lookup, command runner,
and the SSRF-hardened health probe, plus the :class:`DoctorProbes` bundle that injects them.

Split out of :mod:`installation.doctor` so the real subprocess/network wrappers live apart
from the pure executor logic and each file stays under the per-file size limit. These are the
default (real) implementations; tests inject fakes via :class:`DoctorProbes`.
"""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import subprocess  # nosec B404
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ._doctor_model import CommandOutcome, HealthOutcome

#: How long a single validation-check subprocess may run before doctor gives up on it.
COMMAND_TIMEOUT_SECONDS = 120

ToolProbe = Callable[[str], bool]
CommandRunner = Callable[[Sequence[str], Path], CommandOutcome]
HealthProbe = Callable[[str, int], HealthOutcome]


def _default_tool_probe(name: str) -> bool:
    """Whether ``name`` resolves to an executable on PATH."""
    return shutil.which(name) is not None


def _default_command_runner(argv: Sequence[str], cwd: Path) -> CommandOutcome:
    """Run a validated argv array without a shell, capturing nothing sensitive.

    The command comes from the backend contract's :class:`~installation.contract.CommandSpec`,
    which already rejects shell metacharacters, absolute paths, and traversal, so it is run
    with ``shell=False``. Output is captured only to keep it off the terminal — it is never
    read into a result, so a Terraform plan or provider response cannot leak through doctor.
    """
    env = {**os.environ, "AWS_PAGER": ""}
    try:
        completed = subprocess.run(  # noqa: S603 # nosec B603
            list(argv),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            shell=False,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return CommandOutcome(returncode=None, timed_out=True)
    except OSError as exc:
        return CommandOutcome(returncode=None, error=getattr(exc, "strerror", None) or "could not run command")
    return CommandOutcome(returncode=completed.returncode)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects so a public health target cannot bounce the probe to an
    internal endpoint. Returning ``None`` makes urllib raise the 3xx as an ``HTTPError``."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        """Decline to build any redirect request (SSRF guard)."""
        return None


def _is_global_address(address: str) -> bool:
    """Whether ``address`` is a public (global) IP — not loopback/private/link-local/reserved."""
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


def _resolves_to_public_only(hostname: str, port: int) -> bool | None:
    """Whether every address ``hostname`` resolves to is public.

    Returns ``None`` when the name does not resolve, ``False`` when any resolved address is
    loopback/private/link-local/reserved (for example ``127.0.0.1``, ``10.0.0.0/8``, or the
    cloud metadata address ``169.254.169.254``), else ``True``. This is the SSRF guard: a
    config-controlled ``deployment.domain`` cannot point the probe at an internal address.
    """
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except OSError:
        return None
    if not infos:
        return None
    return all(_is_global_address(str(info[4][0])) for info in infos)


def _validate_health_target(target: str) -> str | None:
    """Reject an unsafe health target, returning the reason, or ``None`` when it is safe.

    Treats the target as untrusted: the scheme must be http(s), userinfo is rejected, and the
    hostname must resolve to public addresses only. This closes the SSRF vectors before any
    connection is attempted.
    """
    parsed = urlsplit(target)
    reason: str | None = None
    if parsed.scheme not in ("http", "https"):
        reason = "unsupported target scheme"
    elif parsed.username or parsed.password:
        reason = "target must not contain credentials"
    elif not parsed.hostname:
        reason = "target has no host"
    else:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        public = _resolves_to_public_only(parsed.hostname, port)
        if public is None:
            reason = "host does not resolve"
        elif not public:
            reason = "host resolves to a non-public address"
    return reason


def _probe(target: str, timeout: int) -> HealthOutcome:
    """Perform the read-only GET (target already validated), refusing redirects."""
    opener = urllib.request.build_opener(_NoRedirectHandler())
    request = urllib.request.Request(target, method="GET")  # noqa: S310 - scheme + address class validated
    try:
        with opener.open(request, timeout=timeout) as response:
            return HealthOutcome(status_code=response.status, reachable=True)
    except urllib.error.HTTPError as exc:
        # The server responded (reachable), just not with success (a refused redirect lands here too).
        return HealthOutcome(status_code=exc.code, reachable=True)
    except (OSError, ValueError) as exc:
        # urllib.error.URLError subclasses OSError, so OSError covers it.
        return HealthOutcome(status_code=None, reachable=False, error=exc.__class__.__name__)


def _default_health_probe(target: str, timeout: int) -> HealthOutcome:
    """Read-only HTTP(S) GET of ``target`` with SSRF hardening; never sends credentials.

    The target (``deployment.domain`` from a supplied ``shifter.yaml``) is validated before
    connecting (:func:`_validate_health_target`) and redirects are refused. A narrow DNS-
    rebinding window remains between resolution and connect; it is accepted for this local
    pre-deploy tool because the response body is never read and the primary vectors (direct
    internal resolution, redirect-to-internal) are closed.
    """
    reason = _validate_health_target(target)
    if reason is not None:
        return HealthOutcome(status_code=None, reachable=False, error=reason)
    return _probe(target, timeout)


@dataclass(frozen=True)
class DoctorProbes:
    """The injectable execution seams doctor uses; defaults are the real implementations."""

    tool_probe: ToolProbe = _default_tool_probe
    command_runner: CommandRunner = _default_command_runner
    health_probe: HealthProbe = _default_health_probe


#: The default probe bundle wired to the real subprocess/network implementations.
DEFAULT_PROBES = DoctorProbes()
