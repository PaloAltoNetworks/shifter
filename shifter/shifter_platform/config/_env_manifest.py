"""Static extraction of settings environment-variable bindings (#948).

Scans ``config/settings.py`` and ``config/_*.py`` for ``os.environ.get`` calls
so the generated manifest stays single-sourced with the code that reads each var.
Bindings resolved outside ``os.environ.get`` (e.g. ``require_environment()``)
are listed in ``_EXPLICIT_BINDINGS``.
"""

from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = CONFIG_DIR / "env-manifest.json"


@dataclass(frozen=True, slots=True)
class EnvBinding:
    """One settings env var, its default expression, and the module that reads it."""

    name: str
    default: str | None
    source_file: str


_API_POLICY_FILE = "config/_api_token_settings.py"
_DATABASE_SETTINGS_FILE = "config/_database_settings.py"
_OIDC_SETTINGS_FILE = "config/_oidc_settings.py"
_SETTINGS_FILE = "config/settings.py"

# Vars read through the `_env_int` / `_env_bool` / `require_environment` helpers
# rather than a literal `os.environ.get(...)` call are invisible to the AST
# walker below, so they are declared explicitly here to stay in the manifest
# (PLAT-102 token policy knobs, per the preflight config-binding guardrail).
_EXPLICIT_BINDINGS = (
    EnvBinding(name="DB_HOST", default=None, source_file=_DATABASE_SETTINGS_FILE),
    EnvBinding(name="DB_NAME", default=None, source_file=_DATABASE_SETTINGS_FILE),
    EnvBinding(name="DB_PASSWORD", default=None, source_file=_DATABASE_SETTINGS_FILE),
    EnvBinding(name="DB_PORT", default=None, source_file=_DATABASE_SETTINGS_FILE),
    EnvBinding(name="DB_USER", default=None, source_file=_DATABASE_SETTINGS_FILE),
    EnvBinding(name="DJANGO_ALLOWED_HOSTS", default=None, source_file=_SETTINGS_FILE),
    EnvBinding(name="EMAIL_BACKEND", default=None, source_file="config/_email.py"),
    EnvBinding(name="ENVIRONMENT", default=None, source_file=_SETTINGS_FILE),
    EnvBinding(name="FIELD_ENCRYPTION_KEY", default=None, source_file=_SETTINGS_FILE),
    EnvBinding(name="OIDC_AUTH_DOMAIN", default=None, source_file=_OIDC_SETTINGS_FILE),
    EnvBinding(name="OIDC_ISSUER_URL", default=None, source_file=_OIDC_SETTINGS_FILE),
    EnvBinding(name="OIDC_RP_CLIENT_ID", default=None, source_file=_OIDC_SETTINGS_FILE),
    EnvBinding(name="OIDC_RP_CLIENT_SECRET", default=None, source_file=_OIDC_SETTINGS_FILE),
    EnvBinding(name="API_TOKEN_LAST_USED_COALESCE_SECONDS", default="300", source_file=_API_POLICY_FILE),
    EnvBinding(name="API_TOKEN_MAX_TTL_DAYS", default="365", source_file=_API_POLICY_FILE),
)


def _default_repr(node: ast.expr | None) -> str | None:
    """Render an AST default expression as a stable manifest string."""
    result: str | None
    match node:
        case None:
            result = None
        case ast.Constant(value=None):
            result = None
        case ast.Constant(value=value):
            result = repr(value)
        case ast.Name(id=name):
            result = name
        case ast.IfExp(body=body, orelse=orelse):
            result = f"{_default_repr(body)} if ... else {_default_repr(orelse)}"
        case _:
            try:
                result = ast.unparse(node)
            except Exception:
                result = "<dynamic>"
    return result


def _is_os_environ_get(node: ast.Call) -> bool:
    """Return True when ``node`` is an ``os.environ.get(...)`` call."""
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "get"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "environ"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "os"
    )


def _env_name_from_get(node: ast.Call) -> str | None:
    """Extract the env var name from an ``os.environ.get`` call, or None."""
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return None
    if not isinstance(node.args[0].value, str):
        return None
    return node.args[0].value


def _binding_from_get_call(node: ast.Call, rel: str) -> EnvBinding | None:
    """Build an ``EnvBinding`` from a validated ``os.environ.get`` call."""
    name = _env_name_from_get(node)
    if name is None:
        return None
    default = _default_repr(node.args[1]) if len(node.args) > 1 else None
    return EnvBinding(name=name, default=default, source_file=rel)


def _extract_from_file(path: Path) -> list[EnvBinding]:
    """Collect ``os.environ.get`` bindings from one config module."""
    tree = ast.parse(path.read_text(), filename=str(path))
    rel = path.relative_to(CONFIG_DIR.parent).as_posix()
    bindings: list[EnvBinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_os_environ_get(node):
            continue
        binding = _binding_from_get_call(node, rel)
        if binding is not None:
            bindings.append(binding)
    return bindings


def collect_env_bindings(config_dir: Path | None = None) -> list[EnvBinding]:
    """Merge explicit and extracted env bindings from all config modules."""
    root = config_dir or CONFIG_DIR
    files = sorted(root.glob("settings.py")) + sorted(root.glob("_*.py"))
    merged: dict[str, EnvBinding] = {binding.name: binding for binding in _EXPLICIT_BINDINGS}
    for path in files:
        if path.name == "_env_manifest.py":
            continue
        for binding in _extract_from_file(path):
            merged.setdefault(binding.name, binding)
    return sorted(merged.values(), key=lambda item: item.name)


def render_manifest_json(bindings: list[EnvBinding]) -> str:
    """Serialize bindings to the committed manifest JSON shape."""
    payload = {
        "schema_version": 1,
        "generated_from": "config/_env_manifest.py",
        "variables": [asdict(binding) for binding in bindings],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_manifest(path: Path | None = None) -> Path:
    """Regenerate and write ``env-manifest.json``; return the target path."""
    target = path or MANIFEST_PATH
    bindings = collect_env_bindings()
    target.write_text(render_manifest_json(bindings))
    return target


def manifest_is_current(path: Path | None = None) -> bool:
    """Return True when the committed manifest matches the current extractor output."""
    target = path or MANIFEST_PATH
    if not target.exists():
        return False
    expected = render_manifest_json(collect_env_bindings())
    return target.read_text() == expected
