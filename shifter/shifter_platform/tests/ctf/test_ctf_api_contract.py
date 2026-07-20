"""Contract tests for the typed ``/api/v1/ctf/`` OpenAPI surface (#1372).

Integration-style: loads the committed OpenAPI artifact (the single published
contract that ``manage.py api_contract`` regenerates and the SPA type generation
consumes; the ``--check`` drift gate keeps it byte-identical to the live DRF
views and serializers) and asserts two invariants the CTF workspace SPA depends
on:

1. The canonical CTF workspace paths are published.
2. The participant browse/detail projections never carry flag material
   (``flag_hash``, ``flag_format``) — a participant must not be able to obtain or
   verify a flag from the typed read surface.

``solution`` is intentionally declared on the participant *detail* projection
but is populated only after the event ends/archives (``ctf.api.projections``,
``show_solution`` gate at line ~190) — a post-event writeup, not a live leak — so
it is asserted absent from the participant *browse* list only. The organizer
challenge detail legitimately exposes ``flag_format``/``solution``; a positive
control asserts that split is a real projection boundary rather than the fields
simply vanishing everywhere.
"""

from __future__ import annotations

import json

import pytest

from shared.api.contract import artifact_path

# Flag material that must never appear on any participant-facing challenge type.
_FLAG_MATERIAL = ("flag_hash", "flag_format")

# Participant-facing challenge components (browse item, solve detail, attachment).
_PARTICIPANT_CHALLENGE_COMPONENTS = (
    "ParticipantChallengeListItem",
    "ParticipantChallengeDetail",
    "ParticipantChallengeFile",
)


@pytest.fixture(scope="module")
def openapi_document() -> dict:
    """Load the committed ``/api/v1/`` OpenAPI contract once for the module."""
    return json.loads(artifact_path().read_text(encoding="utf-8"))


def _component_properties(document: dict, name: str) -> set[str]:
    """Return the declared property names of a components.schemas entry."""
    schemas = document["components"]["schemas"]
    assert name in schemas, f"expected component {name!r} in the OpenAPI schema"
    return set(schemas[name].get("properties", {}))


def test_ctf_workspace_paths_published(openapi_document: dict) -> None:
    """The representative CTF workspace paths are in the published contract."""
    paths = openapi_document["paths"]
    for expected in (
        "/api/v1/ctf/events/",
        "/api/v1/ctf/me/challenges/",
        "/api/v1/ctf/me/event/",
        "/api/v1/ctf/events/{event_id}/organizer-scoreboard/",
    ):
        assert expected in paths, f"missing CTF path {expected!r}"


def test_participant_challenge_types_hide_flag_material(openapi_document: dict) -> None:
    """Participant browse/detail/file projections never expose flag material."""
    for name in _PARTICIPANT_CHALLENGE_COMPONENTS:
        props = _component_properties(openapi_document, name)
        leaked = sorted(set(_FLAG_MATERIAL) & props)
        assert not leaked, f"{name} leaks flag material: {leaked}"


def test_participant_browse_list_hides_solution(openapi_document: dict) -> None:
    """The participant browse list never carries a solution field.

    The participant *detail* projection intentionally declares ``solution`` but
    gates it to ended/archived events (see module docstring); the browse list has
    no such field at all.
    """
    props = _component_properties(openapi_document, "ParticipantChallengeListItem")
    assert "solution" not in props


def test_organizer_detail_retains_flag_format_and_solution(openapi_document: dict) -> None:
    """Positive control: the organizer detail still exposes flag_format/solution.

    Confirms the participant/organizer split is a real projection boundary rather
    than the flag fields simply vanishing from the whole schema.
    """
    props = _component_properties(openapi_document, "OrganizerChallengeDetail")
    assert {"flag_format", "solution"} <= props
