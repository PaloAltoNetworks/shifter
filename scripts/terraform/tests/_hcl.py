"""Minimal HCL block extraction for structural Terraform invariant tests.

Static invariant tests read live Terraform text. Asserting that a keyword
appears *anywhere* in a file is weak: it stays green when two adjacent
resources' arguments are swapped, because both resources' labels and literals
are still present regardless of how they are wired. Scoping an assertion to the
block that actually owns the property makes the test fail when the wiring is
wrong rather than only when a literal disappears (#1846).

Deliberately small: brace-depth scanning over `terraform fmt`-normalised files,
which is all these structural tests need. It is not a general HCL parser.
"""

from __future__ import annotations

import re


def resource_block(hcl: str, resource_type: str, label: str) -> str:
    """Return the body of ``resource "<resource_type>" "<label>"``.

    Raises AssertionError when the resource is absent, so a renamed or deleted
    resource fails loudly instead of silently satisfying a substring check.
    """
    description = f'resource "{resource_type}" "{label}"'
    pattern = rf'resource\s+"{re.escape(resource_type)}"\s+"{re.escape(label)}"\s*\{{'
    match = re.search(pattern, hcl)
    assert match is not None, f"{description} not found"

    start = match.end() - 1  # position of the opening brace
    depth = 0
    for index in range(start, len(hcl)):
        char = hcl[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return hcl[start : index + 1]
    raise AssertionError(f"{description} block is unterminated")


def statement_containing(policy_block: str, needle: str) -> str:
    """Return the single ``jsonencode`` Statement object containing ``needle``.

    IAM evaluates each Statement independently, so an Action is only as scoped
    as the Resource in its *own* statement. Asserting that an action and a
    resource both appear somewhere in a policy passes even when the action sits
    in a neighbouring ``Resource = "*"`` statement (#1846).
    """
    matches = [s for s in _statements(policy_block) if needle in s]
    assert matches, f"no statement containing {needle!r}"
    assert len(matches) == 1, f"{needle!r} appears in {len(matches)} statements; expected 1"
    return matches[0]


def _statements(policy_block: str) -> list[str]:
    """Return each top-level object inside the policy's ``Statement`` array."""
    marker = re.search(r"Statement\s*=\s*\[", policy_block)
    assert marker is not None, "policy has no Statement array"

    statements: list[str] = []
    depth = 0
    start = -1
    for index in range(marker.end(), len(policy_block)):
        char = policy_block[index]
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                statements.append(policy_block[start : index + 1])
                start = -1
        elif char == "]" and depth == 0:
            break  # end of the Statement array
    return statements
