"""Backward-compatibility differ for published JSON schemas (issue #1323).

:func:`find_incompatible_changes` reports where a ``new`` schema rejects instances a
``old`` schema accepted: a removed property, a removed enum value, a newly required
property, a narrowed type or union, a tightened numeric/string/array constraint, an added
``allOf``/``items`` constraint, or ``additionalProperties`` restricted. It recurses through
``properties``, ``$defs`` (resolving local ``$ref``), array ``items``/``prefixItems``, and
``anyOf``/``oneOf``/``allOf`` branches, and **fails closed** on any validation keyword it
does not model, so an unmodelled Draft 2020-12 narrowing cannot slip through. Additive
changes are compatible and not reported. Used by the backend-bundle contract's
breaking-change gate; constrained by ADR-011.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_REF_PREFIX = "#/$defs/"
_DEFS_KEY = "$defs"
_MISSING = object()

#: (old $defs, new $defs) reference maps threaded through the recursion for ``$ref`` resolution.
_Defs = tuple[Mapping[str, Any], Mapping[str, Any]]

# Bound keywords: tightening a lower bound (added or raised) or an upper bound (added or
# lowered) rejects previously valid instances.
_LOWER_BOUND_KEYWORDS = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")
_UPPER_BOUND_KEYWORDS = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")

# Validation keywords the differ reasons about explicitly. A change to any other validation
# keyword is treated as potentially breaking (fail closed).
_HANDLED_KEYWORDS = frozenset(
    {
        "type",
        "enum",
        "const",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "prefixItems",
        "anyOf",
        "oneOf",
        "allOf",
        "not",
        "pattern",
        "multipleOf",
        "uniqueItems",
        "$ref",
        *_LOWER_BOUND_KEYWORDS,
        *_UPPER_BOUND_KEYWORDS,
    }
)
# Annotation/metadata keywords that never affect validation — changing them is compatible.
_ANNOTATION_KEYWORDS = frozenset(
    {
        "title",
        "description",
        "default",
        "examples",
        "readOnly",
        "writeOnly",
        "deprecated",
        "$comment",
        "$id",
        "$schema",
        "$defs",
        "definitions",
        "$anchor",
    }
)


def _resolve_ref(node: Mapping[str, Any], defs: Mapping[str, Any]) -> Mapping[str, Any]:
    """Resolve a local ``#/$defs/<name>`` reference to its definition (single level)."""
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
        target = defs.get(ref.removeprefix(_REF_PREFIX))
        if isinstance(target, Mapping):
            return target
    return node


def _type_set(schema: Mapping[str, Any]) -> set[str] | None:
    """The set of JSON types a schema allows, or ``None`` when unconstrained."""
    value = schema.get("type")
    if value is None:
        return None
    return {value} if isinstance(value, str) else set(value)


def _diff_types(old: Mapping[str, Any], new: Mapping[str, Any], path: str, changes: list[str]) -> None:
    """Flag a narrowed JSON ``type`` set."""
    old_types, new_types = _type_set(old), _type_set(new)
    if new_types is None:
        return
    if old_types is None:
        changes.append(f"{path}: type restricted to {sorted(new_types)} (was unconstrained)")
    elif not old_types.issubset(new_types):
        changes.append(f"{path}: type(s) {sorted(old_types - new_types)} no longer accepted")


def _diff_enum_const(old: Mapping[str, Any], new: Mapping[str, Any], path: str, changes: list[str]) -> None:
    """Flag a removed enum value, a newly fixed enum, or an added/changed ``const``."""
    old_enum, new_enum = old.get("enum"), new.get("enum")
    if old_enum is None and new_enum is not None:
        changes.append(f"{path}: values restricted to a fixed enum")
    elif old_enum is not None and new_enum is not None:
        for value in old_enum:
            if value not in new_enum:
                changes.append(f"{path}: enum value {value!r} removed")
    old_const, new_const = old.get("const", _MISSING), new.get("const", _MISSING)
    if new_const is not _MISSING and new_const != old_const:
        changes.append(f"{path}: const value added or changed")


def _flag_bounds(
    old: Mapping[str, Any],
    new: Mapping[str, Any],
    path: str,
    changes: list[str],
    keywords: tuple[str, ...],
    *,
    lower: bool,
) -> None:
    """Flag any bound keyword in ``keywords`` that was added or moved inward."""
    for keyword in keywords:
        o, n = old.get(keyword), new.get(keyword)
        if n is None:
            continue
        if o is None or (n > o if lower else n < o):
            changes.append(f"{path}: {keyword} tightened")


def _diff_bounds(old: Mapping[str, Any], new: Mapping[str, Any], path: str, changes: list[str]) -> None:
    """Flag tightened numeric/length/size bounds."""
    _flag_bounds(old, new, path, changes, _LOWER_BOUND_KEYWORDS, lower=True)
    _flag_bounds(old, new, path, changes, _UPPER_BOUND_KEYWORDS, lower=False)


def _diff_scalar_constraints(old: Mapping[str, Any], new: Mapping[str, Any], path: str, changes: list[str]) -> None:
    """Flag a tightened pattern / multipleOf / uniqueItems, or an added/changed ``not``."""
    if new.get("pattern") is not None and new.get("pattern") != old.get("pattern"):
        changes.append(f"{path}: pattern tightened")
    if new.get("multipleOf") is not None and new.get("multipleOf") != old.get("multipleOf"):
        changes.append(f"{path}: multipleOf tightened")
    if new.get("uniqueItems") is True and old.get("uniqueItems") is not True:
        changes.append(f"{path}: uniqueItems now required")
    if new.get("not") is not None and new.get("not") != old.get("not"):
        changes.append(f"{path}: 'not' constraint added or changed")


def _diff_sequence(
    old_seq: list[object], new_seq: list[object], defs: _Defs, changes: list[str], depth: int, prefix: str
) -> None:
    """Recurse pairwise into two schema sequences (union branches / positional items)."""
    for index, (old_item, new_item) in enumerate(zip(old_seq, new_seq, strict=False)):
        _diff_schema(old_item, new_item, defs, f"{prefix}[{index}]", changes, depth + 1)


def _diff_additional_properties(
    old: Mapping[str, Any], new: Mapping[str, Any], defs: _Defs, path: str, changes: list[str], depth: int
) -> None:
    """Flag ``additionalProperties`` tightened to ``false`` or to a constraining schema."""
    old_ap = old.get("additionalProperties", True)
    new_ap = new.get("additionalProperties", True)
    if new_ap is False and old_ap is not False:
        changes.append(f"{path}: additionalProperties restricted to false")
        return
    if not isinstance(new_ap, Mapping) or new_ap == {}:
        return
    if old_ap is True or old_ap == {}:
        changes.append(f"{path}: additionalProperties restricted to a schema")
    elif isinstance(old_ap, Mapping):
        _diff_schema(old_ap, new_ap, defs, f"{path}.additionalProperties", changes, depth + 1)


def _diff_object(
    old: Mapping[str, Any], new: Mapping[str, Any], defs: _Defs, path: str, changes: list[str], depth: int
) -> None:
    """Flag removed properties, newly required properties, and additionalProperties tightening."""
    old_props = old.get("properties") or {}
    new_props = new.get("properties") or {}
    for name, old_prop in old_props.items():
        if name not in new_props:
            changes.append(f"{path}.{name}: property removed")
        else:
            _diff_schema(old_prop, new_props[name], defs, f"{path}.{name}", changes, depth + 1)
    for name in sorted(set(new.get("required") or []) - set(old.get("required") or [])):
        changes.append(f"{path}.{name}: newly required")
    _diff_additional_properties(old, new, defs, path, changes, depth)


def _diff_union(
    old: Mapping[str, Any], new: Mapping[str, Any], defs: _Defs, path: str, changes: list[str], depth: int
) -> None:
    """Flag a newly added or narrowed ``anyOf``/``oneOf`` alternative set."""
    for keyword in ("anyOf", "oneOf"):
        old_branches, new_branches = old.get(keyword), new.get(keyword)
        if isinstance(new_branches, list) and not isinstance(old_branches, list):
            changes.append(f"{path}: {keyword} constraint added (was unconstrained)")
        elif isinstance(old_branches, list) and isinstance(new_branches, list):
            if len(new_branches) < len(old_branches):
                changes.append(f"{path}: {keyword} narrowed ({len(old_branches)} -> {len(new_branches)} alternatives)")
            _diff_sequence(old_branches, new_branches, defs, changes, depth, f"{path}.{keyword}")


def _diff_allof(
    old: Mapping[str, Any], new: Mapping[str, Any], defs: _Defs, path: str, changes: list[str], depth: int
) -> None:
    """Flag a newly added or narrowed ``allOf`` constraint set (more constraints = narrower)."""
    old_all, new_all = old.get("allOf"), new.get("allOf")
    if isinstance(new_all, list) and not isinstance(old_all, list):
        changes.append(f"{path}: allOf constraint added (was unconstrained)")
    elif isinstance(old_all, list) and isinstance(new_all, list):
        if len(new_all) > len(old_all):
            changes.append(f"{path}: allOf narrowed ({len(old_all)} -> {len(new_all)} constraints)")
        _diff_sequence(old_all, new_all, defs, changes, depth, f"{path}.allOf")


def _diff_array(
    old: Mapping[str, Any], new: Mapping[str, Any], defs: _Defs, path: str, changes: list[str], depth: int
) -> None:
    """Flag newly added or narrowed array ``items``/``prefixItems`` constraints."""
    old_items, new_items = old.get("items"), new.get("items")
    if isinstance(new_items, Mapping) and not isinstance(old_items, Mapping):
        changes.append(f"{path}: items constraint added (was unconstrained)")
    elif isinstance(old_items, Mapping) and isinstance(new_items, Mapping):
        _diff_schema(old_items, new_items, defs, f"{path}.items", changes, depth + 1)
    old_prefix, new_prefix = old.get("prefixItems"), new.get("prefixItems")
    if isinstance(new_prefix, list) and not isinstance(old_prefix, list):
        changes.append(f"{path}: prefixItems constraint added (was unconstrained)")
    elif isinstance(old_prefix, list) and isinstance(new_prefix, list):
        if len(new_prefix) > len(old_prefix):
            changes.append(f"{path}: prefixItems added positional constraints")
        _diff_sequence(old_prefix, new_prefix, defs, changes, depth, f"{path}.prefixItems")


def _diff_unknown_keywords(old: Mapping[str, Any], new: Mapping[str, Any], path: str, changes: list[str]) -> None:
    """Fail closed: any changed validation keyword the differ does not model is a potential break."""
    for keyword in sorted((set(old) | set(new)) - _HANDLED_KEYWORDS - _ANNOTATION_KEYWORDS):
        if old.get(keyword, _MISSING) != new.get(keyword, _MISSING):
            changes.append(f"{path}: unrecognized validation keyword {keyword!r} changed (treated as incompatible)")


def _normalize_boolean_schema(
    old: object, new: object, path: str, changes: list[str]
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    """Resolve boolean subschemas (``true`` = accept all, ``false`` = accept none).

    Returns the ``(old, new)`` mapping pair to keep diffing, or ``None`` when the comparison
    is already resolved (a break was recorded, or the change is a compatible widening).
    """
    result: tuple[Mapping[str, Any], Mapping[str, Any]] | None
    if new is False and old is not False:
        changes.append(f"{path}: now rejects all values")
        result = None
    elif new is True or old is False:
        result = None
    else:
        normalized_old = {} if old is True else old
        both_mappings = isinstance(normalized_old, Mapping) and isinstance(new, Mapping)
        result = (normalized_old, new) if both_mappings else None
    return result


def _diff_schema(old: object, new: object, defs: _Defs, path: str, changes: list[str], depth: int = 0) -> None:
    """Recursively record where ``new`` rejects instances that ``old`` accepted."""
    if depth > 64:
        return
    if isinstance(old, Mapping):
        old = _resolve_ref(old, defs[0])
    if isinstance(new, Mapping):
        new = _resolve_ref(new, defs[1])
    normalized = _normalize_boolean_schema(old, new, path, changes)
    if normalized is None:
        return
    old_map, new_map = normalized
    _diff_types(old_map, new_map, path, changes)
    _diff_enum_const(old_map, new_map, path, changes)
    _diff_bounds(old_map, new_map, path, changes)
    _diff_scalar_constraints(old_map, new_map, path, changes)
    _diff_object(old_map, new_map, defs, path, changes, depth)
    _diff_union(old_map, new_map, defs, path, changes, depth)
    _diff_allof(old_map, new_map, defs, path, changes, depth)
    _diff_array(old_map, new_map, defs, path, changes, depth)
    _diff_unknown_keywords(old_map, new_map, path, changes)


def find_incompatible_changes(old_schema: Mapping[str, Any], new_schema: Mapping[str, Any]) -> list[str]:
    """Return the backward-incompatible changes from ``old_schema`` to ``new_schema``.

    An empty list means ``new_schema`` is backward-compatible with ``old_schema``. See the
    module docstring for the change classes reported and the fail-closed guarantee.
    """
    changes: list[str] = []
    defs = (old_schema.get(_DEFS_KEY) or {}, new_schema.get(_DEFS_KEY) or {})
    _diff_schema(old_schema, new_schema, defs, "root", changes)
    return sorted(dict.fromkeys(changes))
