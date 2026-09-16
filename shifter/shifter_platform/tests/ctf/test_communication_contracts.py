"""Closed audience/trigger/channel shapes and the safe content profile (ADR-051, #2048).

Pure, DB-free validators for the communication domain. Every test drives the real
validator and asserts the effect (accept the safe shape, reject the hostile one),
so it goes red if a bound or a rejection rule is removed. These cover the issue's
"content bounds" and closed-vocabulary acceptance criteria.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from ctf.communication_contracts import (
    CONTENT_PROFILE_V1,
    MAX_BODY_BYTES,
    MAX_SUBJECT_CODEPOINTS,
    validate_audience_spec,
    validate_channels,
    validate_message_content,
    validate_trigger_spec,
)
from ctf.exceptions import CTFCommunicationError

ALLOWED_HOSTS = frozenset({"docs.example.com"})


# ---------------------------------------------------------------------------
# Message content: ctf-communication-markdown/v1
# ---------------------------------------------------------------------------


def _content(**overrides):
    data = {
        "subject": "Welcome to the event",
        "body": "# Hello\n\nRead the **rules** and good luck.",
    }
    data.update(overrides)
    return data


def _assert_content_rejected(**overrides):
    """Build content outside the raises-block so the validator is the only throwing call."""
    content = _content(**overrides)
    with pytest.raises(CTFCommunicationError):
        validate_message_content(content, allowed_link_hosts=ALLOWED_HOSTS)


def test_valid_markdown_content_is_accepted_and_digested():
    result = validate_message_content(_content(), allowed_link_hosts=ALLOWED_HOSTS)

    assert result["subject"] == "Welcome to the event"
    assert result["profile"] == CONTENT_PROFILE_V1
    assert result["digest"].startswith("sha256:")


def test_empty_subject_is_rejected():
    _assert_content_rejected(subject="   ")


def test_oversized_subject_is_rejected():
    _assert_content_rejected(subject="x" * (MAX_SUBJECT_CODEPOINTS + 1))


def test_control_characters_in_subject_are_rejected():
    _assert_content_rejected(subject="bad\x07subject")


def test_oversized_body_is_rejected():
    _assert_content_rejected(body="a" * (MAX_BODY_BYTES + 1))


@pytest.mark.parametrize(
    "body",
    [
        "<script>alert(1)</script>",
        "Hello <div>raw html</div>",
        "<img src=x onerror=alert(1)>",
        "<iframe src='https://evil.example'></iframe>",
    ],
)
def test_raw_html_is_rejected(body):
    _assert_content_rejected(body=body)


@pytest.mark.parametrize(
    "body",
    [
        "[click](javascript:alert(1))",
        "[data](data:text/html;base64,PHNjcmlwdD4=)",
        "[file](file:///etc/passwd)",
        "[shell](vbscript:msgbox)",
    ],
)
def test_dangerous_url_schemes_are_rejected(body):
    _assert_content_rejected(body=body)


def test_external_link_to_disallowed_host_is_rejected():
    _assert_content_rejected(body="See [here](https://evil.example.com/x)")


def test_external_link_to_allowed_host_is_accepted():
    result = validate_message_content(
        _content(body="See [docs](https://docs.example.com/guide)"), allowed_link_hosts=ALLOWED_HOSTS
    )
    assert result["digest"].startswith("sha256:")


def test_relative_link_is_accepted():
    result = validate_message_content(_content(body="See [rules](/events/rules)"), allowed_link_hosts=ALLOWED_HOSTS)
    assert result["digest"].startswith("sha256:")


@pytest.mark.parametrize(
    "url",
    [
        "https://192.168.0.1/x",  # IP literal
        "https://user:pass@docs.example.com/x",  # credentials
        "http://docs.example.com/x",  # non-https external
        "https://localhost/x",  # localhost
    ],
)
def test_unsafe_link_hosts_are_rejected(url):
    _assert_content_rejected(body=f"[x]({url})")


def test_identical_content_produces_a_stable_digest():
    first = validate_message_content(_content(), allowed_link_hosts=ALLOWED_HOSTS)
    second = validate_message_content(_content(), allowed_link_hosts=ALLOWED_HOSTS)
    assert first["digest"] == second["digest"]


def test_protocol_relative_link_is_rejected():
    # `//host` is resolved by browsers as an external origin, so it must not slip
    # through as a "relative" path (codex security finding).
    _assert_content_rejected(body="[login](//attacker.example/login)")


def test_backslash_in_link_is_rejected():
    _assert_content_rejected(body="[x](/\\attacker.example)")


def test_reference_style_link_to_disallowed_host_is_rejected():
    _assert_content_rejected(body="See [the rules][r] for details.\n\n[r]: https://attacker.example/phish")


def test_reference_style_link_to_allowed_host_is_accepted():
    body = "See [the docs][d].\n\n[d]: https://docs.example.com/guide"
    result = validate_message_content(_content(body=body), allowed_link_hosts=ALLOWED_HOSTS)
    assert result["digest"].startswith("sha256:")


def test_bare_url_to_disallowed_host_is_rejected():
    _assert_content_rejected(body="Visit https://attacker.example now")


def test_image_destination_to_disallowed_host_is_rejected():
    _assert_content_rejected(body="![logo](https://attacker.example/x.png)")


# ---------------------------------------------------------------------------
# Audience spec (closed selector)
# ---------------------------------------------------------------------------


def test_single_participant_audience_is_accepted():
    spec = {"kind": "participant", "participant_ids": [str(uuid4())]}
    result = validate_audience_spec(spec)
    assert result["kind"] == "participant"


def test_multi_event_audience_requires_at_least_two_events():
    with pytest.raises(CTFCommunicationError):
        validate_audience_spec({"kind": "multi_event", "event_ids": [str(uuid4())]})


def test_team_audience_is_accepted():
    result = validate_audience_spec({"kind": "team", "team_ids": [str(uuid4()), str(uuid4())]})
    assert result["kind"] == "team"


def test_audience_rejects_email_addresses():
    with pytest.raises(CTFCommunicationError):
        validate_audience_spec({"kind": "participant", "emails": ["a@b.com"]})


def test_audience_rejects_unknown_keys():
    with pytest.raises(CTFCommunicationError):
        validate_audience_spec({"kind": "event", "event_ids": [str(uuid4())], "sql": "1=1"})


def test_audience_rejects_non_uuid_identifiers():
    with pytest.raises(CTFCommunicationError):
        validate_audience_spec({"kind": "participant", "participant_ids": ["not-a-uuid"]})


def test_audience_rejects_unknown_kind():
    with pytest.raises(CTFCommunicationError):
        validate_audience_spec({"kind": "everyone"})


# ---------------------------------------------------------------------------
# Trigger spec (closed declaration)
# ---------------------------------------------------------------------------


def test_manual_trigger_is_accepted():
    assert validate_trigger_spec({"kind": "manual"})["kind"] == "manual"


def test_absolute_time_trigger_requires_a_due_time():
    result = validate_trigger_spec({"kind": "absolute_time", "due_at": "2026-10-01T00:00:00Z"})
    assert result["kind"] == "absolute_time"


def test_absolute_time_trigger_without_due_time_is_rejected():
    with pytest.raises(CTFCommunicationError):
        validate_trigger_spec({"kind": "absolute_time"})


def test_trigger_rejects_unknown_kind_and_extra_keys():
    with pytest.raises(CTFCommunicationError):
        validate_trigger_spec({"kind": "manual", "callable": "os.system"})
    with pytest.raises(CTFCommunicationError):
        validate_trigger_spec({"kind": "webhook"})


def test_absolute_time_normalizes_to_utc():
    # A timezone-aware instant is accepted and normalized to a canonical UTC form,
    # so downstream due-time comparison never depends on the caller's offset (#2099).
    result = validate_trigger_spec({"kind": "absolute_time", "due_at": "2026-10-01T05:00:00+05:00"})
    assert result["due_at"] == "2026-10-01T00:00:00+00:00"


def test_absolute_time_rejects_naive_and_malformed_due_at():
    # A naive datetime is ambiguous (no offset); reject rather than guess a zone.
    with pytest.raises(CTFCommunicationError):
        validate_trigger_spec({"kind": "absolute_time", "due_at": "2026-10-01T00:00:00"})
    with pytest.raises(CTFCommunicationError):
        validate_trigger_spec({"kind": "absolute_time", "due_at": "not-a-timestamp"})


def test_event_lifecycle_requires_a_known_event_status():
    assert validate_trigger_spec({"kind": "event_lifecycle", "event_status": "active"})["event_status"] == "active"
    with pytest.raises(CTFCommunicationError):
        validate_trigger_spec({"kind": "event_lifecycle", "event_status": "bogus_status"})


def test_trigger_reference_refs_are_length_bounded():
    over = "x" * 300
    with pytest.raises(CTFCommunicationError):
        validate_trigger_spec({"kind": "range_signal", "declaration_ref": over})
    with pytest.raises(CTFCommunicationError):
        validate_trigger_spec({"kind": "raes_occurrence", "declaration_ref": "d1", "occurrence_ref": over})


def test_audience_rejects_an_oversized_id_list():
    too_many = [str(uuid4()) for _ in range(5001)]
    with pytest.raises(CTFCommunicationError):
        validate_audience_spec({"kind": "participant_set", "participant_ids": too_many})


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------


def test_channels_accepts_a_valid_subset():
    assert validate_channels(["in_app", "email"]) == ["in_app", "email"]


def test_channels_rejects_empty():
    with pytest.raises(CTFCommunicationError):
        validate_channels([])


def test_channels_rejects_duplicates_and_unknown():
    with pytest.raises(CTFCommunicationError):
        validate_channels(["in_app", "in_app"])
    with pytest.raises(CTFCommunicationError):
        validate_channels(["carrier_pigeon"])
