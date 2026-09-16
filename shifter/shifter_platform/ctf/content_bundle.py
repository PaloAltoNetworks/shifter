"""Closed, data-only contract for native CTF event content bundles."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

BUNDLE_CONTRACT = "shifter-ctf-content/v1"
_MAX_BUNDLE_BYTES = 8 * 1024 * 1024
_MAX_CHALLENGES = 500
_MAX_FLAGS = 8
_MAX_HINTS = 32
_MAX_PREREQUISITES = 64
_MAX_NESTING_DEPTH = 8
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_DIFFICULTIES = frozenset({"easy", "medium", "hard", "expert"})
_VISIBILITIES = frozenset({"visible", "hidden", "locked"})
_DECAY_FUNCTIONS = frozenset({"linear", "logarithmic"})
_FLAG_TYPES = frozenset({"static", "regex", "http"})


class CtfContentBundleError(ValueError):
    """Raised when a native CTF content bundle violates its contract."""


@dataclass(frozen=True)
class BundleFlag:
    """One supported native flag declaration."""

    flag_type: str
    order: int
    case_sensitive: bool = True
    value: str = ""
    validator_config: dict[str, object] | None = None


@dataclass(frozen=True)
class BundleHint:
    """One ordered participant hint."""

    text: str
    penalty: int
    order: int


@dataclass(frozen=True)
class BundleChallenge:
    """One challenge and its bundle-local graph references."""

    source_id: str
    name: str
    description: str
    category: str
    points: int
    difficulty: str
    order: int
    flags: tuple[BundleFlag, ...]
    hints: tuple[BundleHint, ...]
    prerequisites: tuple[str, ...]
    flag_format: str = ""
    solution: str = ""
    max_attempts: int = 0
    minimum_points: int = 0
    decay_function: str = "linear"
    decay_solve_count: int = 0
    visibility: str = "visible"
    target_instance_name: str = ""
    target_port: int | None = None


@dataclass(frozen=True)
class CtfContentBundle:
    """Validated immutable bundle passed to the native hydration service."""

    scenario_id: str
    challenges: tuple[BundleChallenge, ...]
    contract: str = BUNDLE_CONTRACT


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build a JSON object while rejecting duplicate keys."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CtfContentBundleError("bundle contains a duplicate JSON key")
        result[key] = value
    return result


def _reject_unknown(value: Mapping[str, object], allowed: set[str], what: str) -> None:
    """Reject fields outside the closed set allowed for an object."""
    if set(value) - allowed:
        raise CtfContentBundleError(f"{what} contains unknown fields")


def _require_mapping(value: object, what: str) -> Mapping[str, object]:
    """Return an object-like value or raise a bundle contract error."""
    if not isinstance(value, Mapping):
        raise CtfContentBundleError(f"{what} must be an object")
    return value


def _require_list(value: object, what: str, *, maximum: int, minimum: int = 0) -> list[object]:
    """Return a list whose item count is within the declared bounds."""
    if not isinstance(value, list):
        raise CtfContentBundleError(f"{what} must be a list")
    if not minimum <= len(value) <= maximum:
        raise CtfContentBundleError(f"{what} has an invalid item count")
    return value


def _require_string(
    value: object,
    what: str,
    *,
    maximum: int,
    minimum: int = 1,
) -> str:
    """Return a bounded string without embedded null bytes."""
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or "\x00" in value:
        raise CtfContentBundleError(f"{what} is invalid")
    return value


def _require_identifier(value: object, what: str) -> str:
    """Return a normalized bundle identifier."""
    text = _require_string(value, what, maximum=100)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise CtfContentBundleError(f"{what} is invalid")
    return text


def _require_int(value: object, what: str, *, minimum: int, maximum: int) -> int:
    """Return a non-boolean integer within the declared bounds."""
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise CtfContentBundleError(f"{what} is invalid")
    return value


def _require_bool(value: object, what: str) -> bool:
    """Return a strict JSON boolean."""
    if not isinstance(value, bool):
        raise CtfContentBundleError(f"{what} must be a boolean")
    return value


def _require_choice(value: object, what: str, allowed: frozenset[str]) -> str:
    """Return a string selected from a closed set."""
    text = _require_string(value, what, maximum=32)
    if text not in allowed:
        raise CtfContentBundleError(f"{what} is unsupported")
    return text


def _check_depth(value: object, depth: int = 0) -> None:
    """Reject JSON structures deeper than the bundle contract allows."""
    if depth > _MAX_NESTING_DEPTH:
        raise CtfContentBundleError("bundle exceeds its nesting-depth limit")
    if isinstance(value, Mapping):
        for item in value.values():
            _check_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_depth(item, depth + 1)


def _parse_flag(value: object) -> BundleFlag:
    """Parse one supported native flag declaration."""
    flag = _require_mapping(value, "flag")
    flag_type = _require_choice(flag.get("type"), "flag type", _FLAG_TYPES)
    common = {"type", "order", "case_sensitive"}
    order = _require_int(flag.get("order", 0), "flag order", minimum=0, maximum=1000)
    case_sensitive = _require_bool(flag.get("case_sensitive", True), "flag case_sensitive")
    if flag_type in {"static", "regex"}:
        _reject_unknown(flag, common | {"value"}, "flag")
        return BundleFlag(
            flag_type=flag_type,
            order=order,
            case_sensitive=case_sensitive,
            value=_require_string(flag.get("value"), "flag value", maximum=2048),
        )

    _reject_unknown(
        flag,
        common | {"url", "method", "timeout", "headers", "protocol", "profile_id", "objective_id"},
        "flag",
    )
    from ctf.validators import HTTPValidatorConfigError, normalize_http_validator_config

    try:
        validator_config = normalize_http_validator_config(
            {key: item for key, item in flag.items() if key not in common}
        )
    except HTTPValidatorConfigError as exc:
        raise CtfContentBundleError("HTTP flag configuration is invalid") from exc
    return BundleFlag(
        flag_type=flag_type,
        order=order,
        case_sensitive=case_sensitive,
        validator_config=validator_config,
    )


def _parse_hint(value: object) -> BundleHint:
    """Parse one ordered participant hint."""
    hint = _require_mapping(value, "hint")
    _reject_unknown(hint, {"text", "penalty", "order"}, "hint")
    return BundleHint(
        text=_require_string(hint.get("text"), "hint text", maximum=16_384),
        penalty=_require_int(hint.get("penalty", 0), "hint penalty", minimum=0, maximum=100),
        order=_require_int(hint.get("order", 0), "hint order", minimum=0, maximum=1000),
    )


_CHALLENGE_FIELDS = {
    "id",
    "name",
    "description",
    "category",
    "points",
    "difficulty",
    "order",
    "flags",
    "hints",
    "prerequisites",
    "flag_format",
    "solution",
    "max_attempts",
    "minimum_points",
    "decay_function",
    "decay_solve_count",
    "visibility",
    "target_instance_name",
    "target_port",
}


def _parse_challenge(value: object) -> BundleChallenge:
    """Parse one challenge and its bundle-local relationships."""
    challenge = _require_mapping(value, "challenge")
    _reject_unknown(challenge, _CHALLENGE_FIELDS, "challenge")
    raw_flags = _require_list(challenge.get("flags"), "challenge flags", maximum=_MAX_FLAGS, minimum=1)
    flags = tuple(_parse_flag(flag) for flag in raw_flags)
    if len({flag.order for flag in flags}) != len(flags):
        raise CtfContentBundleError("challenge contains duplicate flag orders")

    raw_hints = _require_list(challenge.get("hints", []), "challenge hints", maximum=_MAX_HINTS)
    hints = tuple(_parse_hint(hint) for hint in raw_hints)
    if len({hint.order for hint in hints}) != len(hints):
        raise CtfContentBundleError("challenge contains duplicate hint orders")

    prerequisites = tuple(
        _require_identifier(item, "prerequisite id")
        for item in _require_list(
            challenge.get("prerequisites", []),
            "challenge prerequisites",
            maximum=_MAX_PREREQUISITES,
        )
    )
    if len(set(prerequisites)) != len(prerequisites):
        raise CtfContentBundleError("challenge contains duplicate prerequisite edges")

    target_port = challenge.get("target_port")
    if target_port is not None:
        target_port = _require_int(target_port, "challenge target_port", minimum=1, maximum=65535)
    return BundleChallenge(
        source_id=_require_identifier(challenge.get("id"), "challenge id"),
        name=_require_string(challenge.get("name"), "challenge name", maximum=200),
        description=_require_string(challenge.get("description"), "challenge description", maximum=65_536),
        category=_require_string(challenge.get("category"), "challenge category", maximum=100),
        points=_require_int(challenge.get("points"), "challenge points", minimum=1, maximum=10_000),
        difficulty=_require_choice(challenge.get("difficulty"), "challenge difficulty", _DIFFICULTIES),
        order=_require_int(challenge.get("order"), "challenge order", minimum=0, maximum=10_000),
        flags=flags,
        hints=hints,
        prerequisites=prerequisites,
        flag_format=_require_string(
            challenge.get("flag_format", ""),
            "challenge flag_format",
            maximum=100,
            minimum=0,
        ),
        solution=_require_string(
            challenge.get("solution", ""),
            "challenge solution",
            maximum=65_536,
            minimum=0,
        ),
        max_attempts=_require_int(
            challenge.get("max_attempts", 0),
            "challenge max_attempts",
            minimum=0,
            maximum=100_000,
        ),
        minimum_points=_require_int(
            challenge.get("minimum_points", 0),
            "challenge minimum_points",
            minimum=0,
            maximum=10_000,
        ),
        decay_function=_require_choice(
            challenge.get("decay_function", "linear"),
            "challenge decay_function",
            _DECAY_FUNCTIONS,
        ),
        decay_solve_count=_require_int(
            challenge.get("decay_solve_count", 0),
            "challenge decay_solve_count",
            minimum=0,
            maximum=1_000_000,
        ),
        visibility=_require_choice(
            challenge.get("visibility", "visible"),
            "challenge visibility",
            _VISIBILITIES,
        ),
        target_instance_name=_require_string(
            challenge.get("target_instance_name", ""),
            "challenge target_instance_name",
            maximum=100,
            minimum=0,
        ),
        target_port=target_port,
    )


def _reject_cycles(challenges: Sequence[BundleChallenge]) -> None:
    """Reject cycles in the challenge prerequisite graph."""
    graph = {challenge.source_id: challenge.prerequisites for challenge in challenges}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(source_id: str) -> None:
        """Visit one challenge using depth-first cycle detection."""
        if source_id in visiting:
            raise CtfContentBundleError("challenge prerequisites contain a cycle")
        if source_id in visited:
            return
        visiting.add(source_id)
        for prerequisite in graph[source_id]:
            visit(prerequisite)
        visiting.remove(source_id)
        visited.add(source_id)

    for source_id in graph:
        visit(source_id)


def _validate_graph(challenges: tuple[BundleChallenge, ...]) -> None:
    """Validate global uniqueness and prerequisite graph integrity."""
    ids = [challenge.source_id for challenge in challenges]
    names = [challenge.name for challenge in challenges]
    orders = [challenge.order for challenge in challenges]
    if len(set(ids)) != len(ids):
        raise CtfContentBundleError("bundle contains duplicate challenge ids")
    if len(set(names)) != len(names):
        raise CtfContentBundleError("bundle contains duplicate challenge names")
    if len(set(orders)) != len(orders):
        raise CtfContentBundleError("bundle contains duplicate challenge orders")
    known_ids = set(ids)
    for challenge in challenges:
        if challenge.source_id in challenge.prerequisites:
            raise CtfContentBundleError("a challenge cannot require itself")
        if not set(challenge.prerequisites) <= known_ids:
            raise CtfContentBundleError("challenge references an unknown prerequisite")
    _reject_cycles(challenges)


def _validate_native_flag_policy(challenges: tuple[BundleChallenge, ...]) -> None:
    """Reuse the native regex and HTTP policy before any database mutation."""
    from ctf.exceptions import CTFValidationError
    from ctf.services.challenge import validate_http_flag_config
    from ctf.services.regex_policy import UnsafeRegexError, validate_pattern

    try:
        for challenge in challenges:
            for flag in challenge.flags:
                if flag.flag_type == "regex":
                    validate_pattern(flag.value)
                elif flag.flag_type == "http":
                    validate_http_flag_config(flag.validator_config)
    except (CTFValidationError, UnsafeRegexError) as exc:
        raise CtfContentBundleError("bundle flag policy is invalid") from exc


def parse_ctf_content_bundle(raw: bytes) -> CtfContentBundle:
    """Parse and fully validate one native CTF content bundle."""
    if not isinstance(raw, bytes) or len(raw) > _MAX_BUNDLE_BYTES:
        raise CtfContentBundleError("bundle exceeds its byte limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CtfContentBundleError("bundle must be UTF-8 JSON") from exc
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except CtfContentBundleError:
        raise
    except (TypeError, ValueError) as exc:
        raise CtfContentBundleError("bundle is not valid JSON") from exc
    _check_depth(payload)
    root = _require_mapping(payload, "bundle")
    _reject_unknown(root, {"contract", "scenario_id", "challenges"}, "bundle")
    if root.get("contract") != BUNDLE_CONTRACT:
        raise CtfContentBundleError("bundle contract is unsupported")
    scenario_id = _require_identifier(root.get("scenario_id"), "bundle scenario_id")
    challenges = tuple(
        _parse_challenge(value)
        for value in _require_list(
            root.get("challenges"),
            "bundle challenges",
            maximum=_MAX_CHALLENGES,
            minimum=1,
        )
    )
    _validate_graph(challenges)
    _validate_native_flag_policy(challenges)
    return CtfContentBundle(scenario_id=scenario_id, challenges=challenges)


__all__ = [
    "BUNDLE_CONTRACT",
    "BundleChallenge",
    "BundleFlag",
    "BundleHint",
    "CtfContentBundle",
    "CtfContentBundleError",
    "parse_ctf_content_bundle",
]
