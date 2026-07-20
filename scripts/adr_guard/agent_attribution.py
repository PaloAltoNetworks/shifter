"""Detect prohibited AI/agent attribution in commit messages and tracked text."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Attribution markers only — not general mentions of cursor.com in docs or IAM names.
_ATTRIBUTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "co-authored-by-cursor",
        re.compile(r"(?im)^Co-authored-by:\s*Cursor\b"),
    ),
    (
        "co-authored-by-cursoragent",
        re.compile(r"(?im)^Co-authored-by:.*cursoragent@", re.IGNORECASE),
    ),
    (
        "co-authored-by-claude",
        re.compile(r"(?im)^Co-authored-by:\s*.*\bClaude\b"),
    ),
    (
        "co-authored-by-codex",
        re.compile(r"(?im)^Co-authored-by:\s*.*\bCodex\b"),
    ),
    (
        "co-authored-by-composer",
        re.compile(r"(?im)^Co-authored-by:\s*.*\bComposer\b"),
    ),
    (
        "made-with-cursor-footer",
        re.compile(r"Made with \[Cursor\]\(https://cursor\.com\)", re.IGNORECASE),
    ),
    (
        "made-with-cursor-trailer",
        re.compile(r"(?im)^Made-with:\s*Cursor\b"),
    ),
    (
        "generated-with-claude-code",
        re.compile(r"Generated with Claude Code", re.IGNORECASE),
    ),
)


@dataclass(frozen=True)
class AgentAttributionMatch:
    """One prohibited attribution marker."""

    rule: str
    excerpt: str


def find_agent_attribution_matches(text: str) -> list[AgentAttributionMatch]:
    """Return every prohibited attribution marker found in ``text``."""
    matches: list[AgentAttributionMatch] = []
    for rule, pattern in _ATTRIBUTION_PATTERNS:
        for found in pattern.finditer(text):
            excerpt = found.group(0).strip()
            if len(excerpt) > 120:
                excerpt = excerpt[:117] + "..."
            matches.append(AgentAttributionMatch(rule=rule, excerpt=excerpt))
    return matches
