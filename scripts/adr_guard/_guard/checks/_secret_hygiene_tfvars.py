"""Plaintext-secret scanning for `*.tfvars` files (ADR-004-R7).

Split out of ``secret_hygiene.py`` to keep each module under the file-length
limit; every public name here is re-imported by that module so the package
surface is unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

from .._common import (
    Violation,
    _repo_relative,
)


_TFVARS_SCOPE = (
    "platform/terraform/environments",
    "platform/terraform/global",
)
_SECRET_NAME_GROUP = (
    r"((?:[A-Za-z_][A-Za-z0-9_]*"
    r"(?:_passwords?|_secrets?|_tokens?|_keys?|_credentials?|_authcodes?|_pin_values?))"
    r"|(?:authcodes?|pin_values?))"
)
_SECRET_VAR_PATTERN = re.compile(
    r"^\s*" + _SECRET_NAME_GROUP + r'\s*=\s*"[^"]+"',
)
# HCL also supports heredoc string literals (`name = <<EOF` /
# `name = <<-EOF`), which would otherwise bypass the line regex above.
_SECRET_HEREDOC_PATTERN = re.compile(
    r"^\s*" + _SECRET_NAME_GROUP + r"\s*=\s*<<-?[A-Za-z_][A-Za-z0-9_]*\s*$",
)
# Object / array assignments to secret-bearing variables. These are
# walked forward to the matching brace/bracket and flagged when any
# string literal appears inside.
_SECRET_BLOCK_OPEN_PATTERN = re.compile(
    r"^\s*" + _SECRET_NAME_GROUP + r"\s*=\s*([\{\[])",
)
# Generic single-line assignment to a secret-bearing variable. Used to
# catch function-wrapped string literals like
# `db_password = trimspace("...")` or `api_token = sensitive("...")`
# that the bare-string and block-open patterns above don't cover. The
# RHS is whatever follows `=` on the same line; the violation walker
# then scans for a string literal in that RHS (after stripping trailing
# # / // comments) and flags when present.
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*" + _SECRET_NAME_GROUP + r"\s*=\s*(.+)$",
)
_STRING_LITERAL_PATTERN = re.compile(r'"[^"]+"')
_BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
# Variable-name suffixes that mark share-only material (SSH/JWT public
# keys, authorized_keys files, public certificates) so the suffix-based
# regex doesn't over-flag them. Matched against `var_name.endswith(...)`
# so a variable like `public_key_password` is NOT exempted (the secret
# suffix `_password` still wins, even though `public_key` appears in
# the name).
_NON_SECRET_NAME_SUFFIXES = (
    "_public_key",
    "_public_keys",
    "_public_cert",
    "_public_certs",
    "_pub_key",
    "_pub_keys",
    "_pubkey",
    "_pubkeys",
    "_authorized_keys",
    "public_key",
    "public_keys",
    "public_cert",
    "public_certs",
    "pub_key",
    "pub_keys",
    "pubkey",
    "pubkeys",
    "authorized_keys",
)


def _strip_hcl_comments(text: str) -> str:
    """Replace HCL block comments with whitespace (preserving newlines).

    Line comments (`#`, `//`) are handled per-line by the caller so it can
    keep line numbers aligned for violation reporting. Block comments are
    stripped here because they can span lines; we replace each character
    with whitespace except newlines so subsequent regexes still see the
    same line numbers.
    """

    def _blank(match: re.Match[str]) -> str:
        """Replace a matched block comment with same-shape whitespace."""
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return _BLOCK_COMMENT_PATTERN.sub(_blank, text)


def _is_line_commented(line: str) -> bool:
    """True when the line's first non-whitespace token opens a `#` / `//` comment."""
    stripped = line.lstrip()
    return stripped.startswith(("#", "//"))


def _strip_trailing_line_comment(line: str) -> str:
    """Drop trailing `#` or `//` line-comment tail from an HCL line.

    Walks the line keeping track of whether we're inside a `"..."`
    string so a `#` or `//` inside a string is preserved.
    """
    in_string = False
    escape = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "#":
                return line[:i]
            elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                return line[:i]
        i += 1
    return line


def _balance_scan(chars: str, depth: int) -> tuple[int, bool, bool]:
    """Scan ``chars`` updating the ``()``/``[]``/``{}`` ``depth``.

    Returns ``(new_depth, saw_delimiter, closed_to_zero)``. ``closed_to_zero``
    is ``True`` the moment depth drops to ``<= 0`` — the expression closed
    within ``chars``.
    """
    saw = False
    for ch in chars:
        if ch in "([{":
            depth += 1
            saw = True
        elif ch in ")]}":
            depth -= 1
            saw = True
            if depth <= 0:
                return depth, saw, True
    return depth, saw, False


def _block_depth_scan(chars: str, depth: int, opener: str, closer: str) -> tuple[int, bool]:
    """Scan ``chars`` updating the ``opener``/``closer`` ``depth``.

    Returns ``(new_depth, closed_to_zero)``; ``closed_to_zero`` is ``True``
    the moment depth returns to ``0``.
    """
    for ch in chars:
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return depth, True
    return depth, False


def _scrub_line(line: str) -> str:
    """Blank out ``"..."`` string contents and drop the trailing ``#``/``//``
    line comment so brace/paren counting ignores both.
    """
    return _strip_trailing_line_comment(_STRING_LITERAL_PATTERN.sub('""', line))


def _find_balanced_close_index(lines: list[str], start_idx: int, start_pos: int) -> int | None:
    """Walk forward from ``lines[start_idx][start_pos:]`` tracking the
    running depth of ``()``/``[]``/``{}`` (string-literal- and line-comment-aware)
    until the depth returns to zero. Returns the line index containing
    the closing delimiter, or ``None`` if no balance by end-of-file. A start
    line with no delimiter at all is treated as the close (nothing to balance).

    Used by the wrapped-expression arm of the secrets check so multi-line
    wrappers like ``db_password = jsonencode({\\n  password = "leak"\\n})``
    are walked across newlines and scanned for inner string literals.
    """
    depth = 0
    started = False
    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        if _is_line_commented(line):
            continue
        offset = start_pos if idx == start_idx else 0
        depth, saw, closed = _balance_scan(_scrub_line(line)[offset:], depth)
        if saw:
            started = True
        if closed:
            return idx
        if not started:
            # no opener on the start line — nothing to balance
            return idx
    return None


def _find_block_close_index(lines: list[str], start_idx: int, opener: str) -> int | None:
    """Return the line index containing the brace/bracket that closes the block.

    ``opener`` is ``"{"`` or ``"["``; matched closer is ``"}"`` / ``"]"``. The
    walk treats string literals and ``#`` / ``//`` line comments as inert
    (their contents don't change the brace count). Returns the matching line
    index, or ``None`` if no close is found by end-of-file.
    """
    closer = "}" if opener == "{" else "]"
    depth = 0
    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        if _is_line_commented(line):
            continue
        depth, closed = _block_depth_scan(_scrub_line(line), depth, opener, closer)
        if closed:
            return idx
    return None


def _collect_tfvars_candidates(repo_root: Path, files: list[str] | None) -> list[Path]:
    """Resolve the ``*.tfvars`` files in scope: the subset of ``files`` that
    sits under ``platform/terraform/environments/`` when an explicit list is
    given, otherwise every ``*.tfvars`` file under that tree.
    """
    if files is not None:
        in_scope = [p for p in files if p.startswith(_TFVARS_SCOPE) and p.endswith(".tfvars")]
        return [repo_root / p for p in in_scope]
    candidates: list[Path] = []
    for scope in _TFVARS_SCOPE:
        base = repo_root / scope
        if not base.exists():
            continue
        candidates.extend(p for p in base.rglob("*.tfvars") if p.is_file() and not p.is_symlink())
    return candidates


def _is_public_material_name(var_name: str) -> bool:
    """``True`` for names ending in a public-material suffix (``*_public_key``,
    ``*_authorized_keys``, ``*_pubkey``, …) — material that is share-only by
    design, so a string literal there is not a leaked secret.
    """
    return any(var_name.endswith(suffix) for suffix in _NON_SECRET_NAME_SUFFIXES)


def _lines_have_string_literal(lines: list[str], start_idx: int, end_idx: int) -> bool:
    """``True`` if any line in ``lines[start_idx:end_idx + 1]`` carries a
    ``"..."`` literal once full-line comments are skipped and trailing
    ``#``/``//`` comment tails are stripped.
    """
    for idx in range(start_idx, end_idx + 1):
        inner = lines[idx]
        if _is_line_commented(inner):
            continue
        if _STRING_LITERAL_PATTERN.search(_strip_trailing_line_comment(inner)):
            return True
    return False


def _wrapped_rhs_has_literal(lines: list[str], idx: int, line: str, rhs: str) -> bool:
    """``True`` if a function-wrapped / expression RHS of a secret assignment
    materializes a string literal — scanning the RHS on the assignment line
    and, when it opens a balanced ``()``/``[]``/``{}`` that spans lines, the
    rest of the multi-line expression.
    """
    if _STRING_LITERAL_PATTERN.search(_strip_trailing_line_comment(rhs)):
        return True
    close_idx = _find_balanced_close_index(lines, idx, line.find("=") + 1)
    if close_idx is None or close_idx <= idx:
        return False
    return _lines_have_string_literal(lines, idx + 1, close_idx)


def _block_assignment_has_literal(lines: list[str], idx: int, opener: str) -> bool:
    """``True`` if the object/array block opened on ``lines[idx]`` carries a
    string literal somewhere between the opener and its matching close (an
    empty block, or one composed solely of var/local/data references, is
    acceptable). A block whose close is never found scans to end-of-file.
    """
    close_idx = _find_block_close_index(lines, idx, opener)
    end_idx = close_idx if close_idx is not None else len(lines) - 1
    return _lines_have_string_literal(lines, idx, end_idx)


def _flagged_secret_var(lines: list[str], idx: int) -> str | None:
    """Return the secret-bearing variable on ``lines[idx]`` that is assigned a
    plaintext string literal — directly, via a heredoc, via an object/array
    block, or wrapped in a function/expression — or ``None`` when the line is
    clean or the variable name is public material.
    """
    line = lines[idx]
    # Priority: a direct ``= "..."`` / heredoc literal, then an object/array
    # block, then any other RHS expression. ``_SECRET_ASSIGNMENT_PATTERN`` is
    # the catch-all, so it is consulted last.
    direct = _SECRET_VAR_PATTERN.match(line) or _SECRET_HEREDOC_PATTERN.match(line)
    block_match = _SECRET_BLOCK_OPEN_PATTERN.match(line)
    wrapped = _SECRET_ASSIGNMENT_PATTERN.match(line)
    match = direct or block_match or wrapped
    if match is None:
        return None
    var_name = match.group(1)
    if _is_public_material_name(var_name):
        return None
    if direct is not None:
        materializes_literal = True
    elif block_match is not None:
        materializes_literal = _block_assignment_has_literal(lines, idx, block_match.group(2))
    else:
        materializes_literal = _wrapped_rhs_has_literal(lines, idx, line, wrapped.group(2))
    return var_name if materializes_literal else None


def _scan_tfvars_file(path: Path, repo_root: Path) -> list[Violation]:
    """Scan one ``*.tfvars`` file for plaintext-secret assignments (ADR-004-R7).

    Block comments are spanned BEFORE line splitting so their contents
    (including any ``password = "..."`` examples) cannot trigger the regex;
    line numbers are preserved.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = _strip_hcl_comments(raw_text).splitlines()
    rel = _repo_relative(path, repo_root)
    violations: list[Violation] = []
    for idx, line in enumerate(lines):
        if _is_line_commented(line):
            continue
        var_name = _flagged_secret_var(lines, idx)
        if var_name is None:
            continue
        violations.append(
            Violation(
                "no-plaintext-secrets-in-tfvars",
                "ADR-004-R7",
                rel,
                f"Line {idx + 1}: {var_name!r} is assigned a "
                f"plaintext string literal; reference an out-of-band "
                f"secret store (Secrets Manager, SSM, environment) instead",
            )
        )
    return violations


def check_no_plaintext_secrets_in_tfvars(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid string literals on secret-bearing tfvars assignments (ADR-004-R7).

    Scans ``*.tfvars`` files committed under the Terraform environment and
    global trees and flags any line that assigns a quoted string to a variable
    whose name ends in ``password``, ``secret``, ``token``, ``key``,
    ``credentials``, ``credential``, ``authcode``, ``authcodes``, or
    ``pin_value``. Bare ``authcode`` / ``pin_value`` names are also flagged.
    Var/local/data references and empty strings are allowed
    (they don't materialize a credential in source). ``*.tfvars.example`` files
    and full-line comments are skipped.

    gitleaks catches high-entropy random strings; this is the complementary
    backstop for low-entropy committed credentials that gitleaks ignores
    (e.g. human-typed passwords with mixed case and a single digit suffix).
    """
    violations: list[Violation] = []
    for path in _collect_tfvars_candidates(repo_root, files):
        if path.exists():
            violations.extend(_scan_tfvars_file(path, repo_root))
    return violations


__all__ = [
    "_BLOCK_COMMENT_PATTERN",
    "_NON_SECRET_NAME_SUFFIXES",
    "_SECRET_ASSIGNMENT_PATTERN",
    "_SECRET_BLOCK_OPEN_PATTERN",
    "_SECRET_HEREDOC_PATTERN",
    "_SECRET_NAME_GROUP",
    "_SECRET_VAR_PATTERN",
    "_STRING_LITERAL_PATTERN",
    "_TFVARS_SCOPE",
    "_balance_scan",
    "_block_assignment_has_literal",
    "_block_depth_scan",
    "_collect_tfvars_candidates",
    "_find_balanced_close_index",
    "_find_block_close_index",
    "_flagged_secret_var",
    "_is_line_commented",
    "_is_public_material_name",
    "_lines_have_string_literal",
    "_scan_tfvars_file",
    "_scrub_line",
    "_strip_hcl_comments",
    "_strip_trailing_line_comment",
    "_wrapped_rhs_has_literal",
    "check_no_plaintext_secrets_in_tfvars",
]
