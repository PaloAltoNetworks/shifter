"""Error model for root installation config loading and validation.

A single small exception type, :class:`InstallationConfigError`, carries a list of
:class:`ConfigIssue` records. There is deliberately no broader error hierarchy here:
callers (the ``shifter-config`` CLI, CI checks, and — later — deploy/doctor tooling)
only need "valid" vs "here are the problems", and Django-facing callers should keep
using their own validation/error response patterns rather than this type.

Issue records never carry the *input* that failed validation, so rendering an
``InstallationConfigError`` cannot leak a raw secret value that a user mistakenly
placed in the config.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfigIssue:
    """One problem found in a root installation config.

    Attributes:
        path: Dotted location of the problem (e.g. ``deployment.domain``), the file
            path for file-level problems (missing file, unparseable YAML), or
            ``"<root>"`` when the problem is not attributable to a specific key.
        message: Human-readable description naming what is wrong and, where useful,
            how to fix it. Never contains the rejected input value.
        hint: Optional extra remediation guidance.
    """

    path: str
    message: str
    hint: str | None = None

    def render(self) -> str:
        text = f"{self.path}: {self.message}"
        if self.hint:
            text += f" ({self.hint})"
        return text


class InstallationConfigError(Exception):
    """Raised when a root installation config is missing or invalid.

    The aggregated problems are available on :attr:`issues`.
    """

    def __init__(self, issues: list[ConfigIssue]) -> None:
        self.issues: list[ConfigIssue] = list(issues)
        super().__init__(self._render())

    def _render(self) -> str:
        if not self.issues:
            return "invalid root installation config"
        count = len(self.issues)
        noun = "problem" if count == 1 else "problems"
        lines = [f"invalid root installation config ({count} {noun}):"]
        lines.extend(f"  - {issue.render()}" for issue in self.issues)
        return "\n".join(lines)

    def __str__(self) -> str:
        return self._render()
