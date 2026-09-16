"""The terminal check's correctness hinges on not matching its own echo."""

from __future__ import annotations

import json

import pytest

from range_functional_smoke import terminal


@pytest.fixture
def nonce() -> str:
    return "0123456789abcdef"


def _output(data: str) -> str:
    return json.dumps({"type": "output", "data": data})


class TestEchoHazard:
    """A shell echoes typed input before running it; that must never pass."""

    def test_echoed_command_alone_does_not_satisfy_the_check(self, nonce):
        # Exactly what an interactive shell sends back as the user "types":
        # the command line, verbatim, including the quote break.
        echoed = terminal.input_command(nonce)
        assert nonce in echoed, "sanity: the raw nonce really is present in the echo"
        assert not terminal.nonce_observed(echoed, nonce), (
            "the echoed input must not satisfy the exchange - matching it would report success "
            "against a shell that never executed anything"
        )

    def test_shell_output_satisfies_the_check(self, nonce):
        # What the guest prints once it actually runs the command: the two
        # string literals are concatenated by the shell.
        assert terminal.nonce_observed(terminal.joined_token(nonce), nonce)

    def test_full_session_transcript_passes_only_after_execution(self, nonce):
        transcript = f"user@kali:~$ {terminal.input_command(nonce)}"
        assert not terminal.nonce_observed(transcript, nonce)
        transcript += f"{terminal.joined_token(nonce)}\nuser@kali:~$ "
        assert terminal.nonce_observed(transcript, nonce)


class TestOutputHandling:
    def test_token_split_across_frames_still_matches(self, nonce):
        token = terminal.joined_token(nonce)
        buffer = ""
        for frame in (_output(token[:5]), _output(token[5:])):
            buffer = terminal.accumulate(buffer, terminal.output_text(frame))
        assert terminal.nonce_observed(buffer, nonce)

    def test_ansi_and_carriage_returns_do_not_hide_the_token(self, nonce):
        token = terminal.joined_token(nonce)
        noisy = f"\x1b[0m\x1b[32m{token[:4]}\x1b[K\r{token[4:]}\x1b[0m"
        assert terminal.nonce_observed(noisy, nonce)

    def test_non_output_frames_contribute_nothing(self, nonce):
        for frame in (json.dumps({"type": "status", "data": terminal.joined_token(nonce)}), "not json", b"\xff\xfe"):
            assert terminal.output_text(frame) == ""

    def test_buffer_stays_bounded_and_keeps_the_tail(self, nonce):
        buffer = terminal.accumulate("", "x" * (terminal.MAX_BUFFER_CHARS * 2))
        assert len(buffer) == terminal.MAX_BUFFER_CHARS
        buffer = terminal.accumulate(buffer, terminal.joined_token(nonce))
        assert len(buffer) == terminal.MAX_BUFFER_CHARS
        assert terminal.nonce_observed(buffer, nonce), "the tail carries the answer and must survive trimming"


class TestFraming:
    def test_input_frame_matches_the_consumer_contract(self, nonce):
        message = json.loads(terminal.input_frame(nonce))
        assert message["type"] == "input"
        assert message["data"].endswith("\n"), "the guest shell needs a newline to execute"

    def test_nonce_is_shell_and_regex_safe(self):
        assert terminal.make_nonce().isalnum()

    def test_ws_url_follows_the_origin_scheme(self):
        assert terminal.terminal_ws_url("https://p.example.com", "abc").startswith("wss://")
        # ws:// only ever follows an http:// origin, which the profile permits
        # solely for loopback behind an explicit opt-in.
        assert terminal.terminal_ws_url("http://localhost:8000", "abc").startswith("ws://")
        assert terminal.terminal_ws_url("https://p.example.com", "abc").endswith("/ws/terminal/abc/")
