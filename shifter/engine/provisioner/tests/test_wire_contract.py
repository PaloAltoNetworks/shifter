"""Cross-package wire-contract drift guard for the provisioner publisher."""

from __future__ import annotations

import ast
from pathlib import Path

from cyberscript import wire_constants as event_types
from cyberscript import wire_spec_keys as spec_keys
from cyberscript.enums import ResourceStatus

_TERRAFORM_VARS = Path(__file__).resolve().parents[1] / "terraform_vars.py"
_SPEC_KEY_WALK_FUNCTIONS = frozenset(
    {
        "_build_tf_instance",
        "_build_tf_subnets",
        "_build_range_terraform_variables",
        "_resolve_agent_presigned_url",
    }
)


_SPEC_DICT_RECEIVERS = frozenset({"agent_data", "inst", "range_spec", "subnet"})


def _dict_get_literal_keys_in_functions(module_path: Path, function_names: frozenset[str]) -> set[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in function_names:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            if not isinstance(func, ast.Attribute) or func.attr != "get" or not sub.args:
                continue
            receiver = func.value
            if not isinstance(receiver, ast.Name) or receiver.id not in _SPEC_DICT_RECEIVERS:
                continue
            key_arg = sub.args[0]
            if isinstance(key_arg, ast.Constant) and isinstance(key_arg.value, str):
                keys.add(key_arg.value)
    return keys


class TestProvisionerEventsMatchesCyberscript:
    def test_provisioner_reexports_event_types(self) -> None:
        import events as provisioner_events

        for name in event_types.__all__:
            assert getattr(provisioner_events, name) == getattr(event_types, name)

    def test_provisioner_status_aliases_match_resource_status(self) -> None:
        import events as provisioner_events

        for status in ResourceStatus:
            alias = f"STATUS_{status.name}"
            assert getattr(provisioner_events, alias) == status.value


class TestTerraformVarsRangeSpecKeyWalk:
    def test_dict_get_keys_are_registered_in_wire_spec_keys(self) -> None:
        allowed = (
            spec_keys.RANGE_SPEC_TOP_LEVEL_SCHEMA_KEYS
            | spec_keys.SUBNET_SCHEMA_KEYS
            | spec_keys.SUBNET_RUNTIME_KEYS
            | spec_keys.INSTANCE_SCHEMA_KEYS
            | spec_keys.INSTANCE_RUNTIME_KEYS
            | spec_keys.AGENT_SCHEMA_KEYS
        )
        used = _dict_get_literal_keys_in_functions(_TERRAFORM_VARS, _SPEC_KEY_WALK_FUNCTIONS)
        unknown = used - allowed
        assert not unknown, f"Unregistered dict.get keys in terraform_vars.py: {sorted(unknown)}"
