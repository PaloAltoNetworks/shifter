"""Bounded, fail-loud communication settings parsers (ADR-051, #2048).

The retention window and link-host allowlist are typed, bounded, server-owned
settings. Malformed values must fail loudly at startup rather than silently
weaken content policy or retention. These test the pure parsers directly.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from config._ctf_communication_settings import (
    _parse_allowed_link_hosts,
    _parse_float,
    _parse_int,
    _parse_metrics_namespace,
    _parse_retention_days,
)


def test_retention_days_defaults_and_bounds():
    assert _parse_retention_days("90") == 90
    assert _parse_retention_days("1") == 1
    assert _parse_retention_days("365") == 365


@pytest.mark.parametrize("raw", ["0", "366", "-5", "abc", ""])
def test_retention_days_rejects_out_of_range_or_nonnumeric(raw):
    with pytest.raises(ImproperlyConfigured):
        _parse_retention_days(raw)


def test_allowed_link_hosts_parses_and_normalizes():
    assert _parse_allowed_link_hosts("Docs.Example.com, cdn.example.com") == frozenset(
        {"docs.example.com", "cdn.example.com"}
    )


def test_allowed_link_hosts_empty_is_no_external_hosts():
    assert _parse_allowed_link_hosts("") == frozenset()


@pytest.mark.parametrize(
    "raw",
    [
        "https://docs.example.com",  # scheme
        "docs.example.com/path",  # path
        "bad host.com",  # space
        "user@docs.example.com",  # credentials
    ],
)
def test_allowed_link_hosts_rejects_malformed_entries(raw):
    with pytest.raises(ImproperlyConfigured):
        _parse_allowed_link_hosts(raw)


# --- Delivery-engine worker/backpressure knob parsers (#2098) ------------------


def test_parse_int_defaults_and_bounds(monkeypatch):
    assert _parse_int("CTF_TEST_UNSET_INT", 5, 1, 10) == 5  # default when unset
    monkeypatch.setenv("CTF_TEST_INT", "7")
    assert _parse_int("CTF_TEST_INT", 5, 1, 10) == 7


@pytest.mark.parametrize("raw", ["0", "99", "-3", "notint"])
def test_parse_int_rejects_out_of_range_or_nonnumeric(raw, monkeypatch):
    monkeypatch.setenv("CTF_TEST_INT", raw)
    with pytest.raises(ImproperlyConfigured):
        _parse_int("CTF_TEST_INT", 5, 1, 10)


def test_parse_float_defaults_and_bounds(monkeypatch):
    assert _parse_float("CTF_TEST_UNSET_FLOAT", 0.25, 0.0, 1.0) == 0.25
    monkeypatch.setenv("CTF_TEST_FLOAT", "0.5")
    assert _parse_float("CTF_TEST_FLOAT", 0.25, 0.0, 1.0) == 0.5


@pytest.mark.parametrize("raw", ["2.0", "-0.1", "notfloat"])
def test_parse_float_rejects_out_of_range_or_nonnumeric(raw, monkeypatch):
    monkeypatch.setenv("CTF_TEST_FLOAT", raw)
    with pytest.raises(ImproperlyConfigured):
        _parse_float("CTF_TEST_FLOAT", 0.25, 0.0, 1.0)


def test_parse_metrics_namespace_valid_and_invalid():
    assert _parse_metrics_namespace("Shifter/CtfCommunication") == "Shifter/CtfCommunication"
    for bad in ("", "bad namespace", "/leading", "trailing/", "has space/x"):
        with pytest.raises(ImproperlyConfigured):
            _parse_metrics_namespace(bad)
