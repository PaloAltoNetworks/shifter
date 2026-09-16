"""Contract tests for deployment-owned native CTF content references."""

from __future__ import annotations

import json

import pytest

from shared.schemas.ctf_content_reference import (
    CtfContentReferenceError,
    load_ctf_content_references_json,
)

PREFIX = "ctf/content-bundles"
DIGEST = f"sha256:{'a' * 64}"


def _payload(reference: dict[str, object] | None = None) -> str:
    return json.dumps(
        {
            "contract": "shifter-ctf-content-references/v1",
            "references": [
                reference
                or {
                    "scenario_id": "scenario-one",
                    "object_key": "ctf/content-bundles/aa/bundle.json",
                    "digest": DIGEST,
                }
            ],
        }
    )


def test_empty_configuration_is_inert() -> None:
    catalog = load_ctf_content_references_json("", prefix=PREFIX)
    assert catalog.references == {}


def test_valid_reference_is_indexed_by_scenario() -> None:
    catalog = load_ctf_content_references_json(_payload(), prefix=PREFIX)
    assert catalog.get("scenario-one").digest == DIGEST


@pytest.mark.parametrize(
    "reference",
    [
        {
            "scenario_id": "scenario-one",
            "object_key": "../bundle.json",
            "digest": DIGEST,
        },
        {
            "scenario_id": "scenario-one",
            "object_key": "outside/bundle.json",
            "digest": DIGEST,
        },
        {
            "scenario_id": "scenario-one",
            "object_key": "ctf/content-bundles/bundle.json",
            "digest": "sha256:not-a-digest",
        },
        {
            "scenario_id": "Scenario One",
            "object_key": "ctf/content-bundles/bundle.json",
            "digest": DIGEST,
        },
        {
            "scenario_id": "scenario-one",
            "object_key": "ctf/content-bundles/bundle.json",
            "digest": DIGEST,
            "url": "https://example.test",
        },
    ],
)
def test_invalid_reference_fails_closed(reference: dict[str, object]) -> None:
    raw = _payload(reference)
    with pytest.raises(CtfContentReferenceError):
        load_ctf_content_references_json(raw, prefix=PREFIX)


def test_duplicate_json_key_is_rejected() -> None:
    raw = (
        '{"contract":"shifter-ctf-content-references/v1",'
        '"contract":"shifter-ctf-content-references/v1","references":[]}'
    )
    with pytest.raises(CtfContentReferenceError, match="duplicate"):
        load_ctf_content_references_json(raw, prefix=PREFIX)


def test_duplicate_scenario_is_rejected() -> None:
    reference = {
        "scenario_id": "scenario-one",
        "object_key": "ctf/content-bundles/aa/bundle.json",
        "digest": DIGEST,
    }
    raw = json.dumps(
        {
            "contract": "shifter-ctf-content-references/v1",
            "references": [reference, reference],
        }
    )
    with pytest.raises(CtfContentReferenceError, match="duplicate scenario"):
        load_ctf_content_references_json(raw, prefix=PREFIX)
