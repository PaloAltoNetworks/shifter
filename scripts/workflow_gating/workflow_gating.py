"""Parse the deploy GitHub Actions workflows as data and expose the gating
invariants asserted by ``test_workflow_gating.py`` (GitHub #921).

This module performs NO cloud calls, runs NO GitHub Actions jobs, and reads
only workflow YAML under ``.github/workflows/``. It is test-support code; no
production code imports it. See
``docs/architecture/workflow-gating-test-suite-preflight-921.md``.

Guards: #781 (upstream deploy gating), #892 (branch/event routing),
#913 / R-A2 (portal_image vs shifter_platform change-filter split), and the
runner-exposure fix (no pull_request path to a self-hosted apply/deploy job).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# Reusable workflows that deploy.yml fans out to. Their self-hosted apply /
# deploy jobs are the runner-exposure boundary.
REUSABLE_DEPLOY_WORKFLOWS = (
    "_core.yml",
    "_range.yml",
    "_shifter-engine.yml",
    "_shifter-platform.yml",
    "_gcp-dev.yml",
)

# Self-hosted jobs that are intentionally reachable from pull_request events
# because they only run `terraform plan` and post a PR comment (read-only).
# Every other self-hosted job must block pull_request (runner-exposure fix).
# The suite additionally asserts these stay free of mutation steps, so a
# mutation cannot be smuggled into an allowlisted "plan" job to dodge the guard.
READ_ONLY_SELF_HOSTED_PLAN_JOBS = frozenset(
    {
        ("_core.yml", "plan"),
        ("_range.yml", "plan"),
        ("_shifter-platform.yml", "plan"),
    }
)

# Mutation signals scanned in a self-hosted job's `run` steps. Precise verbs
# only - the bare word "deploy" appears in plan-job step names and is not a
# mutation by itself.
_MUTATION_RE = re.compile(
    r"terraform\s+apply"
    r"|docker\s+push"
    r"|ecs\s+update-service"
    r"|register-task-definition"
    r"|kubectl\s+apply"
    r"|helm\s+(?:upgrade|install)"
    r"|start-instance-refresh"
    r"|aws\s+ecs\s+(?:update|register)",
    re.IGNORECASE,
)

_RESULT_REF = re.compile(r"needs\.([A-Za-z0-9_-]+)\.result")


class WorkflowShapeError(AssertionError):
    """A workflow is missing a structurally-required key.

    Raised instead of returning a default so the suite fails closed: an absent
    job, filter, ``needs``, or ``if`` block is an error, never a silent
    "not applicable".
    """


# --------------------------------------------------------------------------- #
# Loading / accessors
# --------------------------------------------------------------------------- #
def load_workflow(name):
    """Load a workflow by file name (e.g. ``"deploy.yml"``) as a dict.

    Normalizes the YAML 1.1 ``on:`` key, which PyYAML resolves to the Python
    boolean ``True``, back to the string ``"on"``.
    """
    path = WORKFLOWS_DIR / name
    if not path.is_file():
        raise WorkflowShapeError(f"workflow not found: {path}")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise WorkflowShapeError(f"{name}: top-level YAML is not a mapping")
    if True in data:  # bare `on:` parsed as boolean True under YAML 1.1
        data["on"] = data.pop(True)
    return data


def jobs(wf, name="<workflow>"):
    """Return the ``jobs`` mapping or raise if it is missing/empty."""
    js = wf.get("jobs")
    if not isinstance(js, dict) or not js:
        raise WorkflowShapeError(f"{name}: missing or empty 'jobs' mapping")
    return js


def get_job(wf, job_id, name="<workflow>"):
    js = jobs(wf, name)
    if job_id not in js:
        raise WorkflowShapeError(f"{name}: job '{job_id}' not found")
    return js[job_id]


def normalize_expr(expr):
    """Collapse every whitespace run (including block-scalar newlines) to one
    space so substring matching against ``if:`` expressions is robust."""
    return " ".join(str(expr or "").split())


def job_if(job):
    return normalize_expr(job.get("if", ""))


def runs_on(job):
    return job.get("runs-on")


def is_self_hosted(job):
    ro = runs_on(job)
    if isinstance(ro, str):
        return ro == "self-hosted"
    if isinstance(ro, (list, tuple)):
        return "self-hosted" in ro
    return False


def job_has_mutation_step(job):
    for step in job.get("steps", []) or []:
        if _MUTATION_RE.search(str(step.get("run", ""))):
            return True
    return False


# --------------------------------------------------------------------------- #
# #781: upstream deploy gating
# --------------------------------------------------------------------------- #
def result_guarded_upstreams(if_expr):
    """Upstream job ids referenced as ``needs.<job>.result`` in an ``if:``."""
    return set(_RESULT_REF.findall(normalize_expr(if_expr)))


def upstream_gating_violations(wf, deploy_job_ids):
    """Return ``[(job_id, upstream, result), ...]`` for deploy jobs that still
    RUN when a result-gated upstream is ``failure`` or ``cancelled`` (fail-open,
    the #781 class). Empty list means every deploy job fails closed."""
    violations = []
    for jid in deploy_job_ids:
        expr = job_if(get_job(wf, jid, "deploy.yml"))
        for upstream in sorted(result_guarded_upstreams(expr)):
            for bad in ("failure", "cancelled"):
                if not job_denied_when_upstream(expr, upstream, bad):
                    violations.append((jid, upstream, bad))
    return violations


# --------------------------------------------------------------------------- #
# Constrained GitHub Actions `if:` expression evaluator
#
# A substring check cannot PROVE fail-closed gating: an expression that also
# ORs in `failure` or `cancelled` still contains the `success || skipped` text,
# and a correct gate written a different way would be rejected. So the suite
# parses the `if:` and evaluates the denied scenarios (`failure`, `cancelled`,
# `pull_request`) over the finite result/event vocabulary, then asserts the job
# does not run. Supports only the operators these workflows use - `==`, `!=`,
# `&&`, `||`, `!`, parentheses, string literals, and the `always()` status
# function; operands are `needs.<job>.result`, `needs.<job>.outputs.<key>`,
# `inputs.<key>`, and `github.<field>`. Anything else fails closed.
# --------------------------------------------------------------------------- #
_EXPR_TOKEN = re.compile(
    r"""\s+
        |(?P<str>'[^']*')
        |(?P<op>==|!=|&&|\|\||!|\(|\))
        |(?P<ident>[A-Za-z0-9_.\-]+)""",
    re.VERBOSE,
)


class ExpressionError(WorkflowShapeError):
    """An ``if:`` expression used a construct the constrained evaluator rejects."""


def _truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value != ""
    return bool(value)


def _loose_eq(left, right):
    # GitHub Actions `==` compares strings case-insensitively.
    if isinstance(left, str) and isinstance(right, str):
        return left.lower() == right.lower()
    return left == right


def _call_function(name):
    if name == "always":
        return True
    raise ExpressionError(f"unsupported function in if-expression: {name}()")


def _tokenize_expr(expr):
    tokens, pos, end = [], 0, len(expr)
    while pos < end:
        match = _EXPR_TOKEN.match(expr, pos)
        if not match or match.end() == pos:
            raise ExpressionError(f"cannot tokenize: {expr[pos : pos + 20]!r}")
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


class _ExprParser:
    """Recursive-descent evaluator: `!` > comparison > `&&` > `||`."""

    def __init__(self, tokens, resolve):
        self._toks = tokens
        self._i = 0
        self._resolve = resolve

    def _peek(self):
        return self._toks[self._i]

    def _advance(self):
        tok = self._toks[self._i]
        self._i += 1
        return tok

    def _expect(self, op):
        if self._advance() != ("op", op):
            raise ExpressionError(f"expected {op!r}")

    def evaluate(self):
        value = self._parse_or()
        if self._peek()[0] != "end":
            raise ExpressionError(f"trailing tokens: {self._toks[self._i :]!r}")
        return value

    def _parse_or(self):
        value = self._parse_and()
        while self._peek() == ("op", "||"):
            self._advance()
            value = _truthy(value) | _truthy(self._parse_and())
        return value

    def _parse_and(self):
        value = self._parse_not()
        while self._peek() == ("op", "&&"):
            self._advance()
            value = _truthy(value) & _truthy(self._parse_not())
        return value

    def _parse_not(self):
        if self._peek() == ("op", "!"):
            self._advance()
            return not _truthy(self._parse_not())
        return self._parse_cmp()

    def _parse_cmp(self):
        left = self._parse_primary()
        token = self._peek()
        if token in (("op", "=="), ("op", "!=")):
            self._advance()
            equal = _loose_eq(left, self._parse_primary())
            return equal if token == ("op", "==") else not equal
        return left

    def _parse_primary(self):
        token = self._advance()
        if token == ("op", "("):
            value = self._parse_or()
            self._expect(")")
            return value
        if token[0] == "str":
            return token[1]
        if token[0] == "ident":
            if self._peek() == ("op", "("):
                self._advance()
                self._expect(")")
                return _call_function(token[1])
            return self._resolve(token[1])
        raise ExpressionError(f"unexpected token {token!r}")


def evaluate_if(
    if_expr,
    *,
    results=None,
    event_name="workflow_dispatch",
    ref="refs/heads/aws-dev",
    base_ref="",
    inputs_true=True,
):
    """Evaluate a job ``if:`` against a permissive context and return whether
    the job would run.

    Unspecified upstream results default to ``success``, every
    ``needs.*.outputs.*`` to ``true``, and every ``inputs.*`` to
    ``inputs_true`` - so the only thing that flips the outcome is the scenario
    under test (a failed upstream, a pull_request event)."""
    expr = normalize_expr(if_expr)
    if not expr:
        return True  # a job with no `if:` is always eligible
    results = results or {}

    def resolve(path):
        parts = path.split(".")
        head = parts[0]
        if head == "needs" and len(parts) >= 3:
            job, field = parts[1], parts[2]
            if field == "result":
                return results.get(job, "success")
            if field == "outputs":
                return "true"
            return "success"
        if head == "inputs":
            return inputs_true
        if head == "github":
            field = parts[1] if len(parts) > 1 else ""
            return {
                "event_name": event_name,
                "ref": ref,
                "base_ref": base_ref,
            }.get(field, "")
        raise ExpressionError(f"unresolvable operand: {path}")

    return _truthy(_ExprParser(_tokenize_expr(expr), resolve).evaluate())


def job_denied_when_upstream(if_expr, upstream, result):
    """True iff the job does NOT run when ``upstream`` has ``result`` (every
    other condition permissive). Proves a failed/cancelled upstream blocks the
    deploy job (#781)."""
    return not evaluate_if(if_expr, results={upstream: result})


def job_denied_on_pull_request(if_expr):
    """True iff the job does NOT run on a ``pull_request`` event (every other
    condition permissive). Proves PR events cannot reach the job
    (runner-exposure fix)."""
    return not evaluate_if(if_expr, event_name="pull_request")


def job_runs_when_eligible(if_expr):
    """Sanity check: the permissive context actually runs the job, so a
    denied-case assertion is meaningful and not vacuously satisfied."""
    return evaluate_if(if_expr)


# --------------------------------------------------------------------------- #
# #913 / R-A2: dorny/paths-filter change-filter coverage
# --------------------------------------------------------------------------- #
def parse_paths_filter(wf, job_id, step_id, name="deploy.yml"):
    """Return ``{filter_name: [patterns]}`` from a dorny/paths-filter step.

    The action's ``filters`` input is itself a YAML document (a block scalar in
    the workflow), so it is parsed a second time here.
    """
    job = get_job(wf, job_id, name)
    for step in job.get("steps", []) or []:
        if step.get("id") == step_id:
            raw = (step.get("with") or {}).get("filters")
            if not isinstance(raw, str):
                raise WorkflowShapeError(
                    f"{name}:{step_id} has no string 'filters' input"
                )
            parsed = yaml.safe_load(raw)
            if not isinstance(parsed, dict) or not parsed:
                raise WorkflowShapeError(f"{name}:{step_id} filters not a mapping")
            return {key: list(val) for key, val in parsed.items()}
    raise WorkflowShapeError(f"{name}:{job_id} has no step with id '{step_id}'")


def _glob_to_regex(pattern):
    """Translate a micromatch-style glob to an anchored regex.

    Supports the features the deploy filters use: ``**`` (any depth, including
    a trailing ``/`` that matches zero or more directories), ``*`` (one path
    segment), and literal text. Mirrors ``dorny/paths-filter`` (micromatch)
    for ``prefix/**``, ``*/*.tf``, ``**/*.md``, and exact paths.
    """
    i, n = 0, len(pattern)
    out = ["^"]
    while i < n:
        char = pattern[i]
        if char == "*":
            if pattern[i : i + 2] == "**":
                j = i + 2
                if pattern[j : j + 1] == "/":
                    out.append("(?:.*/)?")  # `**/` => zero or more directories
                    i = j + 1
                else:
                    out.append(".*")
                    i = j
            else:
                out.append("[^/]*")
                i += 1
        else:
            out.append(re.escape(char))
            i += 1
    out.append("$")
    return "".join(out)


def path_matches_any(path, patterns):
    """True iff ``path`` matches any positive pattern in ``patterns``.

    The deploy filters use no ``!`` negation and the default ``some``
    quantifier, so positive-pattern membership is the full contract for them.
    """
    for pattern in patterns:
        if pattern.startswith("!"):
            continue
        if re.match(_glob_to_regex(pattern), path):
            return True
    return False


# --------------------------------------------------------------------------- #
# #892: branch/event routing
# --------------------------------------------------------------------------- #
def extract_set_environment_script(wf, name="deploy.yml"):
    """Return the ``run`` body of the ``changes`` job's ``Set environment`` step."""
    job = get_job(wf, "changes", name)
    for step in job.get("steps", []) or []:
        if step.get("id") == "env" or step.get("name") == "Set environment":
            run = step.get("run")
            if not isinstance(run, str):
                raise WorkflowShapeError(
                    f"{name}: 'Set environment' step has no run script"
                )
            return run
    raise WorkflowShapeError(f"{name}: no 'Set environment' step in 'changes' job")


def evaluate_env(script, event_name, ref="", base_ref=""):
    """Execute the workflow's own ``Set environment`` bash and return its
    ``GITHUB_OUTPUT`` key/value pairs.

    The GitHub context expressions the script references are substituted with
    the literal scenario values; ``GITHUB_REF`` is provided via the
    environment. Only literal event/branch strings reach bash - no secrets, no
    shell trace - matching GitHub's default ``bash -e -o pipefail`` shell.
    """
    rendered = script.replace("${{ github.event_name }}", event_name).replace(
        "${{ github.base_ref }}", base_ref
    )
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "github_output")
        Path(out_path).touch()
        env = {
            "PATH": os.environ.get("PATH", ""),
            "GITHUB_REF": ref,
            "GITHUB_OUTPUT": out_path,
        }
        proc = subprocess.run(
            ["bash", "-eo", "pipefail", "-c", rendered],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"Set environment script exited {proc.returncode}: {proc.stderr.strip()}"
            )
        outputs = {}
        for line in Path(out_path).read_text().splitlines():
            line = line.strip()
            if "=" in line:
                key, val = line.split("=", 1)
                outputs[key] = val
    return outputs
