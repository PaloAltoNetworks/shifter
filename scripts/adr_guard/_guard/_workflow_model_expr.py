"""Constrained GitHub Actions ``if:`` expression model (`_dw_*`).

Split out of ``_workflow_model.py`` to keep each module under the file-length
limit; every public name here is re-imported by that module so the package
surface is unchanged.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass


_DW_RESULT_REF = re.compile(r"needs\.([A-Za-z0-9_-]+)\.result")
_DW_EXPR_TOKEN = re.compile(
    r"""\s+
        |(?P<str>'[^']*')
        |(?P<op>==|!=|&&|\|\||!|\(|\))
        |(?P<ident>[A-Za-z0-9_.\-]+)""",
    re.VERBOSE,
)
# `if:` accepts a condition with or without the `${{ }}` wrapper; the workflows
# here use both styles, so the evaluator normalizes to the bare expression.
_DW_EXPR_WRAPPER = re.compile(r"^\$\{\{(?P<body>.*)\}\}$", re.DOTALL)
# The one repository whose runs are the canonical CI. Steps that must not
# silently no-op compare `github.repository` against this literal rather than
# testing whether their configuration variables happen to be set (ADR-003-R7).
_DW_CANONICAL_REPOSITORY = "Brad-Edwards/shifter"


class _DwShapeError(Exception):
    """A deploy workflow is missing a structurally-required key.

    Raised instead of returning a default so the model fails closed: an absent
    job, filter, ``needs``, or ``if`` block is an error, never a silent
    "not applicable".
    """


class _DwExprError(_DwShapeError):
    """An ``if:`` expression used a construct the constrained evaluator rejects."""


def _dw_normalize_expr(expr: object) -> str:
    """Collapse whitespace (incl. block-scalar newlines) to single spaces."""
    return " ".join(str(expr or "").split())


def _dw_unwrap_expr(expr: str) -> str:
    """Strip a single enclosing ``${{ }}`` so the tokenizer sees a bare
    expression. Anything else is returned unchanged."""
    match = _DW_EXPR_WRAPPER.match(expr)
    return match.group("body").strip() if match else expr


def _dw_result_guarded_upstreams(if_expr: object) -> set[str]:
    """Upstream job ids referenced as ``needs.<job>.result`` in an ``if:``."""
    return set(_DW_RESULT_REF.findall(_dw_normalize_expr(if_expr)))


# --- Constrained GitHub Actions `if:` expression evaluator ----------------- #
# A substring check cannot PROVE fail-closed gating: an expression that also
# ORs in `failure`/`cancelled` still contains the `success || skipped` text,
# and a correct gate written a different way would be wrongly rejected. So the
# model parses the `if:` and evaluates the denied scenarios (`failure`,
# `cancelled`, `pull_request`) over the finite result/event vocabulary, then
# asserts the job does not run. Supports only the operators these workflows
# use - `==`, `!=`, `&&`, `||`, `!`, parentheses, string literals, and the
# `always()` status function; operands are `needs.<job>.result`,
# `needs.<job>.outputs.<key>`, `inputs.<key>`, `vars.<name>`, and
# `github.<field>`.
def _dw_truthy(value: object) -> bool:
    """Apply GitHub Actions truthiness: a non-empty string or a true boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value != ""
    return bool(value)


def _dw_loose_eq(left: object, right: object) -> bool:
    """Compare two operands the way the Actions ``==`` operator does."""
    # GitHub Actions `==` compares strings case-insensitively.
    if isinstance(left, str) and isinstance(right, str):
        return left.lower() == right.lower()
    return left == right


def _dw_call_function(name: str) -> bool:
    """Evaluate a zero-argument status function; any other call is rejected."""
    if name == "always":
        return True
    raise _DwExprError(f"unsupported function in if-expression: {name}()")


def _dw_tokenize(expr: str) -> list[tuple[str, str]]:
    """Tokenize an ``if:`` expression into ``(kind, text)`` pairs."""
    tokens: list[tuple[str, str]] = []
    pos, end = 0, len(expr)
    while pos < end:
        match = _DW_EXPR_TOKEN.match(expr, pos)
        if not match or match.end() == pos:
            raise _DwExprError(f"cannot tokenize: {expr[pos : pos + 20]!r}")
        pos = match.end()
        kind = match.lastgroup
        if kind == "str":
            tokens.append(("str", match.group("str")[1:-1]))
        elif kind == "op":
            tokens.append(("op", match.group("op")))
        elif kind == "ident":
            tokens.append(("ident", match.group("ident")))
        # whitespace (no named group) is skipped
    tokens.append(("end", ""))
    return tokens


class _DwParser:
    """Recursive-descent evaluator: `!` > comparison > `&&` > `||`."""

    def __init__(
        self, tokens: list[tuple[str, str]], resolve: Callable[[str], object]
    ) -> None:
        self._toks = tokens
        self._i = 0
        self._resolve = resolve

    def _peek(self) -> tuple[str, str]:
        return self._toks[self._i]

    def _advance(self) -> tuple[str, str]:
        tok = self._toks[self._i]
        self._i += 1
        return tok

    def _expect(self, op: str) -> None:
        if self._advance() != ("op", op):
            raise _DwExprError(f"expected {op!r}")

    def evaluate(self) -> object:
        value = self._parse_or()
        if self._peek()[0] != "end":
            raise _DwExprError(f"trailing tokens: {self._toks[self._i :]!r}")
        return value

    def _parse_or(self) -> object:
        value = self._parse_and()
        while self._peek() == ("op", "||"):
            self._advance()
            value = _dw_truthy(value) | _dw_truthy(self._parse_and())
        return value

    def _parse_and(self) -> object:
        value = self._parse_not()
        while self._peek() == ("op", "&&"):
            self._advance()
            value = _dw_truthy(value) & _dw_truthy(self._parse_not())
        return value

    def _parse_not(self) -> object:
        if self._peek() == ("op", "!"):
            self._advance()
            return not _dw_truthy(self._parse_not())
        return self._parse_cmp()

    def _parse_cmp(self) -> object:
        left = self._parse_primary()
        token = self._peek()
        if token in (("op", "=="), ("op", "!=")):
            self._advance()
            equal = _dw_loose_eq(left, self._parse_primary())
            return equal if token == ("op", "==") else not equal
        return left

    def _parse_primary(self) -> object:
        token = self._advance()
        if token == ("op", "("):
            value = self._parse_or()
            self._expect(")")
        elif token[0] == "str":
            value = token[1]
        elif token[0] == "ident":
            value = self._parse_ident(token[1])
        else:
            raise _DwExprError(f"unexpected token {token!r}")
        return value

    def _parse_ident(self, name: str) -> object:
        """Resolve an identifier: a zero-argument function call, or an operand."""
        if self._peek() == ("op", "("):
            self._advance()
            self._expect(")")
            return _dw_call_function(name)
        return self._resolve(name)


@dataclass(frozen=True)
class _DwScenario:
    """The context one ``if:`` evaluation runs against.

    Every field is permissive by default, so the only thing that flips an
    evaluation's outcome is the scenario under test (a failed upstream, a
    pull_request event, a fork's ``repository``, an unset repository variable).
    """

    results: Mapping[str, str] | None = None
    event_name: str = "workflow_dispatch"
    ref: str = "refs/heads/aws-dev"
    base_ref: str = ""
    repository: str = _DW_CANONICAL_REPOSITORY
    inputs_true: bool = True
    vars_set: bool = True
    fork_pr: bool = False


def _dw_resolve_needs(parts: list[str], scenario: _DwScenario) -> str:
    """Resolve a ``needs.<job>.<field>`` operand: unspecified results are
    ``success`` and every ``needs.*.outputs.*`` is ``true``."""
    if len(parts) < 3:
        raise _DwExprError(f"unresolvable operand: {'.'.join(parts)}")
    job, field = parts[1], parts[2]
    if field == "result":
        return (scenario.results or {}).get(job, "success")
    return "true" if field == "outputs" else "success"


def _dw_head_repo_full_name(scenario: _DwScenario) -> str:
    """Resolve ``github.event.pull_request.head.repo.full_name``.

    The head repo of a same-repo PR IS this repository; a fork-origin PR's head
    repo belongs to a different owner. This is the identity GitHub uses to
    withhold secrets, and unlike ``head.repo.fork`` it stays correct when the
    base repository is itself a fork of an upstream (which makes
    ``head.repo.fork`` true for every same-repo PR branch).
    """
    if not scenario.fork_pr:
        return scenario.repository
    return "fork-owner/" + scenario.repository.split("/", 1)[-1]


def _dw_resolve_github(path: str, parts: list[str], scenario: _DwScenario) -> str | bool:
    """Resolve a ``github.*`` operand against the scenario."""
    # Fork-origin PRs run in the base repository's context, so
    # `github.repository` alone cannot distinguish them.
    if path == "github.event.pull_request.head.repo.fork":
        return scenario.fork_pr
    if path == "github.event.pull_request.head.repo.full_name":
        return _dw_head_repo_full_name(scenario)
    field = parts[1] if len(parts) > 1 else ""
    return {
        "event_name": scenario.event_name,
        "ref": scenario.ref,
        "base_ref": scenario.base_ref,
        "repository": scenario.repository,
    }.get(field, "")


def _dw_resolve_operand(path: str, scenario: _DwScenario) -> str | bool:
    """Resolve one ``if:`` operand; an operand outside the model's vocabulary
    is an error rather than a silent default."""
    parts = path.split(".")
    head = parts[0]
    if head == "needs" and len(parts) >= 3:
        value = _dw_resolve_needs(parts, scenario)
    elif head == "inputs":
        value = scenario.inputs_true
    elif head == "vars":
        value = "true" if scenario.vars_set else ""
    elif path in ("true", "false"):
        value = path == "true"
    elif head == "github":
        value = _dw_resolve_github(path, parts, scenario)
    else:
        raise _DwExprError(f"unresolvable operand: {path}")
    return value


def _dw_evaluate_scenario(if_expr: object, scenario: _DwScenario) -> bool:
    """Evaluate a job or step ``if:`` against ``scenario``; return whether it
    would run."""
    expr = _dw_unwrap_expr(_dw_normalize_expr(if_expr))
    if not expr:
        # no `if:` at all is always eligible
        return True
    parser = _DwParser(
        _dw_tokenize(expr), lambda path: _dw_resolve_operand(path, scenario)
    )
    return _dw_truthy(parser.evaluate())


def _dw_evaluate_if(if_expr: object, **scenario: object) -> bool:
    """Evaluate a job or step ``if:`` against a permissive context; return
    whether it would run. Keyword arguments are the :class:`_DwScenario` fields:
    unspecified upstream results default to ``success``, every
    ``needs.*.outputs.*`` to ``true``, every ``inputs.*`` to ``inputs_true``,
    and every ``vars.*`` to a non-empty value when ``vars_set`` - so the only
    thing that flips the outcome is the scenario under test (a failed upstream,
    a pull_request event, a fork's ``repository``, an unset repository
    variable)."""
    return _dw_evaluate_scenario(if_expr, _DwScenario(**scenario))


def _dw_job_denied_when_upstream(if_expr: object, upstream: str, result: str) -> bool:
    """True iff the job does NOT run when ``upstream`` has ``result`` (every
    other condition permissive). Proves a failed/cancelled upstream blocks the
    deploy job (#781)."""
    return not _dw_evaluate_if(if_expr, results={upstream: result})


def _dw_job_denied_on_pull_request(if_expr: object) -> bool:
    """True iff the job does NOT run on a ``pull_request`` event (every other
    condition permissive). Proves PR events cannot reach the job (ADR-003-R5)."""
    return not _dw_evaluate_if(if_expr, event_name="pull_request")


def _dw_job_runs_when_eligible(if_expr: object) -> bool:
    """Sanity: the permissive context actually runs the job, so a denied-case
    assertion is meaningful and not vacuously satisfied."""
    return _dw_evaluate_if(if_expr)
