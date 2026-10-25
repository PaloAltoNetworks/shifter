"""Guacamole display synchronization protocol tests (#1816)."""

from __future__ import annotations

import pytest

from range_functional_smoke.guacamole import (
    GuacamoleInstructionParser,
    GuacamoleProtocolError,
    encode_instruction,
)


def test_parser_handles_fragmented_length_prefixed_instructions():
    parser = GuacamoleInstructionParser(max_buffer_bytes=128)

    assert parser.feed("5.rea") == []
    instructions = parser.feed("dy,3.abc;4.sync,3.123;")

    assert [(item.opcode, item.args) for item in instructions] == [
        ("ready", ("abc",)),
        ("sync", ("123",)),
    ]
    assert encode_instruction("sync", "123") == "4.sync,3.123;"


def test_parser_rejects_malformed_or_unbounded_streams():
    parser = GuacamoleInstructionParser(max_buffer_bytes=12)
    with pytest.raises(GuacamoleProtocolError):
        parser.feed("not-length-prefixed;")

    parser = GuacamoleInstructionParser(max_buffer_bytes=8)
    with pytest.raises(GuacamoleProtocolError, match="buffer limit"):
        parser.feed("9.abcdefghi")


def test_parser_allows_a_large_batch_of_individually_bounded_instructions():
    parser = GuacamoleInstructionParser(max_buffer_bytes=8)

    instructions = parser.feed("1.a;1.b;1.c;")

    assert [item.opcode for item in instructions] == ["a", "b", "c"]


def test_parser_rejects_an_element_declared_larger_than_the_bound():
    parser = GuacamoleInstructionParser(max_buffer_bytes=8)

    with pytest.raises(GuacamoleProtocolError, match="buffer limit"):
        parser.feed("9.")


def test_parser_rejects_non_ascii_digit_prefix_with_protocol_error():
    parser = GuacamoleInstructionParser(max_buffer_bytes=32)

    with pytest.raises(GuacamoleProtocolError, match="element length"):
        parser.feed("².foo;")


def test_parser_bounds_an_undelimited_slow_drip_length_prefix():
    parser = GuacamoleInstructionParser(max_buffer_bytes=8)

    assert parser.feed("1111") == []
    assert parser.feed("1111") == []
    with pytest.raises(GuacamoleProtocolError, match="buffer limit"):
        parser.feed("1")
