"""Range runner-container command execution.

Adapters execute the participant path from inside the same runner containers
participants pivot through (a14-kali, a15-ops-eng, a16-research-analyst,
a9-splice). Commands are passed as argv arrays through ``docker exec`` so that
challenge metadata, hostnames, and other untrusted strings are never evaluated
by a shell.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

# Docker object names: alphanumerics plus a small punctuation set. This refuses
# anything that could carry shell metacharacters even though argv-array exec
# would not interpret them — defence in depth at the boundary.
_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class ExecResult:
    """Result of one command executed in a runner container."""

    returncode: int
    stdout: str
    stderr: str


def _default_run(argv: list[str], *, input: str | None, timeout: int) -> ExecResult:
    completed = subprocess.run(  # noqa: S603 - argv array, no shell
        argv,
        input=input,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return ExecResult(completed.returncode, completed.stdout, completed.stderr)


class Runner:
    """Executes commands inside range runner containers via ``docker exec``."""

    def __init__(
        self,
        docker: str = "docker",
        runner_run=None,
    ) -> None:
        self._docker = docker
        self._run = runner_run or (
            lambda argv, input=None, timeout=60: _default_run(
                argv, input=input, timeout=timeout
            )
        )

    def exec(
        self,
        container: str,
        argv: list[str],
        *,
        input: str | None = None,
        timeout: int = 60,
    ) -> ExecResult:
        """Run ``argv`` inside ``container`` and return its result."""
        if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
            raise TypeError("argv must be a list of strings, not a shell string")
        if not _CONTAINER_RE.match(container):
            raise ValueError(f"invalid container name: {container!r}")
        full = [self._docker, "exec", container, *argv]
        return self._run(full, input=input, timeout=timeout)
