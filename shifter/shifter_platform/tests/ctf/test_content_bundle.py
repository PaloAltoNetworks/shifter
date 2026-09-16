"""Closed-schema and graph tests for native CTF content bundles."""

from __future__ import annotations

import json

import pytest

from ctf.content_bundle import CtfContentBundleError, parse_ctf_content_bundle


def _challenge(source_id: str = "challenge-one", **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": source_id,
        "name": source_id.replace("-", " ").title(),
        "description": "Find the participant-visible evidence.",
        "category": "Module 1",
        "points": 100,
        "difficulty": "easy",
        "order": 1,
        "flags": [
            {
                "type": "http",
                "url": "https://validator.example.test/verify",
                "method": "POST",
                "timeout": 5,
                "headers": {},
                "order": 0,
            }
        ],
        "hints": [{"text": "Inspect the portal.", "penalty": 0, "order": 1}],
        "prerequisites": [],
    }
    value.update(overrides)
    return value


def _bundle(challenges: list[dict[str, object]] | None = None, **overrides: object) -> bytes:
    value: dict[str, object] = {
        "contract": "shifter-ctf-content/v1",
        "scenario_id": "scenario-one",
        "challenges": challenges or [_challenge()],
    }
    value.update(overrides)
    return json.dumps(value).encode()


def test_valid_bundle_parses_to_immutable_contract() -> None:
    bundle = parse_ctf_content_bundle(_bundle())
    assert bundle.scenario_id == "scenario-one"
    assert bundle.challenges[0].flags[0].flag_type == "http"
    assert bundle.challenges[0].hints[0].order == 1


@pytest.mark.parametrize(
    "payload",
    [
        _bundle(contract="shifter-ctf-content/v2"),
        _bundle(extra=True),
        _bundle([_challenge(flags=[{"type": "programmable", "order": 0}])]),
        _bundle([_challenge(flags=[{"type": "http", "url": "http://validator.example.test", "order": 0}])]),
        _bundle([_challenge(flags=[])]),
        _bundle([_challenge(hints=[{"text": "one", "order": 1}, {"text": "two", "order": 1}])]),
        _bundle([_challenge(prerequisites=["missing"])]),
        _bundle([_challenge(prerequisites=["challenge-one"])]),
        _bundle([_challenge(), _challenge("challenge-two", order=1)]),
    ],
)
def test_invalid_bundle_fails_closed(payload: bytes) -> None:
    with pytest.raises(CtfContentBundleError):
        parse_ctf_content_bundle(payload)


def test_cycle_is_rejected() -> None:
    payload = _bundle(
        [
            _challenge("challenge-one", prerequisites=["challenge-two"]),
            _challenge("challenge-two", order=2, prerequisites=["challenge-one"]),
        ]
    )
    with pytest.raises(CtfContentBundleError, match="cycle"):
        parse_ctf_content_bundle(payload)


def test_duplicate_json_key_is_rejected() -> None:
    raw = (
        b'{"contract":"shifter-ctf-content/v1","scenario_id":"scenario-one",'
        b'"scenario_id":"scenario-two","challenges":[]}'
    )
    with pytest.raises(CtfContentBundleError, match="duplicate"):
        parse_ctf_content_bundle(raw)
