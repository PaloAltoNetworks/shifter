"""Tests for SECRET_KEY_FALLBACKS parsing (issue #159).

SECRET_KEY_FALLBACKS lets a SECRET_KEY rotation keep existing signed sessions
valid (the previous key still verifies) so the rollout forces no logout.
"""

from __future__ import annotations

import json

import pytest

from config._database_settings import SECRET_KEY_FALLBACKS_MAX, parse_secret_key_fallbacks


@pytest.mark.parametrize("raw", ["", "   ", "\n\n", "[]"])
def test_empty_inputs_yield_no_fallbacks(raw):
    assert parse_secret_key_fallbacks(raw) == []


def test_json_array_is_parsed_in_order():
    assert parse_secret_key_fallbacks('["old1", "old2"]') == ["old1", "old2"]


def test_json_array_filters_blank_entries():
    assert parse_secret_key_fallbacks('["old1", "", "  ", "old2"]') == ["old1", "old2"]


def test_newline_separated_fallback_form():
    assert parse_secret_key_fallbacks("old1\nold2\n") == ["old1", "old2"]


def test_newline_form_preserves_commas_in_keys():
    # Django SECRET_KEYs can contain commas, so the non-JSON form splits on
    # newlines (not commas) to keep each key intact.
    assert parse_secret_key_fallbacks("ke,y1\nkey2") == ["ke,y1", "key2"]


def test_non_list_json_is_rejected():
    with pytest.raises(ValueError, match="array of strings"):
        parse_secret_key_fallbacks('{"old": 1}')


def test_max_count_is_allowed():
    keys = [f"key{i}" for i in range(SECRET_KEY_FALLBACKS_MAX)]
    assert parse_secret_key_fallbacks(json.dumps(keys)) == keys


def test_exceeding_max_count_is_rejected():
    keys = [f"key{i}" for i in range(SECRET_KEY_FALLBACKS_MAX + 1)]
    with pytest.raises(ValueError, match="maximum is"):
        parse_secret_key_fallbacks(json.dumps(keys))
