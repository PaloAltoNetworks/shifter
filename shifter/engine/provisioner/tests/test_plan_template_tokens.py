"""CI-time lint: provisioner plan scripts must not contain unrendered template tokens.

`SetupOrchestrator._render_script` raises `SetupError` at live provisioning time
for any ``{{word}}`` placeholder that is not a key in the plan's render context.
This module statically scans every provisioner plan for the same collision so it
is caught in CI instead of on a live range.

Dot-prefixed Go/Docker template fields (``{{.Names}}``,
``{{json .NetworkSettings.Networks}}``) do not match the runtime matcher and are
safe by construction. Bare word-only tokens (``{{end}}``, ``{{range}}``) do match
and must correspond to a declared plan context key.

The scan is purely static (AST only): no plan is instantiated and no script is
executed. The placeholder matcher is not hard-coded here — it is extracted
straight out of ``SetupOrchestrator._render_script``'s source so the lint
always uses the exact runtime regex and can never drift from it.
"""

import ast
import re
from pathlib import Path

import pytest

PLANS_DIR = Path(__file__).resolve().parent.parent / "plans"
_ORCHESTRATOR = PLANS_DIR.parent / "orchestrators" / "setup_orchestrator.py"


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

# Modules under plans/ that define no SetupOrchestrator-rendered plan.
_NON_PLAN_MODULES = {"base.py", "__init__.py"}

# SetupStep dataclass fields that SetupOrchestrator renders through
# _render_script, mapped to their positional index in the SetupStep signature
# (name, script, timeout_seconds, requires_reboot, is_verification,
#  stdin_input, poll_for_job).
RENDERED_STEP_FIELDS = {"script": 1, "stdin_input": 5}

# Optional class attribute: an explicit frozenset of render-context keys for
# plans whose get_context() builds its dict dynamically and so cannot be
# inferred from a literal return.
CONTEXT_KEYS_ATTR = "TEMPLATE_CONTEXT_KEYS"


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


def _literal_str_collection(node):
    """Extract a set of string literals from a set/list/tuple literal, optionally
    wrapped in frozenset()/set()/tuple()/list(). Returns None if the node is not
    a pure literal collection of strings.
    """
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"frozenset", "set", "tuple", "list"}
    ):
        if len(node.args) != 1:
            return None
        node = node.args[0]
    if not isinstance(node, ast.Set | ast.List | ast.Tuple):
        return None
    out = set()
    for elt in node.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            out.add(elt.value)
        else:
            return None
    return out


def _explicit_context_keys(classdef):
    """Return the declared TEMPLATE_CONTEXT_KEYS set for a plan class, or None."""
    for node in classdef.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == CONTEXT_KEYS_ATTR:
                return _literal_str_collection(value)
    return None


def _inferred_context_keys(classdef):
    """Infer context keys from a get_context() literal-dict return.

    Returns (keys, reliable). Inference is reliable only when get_context()
    returns one or more literal dicts whose keys are all string literals.
    """
    get_ctx = next(
        (b for b in classdef.body if isinstance(b, ast.FunctionDef) and b.name == "get_context"),
        None,
    )
    if get_ctx is None:
        return set(), False
    returns = [n for n in ast.walk(get_ctx) if isinstance(n, ast.Return)]
    if not returns:
        return set(), False
    keys = set()
    for ret in returns:
        if not isinstance(ret.value, ast.Dict):
            return set(), False
        for key in ret.value.keys:
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                # A None key means dict-unpacking (**other); a non-literal key
                # means the key set cannot be determined statically.
                return set(), False
            keys.add(key.value)
    return keys, True


def _plan_context_keys(classes):
    """Resolve the union of declared context keys across a module's plan classes.

    Returns (keys, resolvable). resolvable is False when the module has no plan
    class, or when a plan class neither declares TEMPLATE_CONTEXT_KEYS nor has a
    statically inferable get_context().
    """
    if not classes:
        return set(), False
    keys = set()
    resolvable = True
    for classdef in classes:
        explicit = _explicit_context_keys(classdef)
        if explicit is not None:
            keys |= explicit
            continue
        inferred, reliable = _inferred_context_keys(classdef)
        if reliable:
            keys |= inferred
        else:
            resolvable = False
    return keys, resolvable


def _lint_tree(tree, label):
    """Return a list of human-readable violation strings for one parsed module."""
    consts = _module_string_constants(tree)
    tokens = _collect_tokens(tree, consts)
    if not tokens:
        return []
    keys, resolvable = _plan_context_keys(_plan_classes(tree))
    if not resolvable:
        return [
            f"{label}: contains {{{{word}}}} template tokens but its plan context "
            f"keys cannot be determined statically. Declare a `{CONTEXT_KEYS_ATTR}` "
            f"frozenset of context keys on the plan class."
        ]
    violations = []
    for field_name, step_name, token in tokens:
        if token not in keys:
            violations.append(
                f"{label}: step '{step_name}' field '{field_name}' references "
                f"unrendered template token '{{{{{token}}}}}', which is not a "
                f"declared plan context key. Declared keys: {sorted(keys)}. "
                f"Either declare the key in get_context() or use a dot-prefixed "
                f"Go/Docker token (e.g. '{{{{.{token}}}}}') if it is not a "
                f"provisioner placeholder."
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

_SYNTHETIC_DYNAMIC = """
from typing import Any
class DynamicPlan:
    steps = [SetupStep(name="d", script="echo {{rdp_user}}")]
    def get_context(self, ctx: Any) -> dict:
        return ctx
"""

_SYNTHETIC_DYNAMIC_DECLARED = """
from typing import Any, ClassVar
class DynamicPlan:
    TEMPLATE_CONTEXT_KEYS: ClassVar[frozenset] = frozenset({"rdp_user"})
    steps = [SetupStep(name="d", script="echo {{rdp_user}}")]
    def get_context(self, ctx: Any) -> dict:
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


def test_dynamic_context_without_declaration_is_flagged():
    violations = _lint_tree(ast.parse(_SYNTHETIC_DYNAMIC), "dyn.py")
    assert violations
    assert CONTEXT_KEYS_ATTR in violations[0]


def test_dynamic_context_with_declaration_passes():
    assert _lint_tree(ast.parse(_SYNTHETIC_DYNAMIC_DECLARED), "dyn.py") == []


def test_dot_prefixed_tokens_are_ignored():
    assert _lint_tree(ast.parse(_SYNTHETIC_DOT_TOKENS), "dot.py") == []


def test_stdin_input_field_is_scanned():
    violations = _lint_tree(ast.parse(_SYNTHETIC_STDIN), "stdin.py")
    assert violations
    assert "stdin_input" in violations[0]
    assert "missing" in violations[0]
