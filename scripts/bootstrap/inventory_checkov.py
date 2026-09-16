"""Run pinned Checkov with GitHub's immutable-subject grammar compatibility.

Only CKV_GCP_125's repository-segment parser is extended. Its evaluation, result
reporting and exit status remain upstream behavior. The full resolved-policy
verifier independently checks every subject and binding before this scan.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import re

CHECKOV_VERSION = "3.2.534"
LEGACY_PATTERN = r"(\$\{)?[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)*(\})?/[^/]+"
IMMUTABLE_PATTERN = r"[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*@[0-9]+/[a-zA-Z0-9_.-]+@[0-9]+\Z"


def repository_pattern(legacy_pattern: str) -> re.Pattern[str]:
    """Extend only the known pinned parser, refusing unexpected upstream drift."""
    if legacy_pattern != LEGACY_PATTERN:
        raise RuntimeError("Checkov repository parser changed; review compatibility adapter")
    return re.compile(f"(?:{legacy_pattern})|(?:{IMMUTABLE_PATTERN})")


def main() -> int:
    """Apply the bounded parser repair and preserve the scanner's exit status."""
    if importlib.metadata.version("checkov") != CHECKOV_VERSION:
        raise RuntimeError("Checkov version differs from the reviewed bootstrap pin")
    rule = importlib.import_module("checkov.terraform.checks.resource.gcp.GithubActionsOIDCTrustPolicy")
    rule.gh_repo_regex = repository_pattern(rule.gh_repo_regex.pattern)
    scanner = importlib.import_module("checkov.main")
    return scanner.Checkov().run()


if __name__ == "__main__":
    raise SystemExit(main())
