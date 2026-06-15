"""CI-time lint: provisioner plan scripts must not contain unrendered template tokens.

`SetupOrchestrator._render_script` raises `SetupError` at live provisioning time
for any ``{{word}}`` placeholder that is not a key in the plan's render context.
This module statically scans every provisioner plan for the same collision so it
is caught in CI instead of on a live range.

Dot-prefixed Go/Docker template fields (``{{.Names}}``,
``{{json .NetworkSettings.Networks}}``) do not match the runtime matcher and are
safe by construction. Bare word-only tokens (``{{end}}``, ``{{range}}``) do match
and must correspond to a render-context key the plan's ``get_context()`` declares.

The scan is purely static (AST only): no plan is instantiated and no script is
executed. The placeholder matcher is not hard-coded here — it is extracted
straight out of ``SetupOrchestrator._render_script``'s source so the lint always
uses the exact runtime regex and can never drift from it.
"""

import ast
import re
from pathlib import Path

import pytest

PLANS_DIR = Path(__file__).resolve().parent.parent / "plans"
# `_render_script` was split out of `setup_orchestrator.py` into the
# `_setup_logging` mixin module (see SetupOrchestrator's docstring); the
# AST scan must follow it to keep the runtime regex as its source of truth.
_ORCHESTRATOR = PLANS_DIR.parent / "orchestrators" / "_setup_logging.py"

# Modules under plans/ that define no SetupOrchestrator-rendered plan.
_NON_PLAN_MODULES = {"base.py", "__init__.py"}

# SetupStep dataclass fields that SetupOrchestrator renders through
# _render_script, mapped to their positional index in the SetupStep signature
# (name, script, timeout_seconds, requires_reboot, is_verification,
#  stdin_input, poll_for_job).
RENDERED_STEP_FIELDS = {"script": 1, "stdin_input": 5}


def _orchestrator_placeholder_pattern():
    """Extract the ``{{ variable }}`` matcher regex from SetupOrchestrator.

    `_render_script` assigns the matcher to a local named ``pattern``. Reading
    that literal out of the source — rather than copying the regex here —
    guarantees the lint matches the runtime renderer exactly. A rename or regex
    change in the orchestrator surfaces as a loud test error, not silent drift.
    """
    tree = ast.parse(_ORCHESTRATOR.read_text(encoding="utf-8"), filename=str(_ORCHESTRATOR))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "_render_script"):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Assign)
                and len(sub.targets) == 1
                and isinstance(sub.targets[0], ast.Name)
                and sub.targets[0].id == "pattern"
                and isinstance(sub.value, ast.Constant)
                and isinstance(sub.value.value, str)
            ):
                return re.compile(sub.value.value)
    raise AssertionError(
        "could not locate the `pattern` placeholder regex in "
        "SetupOrchestrator._render_script — the lint cannot verify plan scripts "
        "without the runtime matcher; update _orchestrator_placeholder_pattern()."
    )


# The exact matcher SetupOrchestrator._render_script uses at provisioning time.
TEMPLATE_PLACEHOLDER_PATTERN = _orchestrator_placeholder_pattern()


def _static_text(node):
    """Best-effort static string value of an AST node.

    Returns a plain string literal verbatim, or the literal segments of an
    f-string concatenated. Returns None for anything else. f-string
    interpolations are Python-evaluated, not template tokens, so dropping them
    is correct for token scanning.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return None


def _module_string_constants(tree):
    """Map module-level NAME -> string value for plain and f-string assignments."""
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        text = _static_text(value)
        if text is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                consts[target.id] = text
    return consts


def _resolve_str(node, consts):
    """Resolve an AST node to a string: a literal, or a module-constant reference."""
    text = _static_text(node)
    if text is not None:
        return text
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    return None


def _call_arg(call, name, pos):
    """Return the keyword (or positional) argument node for a call, or None."""
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    if pos < len(call.args):
        return call.args[pos]
    return None


def _collect_tokens(tree, consts):
    """Collect (field, step_name, token) for every {{word}} in a SetupStep field."""
    tokens = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "SetupStep":
            continue
        step_name = _resolve_str(_call_arg(node, "name", 0), consts) or "<unnamed step>"
        for field_name, pos in RENDERED_STEP_FIELDS.items():
            value_node = _call_arg(node, field_name, pos)
            if value_node is None:
                continue
            text = _resolve_str(value_node, consts)
            if text is None:
                # Dynamically-built string (e.g. assembled by a builder
                # function); there is no static value to scan.
                continue
            for token in TEMPLATE_PLACEHOLDER_PATTERN.findall(text):
                tokens.append((field_name, step_name, token))
    return tokens


def _plan_classes(tree):
    """Module-level classes that implement the SetupPlan protocol (have get_context)."""
    return [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(isinstance(b, ast.FunctionDef) and b.name == "get_context" for b in node.body)
    ]


def _subscript_or_get_key(node):
    """The string index of ``ctx["k"]`` or the first arg of ``ctx.get("k")``, else None."""
    if isinstance(node, ast.Subscript):
        index = node.slice
        if isinstance(index, ast.Constant) and isinstance(index.value, str):
            return index.value
        return None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    return None


def _key_strings(node):
    """String literals used in a context-key position within one AST node."""
    if isinstance(node, ast.Dict):
        return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    if isinstance(node, ast.Set | ast.List | ast.Tuple):
        return {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    literal = _subscript_or_get_key(node)
    return {literal} if literal is not None else set()


def _declared_context_keys(classdef):
    """Collect the render-context keys a plan's get_context() declares.

    A context key always appears as a string literal in get_context() in a key
    position: a dict-literal key, a subscript index (``ctx["k"]``), a
    ``.get("k")`` argument, or an element of a literal list/set/tuple the method
    iterates. Collecting those positions covers every plan style — literal
    return, loop-built dict, and input pass-through — directly from the existing
    get_context() contract, with no parallel per-plan schema.
    """
    get_ctx = next(
        (b for b in classdef.body if isinstance(b, ast.FunctionDef) and b.name == "get_context"),
        None,
    )
    if get_ctx is None:
        return set()
    keys = set()
    for node in ast.walk(get_ctx):
        keys |= _key_strings(node)
    return keys


def _plan_context_keys(classes):
    """Union of declared context keys across a module's plan classes.

    resolvable is False only when the module declares no plan class at all, so a
    module with rendered tokens but no get_context() cannot pass silently.
    """
    if not classes:
        return set(), False
    keys = set()
    for classdef in classes:
        keys |= _declared_context_keys(classdef)
    return keys, True


def _lint_tree(tree, label):
    """Return a list of human-readable violation strings for one parsed module."""
    consts = _module_string_constants(tree)
    tokens = _collect_tokens(tree, consts)
    if not tokens:
        return []
    keys, resolvable = _plan_context_keys(_plan_classes(tree))
    if not resolvable:
        return [
            f"{label}: contains {{{{word}}}} template tokens but declares no plan "
            f"class with a get_context() method, so the lint cannot determine the "
            f"render-context keys."
        ]
    violations = []
    for field_name, step_name, token in tokens:
        if token not in keys:
            violations.append(
                f"{label}: step '{step_name}' field '{field_name}' references "
                f"unrendered template token '{{{{{token}}}}}', which is not a "
                f"render-context key declared by get_context(). Declared keys: "
                f"{sorted(keys)}. Either add the key to get_context() or, if it is "
                f"not a provisioner placeholder, use a dot-prefixed Go/Docker token "
                f"(e.g. '{{{{.{token}}}}}')."
            )
    return violations


def _lint_module(path):
    """Return violation strings for a plan module on disk."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _lint_tree(tree, path.name)


def _plan_modules():
    return sorted(p for p in PLANS_DIR.glob("*.py") if p.name not in _NON_PLAN_MODULES)


# --- the lint -------------------------------------------------------------


def test_plans_directory_is_discovered():
    assert _plan_modules(), f"no provisioner plan modules found under {PLANS_DIR}"


@pytest.mark.parametrize("plan_path", _plan_modules(), ids=lambda p: p.name)
def test_plan_scripts_have_no_unrendered_tokens(plan_path):
    violations = _lint_module(plan_path)
    assert not violations, "\n".join(violations)


# --- helper coverage (the scanner itself) ---------------------------------

_SYNTHETIC_OK = """
from typing import Any, ClassVar
SCRIPT_A = "echo {{hostname}}"
class GoodPlan:
    steps: ClassVar[list] = [SetupStep(name="a", script=SCRIPT_A)]
    def get_context(self, instance: Any) -> dict:
        return {"hostname": instance.hostname}
"""

_SYNTHETIC_BAD = """
from typing import Any, ClassVar
class BadPlan:
    steps: ClassVar[list] = [
        SetupStep(name="bad", script="docker network inspect --format '{{range}}{{end}}'"),
    ]
    def get_context(self, instance: Any) -> dict:
        return {"hostname": instance.hostname}
"""

_SYNTHETIC_PASSTHROUGH = """
class PassthroughPlan:
    steps = [SetupStep(name="p", script="echo {{rdp_user}}")]
    def get_context(self, context):
        username = context.get("rdp_user")
        if not username:
            raise ValueError("missing rdp_user")
        return context
"""

_SYNTHETIC_LOOP_BUILT = """
class LoopPlan:
    steps = [SetupStep(name="l", script="echo {{alpha}} {{beta}}")]
    def get_context(self, instance):
        required = ["alpha", "beta"]
        ctx = {}
        for attr in required:
            ctx[attr] = getattr(instance, attr)
        return ctx
"""

_SYNTHETIC_DOT_TOKENS = """
class DotPlan:
    steps = [SetupStep(name="s", script="docker ps --format '{{.Names}} {{.Status}}'")]
    def get_context(self, instance):
        return {}
"""

_SYNTHETIC_STDIN = """
class StdinPlan:
    steps = [SetupStep(name="s", script="", stdin_input="set region {{missing}}")]
    def get_context(self, instance):
        return {"present": 1}
"""

_SYNTHETIC_NO_GET_CONTEXT = """
class NoContextPlan:
    steps = [SetupStep(name="s", script="echo {{stray}}")]
"""


def test_template_pattern_matches_bare_tokens_only():
    assert TEMPLATE_PLACEHOLDER_PATTERN.findall("{{end}} {{ word }}") == ["end", "word"]
    assert TEMPLATE_PLACEHOLDER_PATTERN.findall("{{.Names}} {{json .X}}") == []


def test_clean_synthetic_plan_passes():
    assert _lint_tree(ast.parse(_SYNTHETIC_OK), "ok.py") == []


def test_bad_token_is_flagged():
    violations = _lint_tree(ast.parse(_SYNTHETIC_BAD), "bad.py")
    assert violations
    joined = " ".join(violations)
    assert "range" in joined
    assert "end" in joined


def test_passthrough_get_context_keys_from_get_calls():
    assert _lint_tree(ast.parse(_SYNTHETIC_PASSTHROUGH), "passthrough.py") == []


def test_loop_built_get_context_keys_from_list_literal():
    assert _lint_tree(ast.parse(_SYNTHETIC_LOOP_BUILT), "loop.py") == []


def test_dot_prefixed_tokens_are_ignored():
    assert _lint_tree(ast.parse(_SYNTHETIC_DOT_TOKENS), "dot.py") == []


def test_stdin_input_field_is_scanned():
    violations = _lint_tree(ast.parse(_SYNTHETIC_STDIN), "stdin.py")
    assert violations
    assert "stdin_input" in violations[0]
    assert "missing" in violations[0]


def test_module_with_tokens_but_no_get_context_is_flagged():
    violations = _lint_tree(ast.parse(_SYNTHETIC_NO_GET_CONTEXT), "nocontext.py")
    assert violations
    assert "get_context" in violations[0]
