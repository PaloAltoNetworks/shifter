"""MCP policy checks: no shell exec, ops TLS strict (JS/TS source scanning)."""
from __future__ import annotations

import re
from pathlib import Path

from .._common import (
    Violation,
    _repo_relative,
)


# child_process import shapes we care about (any form — named, default,
# namespace, CJS destructure, bare CJS require — with or without the
# `node:` prefix). We require the import as evidence that this file
# really pulls Node's child_process; without it, an `execSync` token
# could be an unrelated function with the same name.
_CHILD_PROCESS_IMPORT = re.compile(
    r"""(?x)
    (
        from\s*["'](?:node:)?child_process["']
    )
    |
    (
        require\s*\(\s*["'](?:node:)?child_process["']\s*\)
    )
    """,
)
# `execSync as <alias>` in an ESM named-import. Captures the alias
# so we can search for `<alias>(` as a call site too.
_EXEC_SYNC_ALIAS = re.compile(r"\bexecSync\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)")


# Tiny per-state helpers for _strip_js_comments_and_strings.
# Splitting the state machine across these helpers keeps per-function
# cognitive complexity low and avoids a single mega-regex whose
# alternation complexity tripped SonarCloud. Each helper consumes one
# or two characters and returns the next loop state.

_BLANK_KEEP_NEWLINES = {"\n": "\n"}


def _blank_for(ch: str) -> str:
    """Whitespace replacement for a consumed character, keeping newlines intact."""
    return _BLANK_KEEP_NEWLINES.get(ch, " ")


def _consume_code(text: str, i: int) -> tuple[int, str, str, str]:
    """Code state. Detects start of comment / string / nothing."""
    nxt = text[i + 1] if i + 1 < len(text) else ""
    ch = text[i]
    if ch == "/" and nxt in ("/", "*"):
        return i + 2, "  ", "line_comment" if nxt == "/" else "block_comment", ""
    if ch in ("'", '"', "`"):
        return i + 1, " ", "string", ch
    return i + 1, ch, "code", ""


def _consume_line_comment(text: str, i: int) -> tuple[int, str, str, str]:
    """Line-comment state. Returns to code at the newline, blanking the body."""
    ch = text[i]
    if ch == "\n":
        return i + 1, "\n", "code", ""
    return i + 1, " ", "line_comment", ""


def _consume_block_comment(text: str, i: int) -> tuple[int, str, str, str]:
    """Block-comment state. Returns to code at `*/`, blanking the body."""
    nxt = text[i + 1] if i + 1 < len(text) else ""
    ch = text[i]
    if ch == "*" and nxt == "/":
        return i + 2, "  ", "code", ""
    return i + 1, _blank_for(ch), "block_comment", ""


def _consume_string(text: str, i: int, quote: str) -> tuple[int, str, str, str]:
    """String state. Returns to code at the matching `quote`, blanking the body."""
    nxt = text[i + 1] if i + 1 < len(text) else ""
    ch = text[i]
    if ch == "\\" and nxt:
        # Two-char escape consumed as whitespace; backslash never
        # closes the string prematurely.
        return i + 2, "  ", "string", quote
    if ch == quote:
        return i + 1, " ", "code", ""
    return i + 1, _blank_for(ch), "string", quote


def _strip_line_comment(text: str, i: int, n: int) -> tuple[str, int]:
    """Consume a `//` line comment starting at `i` and return
    `(spaces, new_index)`. Newlines are preserved so line numbers
    stay correct."""
    end = text.find("\n", i + 2)
    if end == -1:
        return " " * (n - i), n
    return " " * (end - i), end


def _strip_block_comment(text: str, i: int, n: int) -> tuple[str, int]:
    """Consume a `/* */` block comment starting at `i`. Replace its
    body with whitespace; preserve newlines."""
    end = text.find("*/", i + 2)
    if end == -1:
        return " " * (n - i), n
    segment = text[i : end + 2]
    return "".join(c if c == "\n" else " " for c in segment), end + 2


def _scan_to_closing_quote(text: str, start: int, n: int, quote: str) -> int:
    """Return the index just past the matching closing quote starting
    at `start`. Handles backslash escapes."""
    j = start
    while j < n:
        if text[j] == "\\" and j + 1 < n:
            j += 2
            continue
        if text[j] == quote:
            return j + 1
        j += 1
    return j


def _strip_js_comments_only(text: str) -> str:
    """Replace JS `//` and `/* */` comment contents with whitespace,
    preserve string-literal contents verbatim.

    Used by `mcp-ops-tls-strict` (#1190 / codex review #1180 cycle 1
    finding 7): the previous full strip erased quoted property keys
    like `{ "rejectUnauthorized": false }` along with the legitimate
    string-literal documentation neighbours. Stripping only comments
    keeps the quoted-key form visible to the regex while still
    suppressing false-positives from explanatory `//` comments.
    """
    out: list[str] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            emit, i = _strip_line_comment(text, i, n)
            out.append(emit)
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            emit, i = _strip_block_comment(text, i, n)
            out.append(emit)
            continue
        if ch in ('"', "'"):
            end = _scan_to_closing_quote(text, i + 1, n, ch)
            out.append(text[i:end])
            i = end
            continue
        if ch == "`":
            end = _scan_to_closing_quote(text, i + 1, n, "`")
            out.append(text[i:end])
            i = end
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_js_comments_and_strings(text: str) -> str:
    """Flatten JS string-literal and comment contents to whitespace.

    Newlines are preserved so error positions stay sane and so `^` /
    line-mode regexes still work. Template-literal substitutions
    (`${...}`) are intentionally not parsed; an `execSync(` inside a
    `` `${...}` `` substitution is a vanishingly rare bypass and falls
    under code-review, not regex.
    """
    out: list[str] = []
    n = len(text)
    i = 0
    state = "code"
    quote = ""
    while i < n:
        if state == "code":
            i, emit, state, quote = _consume_code(text, i)
        elif state == "line_comment":
            i, emit, state, quote = _consume_line_comment(text, i)
        elif state == "block_comment":
            i, emit, state, quote = _consume_block_comment(text, i)
        else:
            # state == "string"
            i, emit, state, quote = _consume_string(text, i, quote)
        out.append(emit)
    return "".join(out)


def _build_call_site_pattern(aliases: list[str]) -> re.Pattern[str]:
    """Pattern matching `execSync(` / `exec(` and any captured alias `(`.

    `exec` and `execSync` are the two child_process call shapes that
    take a shell command string. `spawnSync(... { shell: true })` is
    handled by a separate matcher because it requires looking at the
    options object as well as the function name.

    Using `(?<![A-Za-z0-9_$])` rejects unrelated identifiers that
    happen to end in `exec` or `execSync` (e.g. `myExecSync`,
    `regexExec`).
    """
    names = ["execSync", "exec", *aliases]
    alt = "|".join(re.escape(name) for name in names)
    return re.compile(rf"(?<![A-Za-z0-9_$])(?:{alt})\s*\(")


# `spawn` / `spawnSync` / `execFile` / `execFileSync` with
# `{ shell: true }` is just as bad as `exec` from a shell-string
# point of view; the option re-routes the call through `/bin/sh -c`.
# We match the function name immediately followed (eventually) by an
# options object that contains `shell: true`. Because we cannot parse
# JS in a regex, the matcher is intentionally generous: any `shell:
# true` within ~400 characters of a `spawn`/`execFile` call counts.
_SHELL_TRUE_SPAWN = re.compile(
    r"""(?xs)
    (?<![A-Za-z0-9_$])
    (?:spawnSync|spawn|execFileSync|execFile)
    \s*\([^)]{0,400}?
    \bshell\s*:\s*true\b
    """,
)

_JS_SUFFIXES = (".js", ".mjs", ".cjs")
_EXEC_CALL_MESSAGE = (
    "Calls exec/execSync from child_process; MCP servers must invoke external CLIs "
    "via argv arrays (spawn/spawnSync/execFile)"
)
_SHELL_TRUE_MESSAGE = (
    "Uses spawn/spawnSync/execFile/execFileSync with { shell: true }; MCP servers must "
    "invoke external CLIs via argv arrays without a shell"
)


def _js_candidate_paths(repo_root: Path, files: list[str] | None, scan_root: Path, prefix: str) -> list[Path]:
    """JS/MJS/CJS candidates: the `prefix`-scoped subset of `files`, or a full scan."""
    if files is not None:
        return [repo_root / path for path in files if path.startswith(prefix) and path.endswith(_JS_SUFFIXES)]
    return [
        p
        for p in scan_root.rglob("*")
        if p.is_file() and p.suffix in _JS_SUFFIXES and "node_modules" not in p.parts
    ]


def _read_js_source(path: Path) -> str | None:
    """Read a candidate JS file, returning None when it is missing or unreadable."""
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _shell_exec_violation(path: Path, repo_root: Path) -> Violation | None:
    """Return the ADR-010-R1 violation for one mcp/ JS file, or None when clean."""
    text = _read_js_source(path)
    # Import detection runs on raw text so the matched
    # `"child_process"` string literal is preserved.
    if text is None or not _CHILD_PROCESS_IMPORT.search(text):
        return None

    # Alias and call-site detection run on the comment-and-string
    # flattened form so that an `execSync(` token inside a comment
    # or string cannot trigger the check, a real `execSync(` call
    # on a line containing a URL like `"https://..."` is not
    # erased, and a comment like `// execSync as run` cannot
    # synthesise a fake alias that turns innocent `run(` calls
    # into false positives.
    stripped = _strip_js_comments_and_strings(text)
    aliases = _EXEC_SYNC_ALIAS.findall(stripped)
    if _build_call_site_pattern(aliases).search(stripped):
        message = _EXEC_CALL_MESSAGE
    elif _SHELL_TRUE_SPAWN.search(stripped):
        message = _SHELL_TRUE_MESSAGE
    else:
        return None
    return Violation("mcp-no-shell-exec", "ADR-010-R1", _repo_relative(path, repo_root), message)


def check_mcp_no_shell_exec(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid execSync call sites in mcp/ servers (ADR-010-R1).

    Static lower bound for catching shell-string aws-cli invocations:
    if a file under mcp/ both imports `child_process` (in any form —
    named ESM, default ESM, namespace ESM, named CJS, or whole-module
    CJS — including the `node:` prefix) AND contains an `execSync(`
    or aliased call site (`import { execSync as run } ... run(...)`),
    flag it. String literals and comments are flattened to whitespace
    first so they cannot false-positive trip the check or hide a
    real call site. Exceptions (e.g. mcp/ngfw) are filtered through
    docs/adr/exceptions.yaml.

    Static analysis cannot catch every motivated bypass (e.g.
    `const run = cp.execSync; run(...)`); ADR-010 is enforced at
    multiple layers and the static check is the cheap pre-commit
    backstop, not the only line of defence.
    """
    mcp_root = repo_root / "mcp"
    if not mcp_root.exists():
        return []

    violations: list[Violation] = []
    for path in _js_candidate_paths(repo_root, files, mcp_root, "mcp/"):
        violation = _shell_exec_violation(path, repo_root)
        if violation is not None:
            violations.append(violation)
    return violations


# Issue #1190 — mcp/ops Postgres TLS verification must stay on. This
# is a defense-in-depth backstop for `mcp/ops/lib.js::buildPoolConfig`,
# which is the single place that builds the pg.Pool TLS config. The
# guardrail flags any other file under `mcp/ops/` that introduces
# `rejectUnauthorized: false` (or `0`/`null`), even in a different
# call site, before code review notices.
#
# The regex matches BOTH the unquoted `rejectUnauthorized: false`
# property form AND the quoted property-name forms
# `"rejectUnauthorized": false` / `'rejectUnauthorized': false`.
# Stripping JS strings before matching would erase the quoted-key
# form (codex #1180 cycle 1 finding 7) so we match against raw text.
# A comment line literally containing this token is rare enough that
# the false-positive risk is bounded; in that case the reviewer
# rewrites the comment, which is the right outcome anyway.
_REJECT_UNAUTH_FALSE = re.compile(
    r"""["']?rejectUnauthorized["']?\s*:\s*(?:false|0|null)\b""",
    re.IGNORECASE,
)


def check_mcp_ops_tls_strict(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid `rejectUnauthorized: false` under mcp/ops (ADR-014-R7).

    The `mcp/ops` MCP server connects to RDS Postgres via an SSM port
    forward. Issue #1190 — the previous implementation disabled TLS
    verification to work around the cert/host mismatch caused by the
    tunnel. `buildPoolConfig` (in `mcp/ops/lib.js`) now sets
    `ssl.servername` to the captured RDS endpoint so verification fires
    against the real RDS cert; the `rejectUnauthorized: false` escape
    hatch is removed.

    This check scans the JS/MJS/CJS files under `mcp/ops/` (excluding
    `node_modules/`) for any reintroduction of
    `rejectUnauthorized: false` (or `0`/`null`). Matches both
    unquoted property keys (`rejectUnauthorized: false`) and quoted
    property keys (`"rejectUnauthorized": false`,
    `'rejectUnauthorized': false`) so JSON-shaped config cannot
    re-introduce the setting under the guard's nose.
    """
    ops_root = repo_root / "mcp" / "ops"
    if not ops_root.exists():
        return []

    violations: list[Violation] = []
    for path in _js_candidate_paths(repo_root, files, ops_root, "mcp/ops/"):
        text = _read_js_source(path)
        if text is None:
            continue
        # Strip comments only (not strings) so:
        #   - `// rejectUnauthorized: false` doc comments do not trip.
        #   - quoted-key forms `{ "rejectUnauthorized": false }` still
        #     match the regex (codex review #1180 cycle 1 finding 7).
        comment_stripped = _strip_js_comments_only(text)
        if _REJECT_UNAUTH_FALSE.search(comment_stripped):
            rel = _repo_relative(path, repo_root)
            violations.append(
                Violation(
                    check="mcp-ops-tls-strict",
                    rule_id="ADR-014-R7",
                    path=rel,
                    message=(
                        "Postgres TLS verification must stay enabled. "
                        "Use buildPoolConfig() in mcp/ops/lib.js, which sets "
                        "ssl.servername to the captured RDS endpoint so cert "
                        "verification fires against RDS, not localhost."
                    ),
                )
            )
    return violations
