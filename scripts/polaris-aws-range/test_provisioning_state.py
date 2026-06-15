"""Tests for the extracted provisioning-state data model (issue #691).

Run from this directory:
    python3 -m unittest test_provisioning_state -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from provisioning_state import (
    ParticipantOutcome,
    State,
    load_state,
    now_iso,
    save_state,
    write_status_doc,
)


class StateRoundTripTests(unittest.TestCase):
    def test_to_dict_and_from_dict_preserve_outcomes(self) -> None:
        state = State(
            started_at="2026-05-23T00:00:00+00:00",
            finished_at="",
            total_participants=2,
            batches_completed=1,
            halted=False,
            halt_reason="",
            outcomes={
                "p1": ParticipantOutcome(
                    participant_id="p1",
                    email="a@example.com",
                    name="Alice",
                    range_instance_id="r-1",
                    status="ready",
                    batch_num=1,
                    started_at="2026-05-23T00:00:01+00:00",
                    finished_at="2026-05-23T00:05:00+00:00",
                ),
                "p2": ParticipantOutcome(
                    participant_id="p2",
                    email="b@example.com",
                    name="Bob",
                    status="failed",
                    error="boom",
                    batch_num=1,
                ),
            },
        )

        round_tripped = State.from_dict(state.to_dict())

        self.assertEqual(round_tripped.batches_completed, 1)
        self.assertEqual(round_tripped.outcomes["p1"].status, "ready")
        self.assertEqual(round_tripped.outcomes["p1"].range_instance_id, "r-1")
        self.assertEqual(round_tripped.outcomes["p2"].error, "boom")
        self.assertEqual(round_tripped.outcomes["p2"].finished_at, "")

    def test_save_state_and_load_state_round_trip_through_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state = State(started_at=now_iso(), total_participants=3)
            state.outcomes["pX"] = ParticipantOutcome(
                participant_id="pX",
                email="x@example.com",
                name="X",
                status="triggered",
            )

            save_state(state, state_path)
            loaded = load_state(state_path)

            self.assertEqual(loaded.total_participants, 3)
            self.assertIn("pX", loaded.outcomes)
            self.assertEqual(loaded.outcomes["pX"].status, "triggered")

    def test_load_state_returns_fresh_state_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "absent.json"

            loaded = load_state(state_path)

            self.assertTrue(loaded.started_at)
            self.assertEqual(loaded.outcomes, {})

    def test_load_state_returns_fresh_state_on_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "corrupt.json"
            state_path.write_text("{not json")

            loaded = load_state(state_path)

            self.assertTrue(loaded.started_at)
            self.assertEqual(loaded.outcomes, {})


class WriteStatusDocTests(unittest.TestCase):
    def test_renders_header_tallies_and_failure_table(self) -> None:
        state = State(
            started_at="2026-05-23T00:00:00+00:00",
            finished_at="2026-05-23T00:30:00+00:00",
            batches_completed=2,
            outcomes={
                "p1": ParticipantOutcome(
                    participant_id="p1", email="a@x", name="A", status="ready", batch_num=1
                ),
                "p2": ParticipantOutcome(
                    participant_id="p2",
                    email="b@x",
                    name="B",
                    status="failed",
                    error="boom",
                    batch_num=1,
                ),
                "p3": ParticipantOutcome(
                    participant_id="p3",
                    email="c@x",
                    name="C",
                    status="trigger_error",
                    error="bad|pipe",
                    batch_num=2,
                ),
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.md"
            write_status_doc(state, current_batch_log=["did the thing"], status_md_path=status_path)
            rendered = status_path.read_text()

        self.assertIn("# Polaris provisioning status", rendered)
        self.assertIn("- started: 2026-05-23T00:00:00+00:00", rendered)
        self.assertIn("- finished: 2026-05-23T00:30:00+00:00", rendered)
        self.assertIn("- batches completed: 2", rendered)
        self.assertIn("## Outcome tally", rendered)
        self.assertIn("## Failures", rendered)
        # Pipes in error fields must be escaped (markdown table cell discipline).
        self.assertIn(r"bad\|pipe", rendered)
        self.assertIn("## Current / last batch log", rendered)
        self.assertIn("- did the thing", rendered)

    def test_renders_halted_marker_when_state_is_halted(self) -> None:
        state = State(
            started_at="2026-05-23T00:00:00+00:00",
            halted=True,
            halt_reason="threshold exceeded",
        )

        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.md"
            write_status_doc(state, current_batch_log=[], status_md_path=status_path)
            rendered = status_path.read_text()

        self.assertIn("**HALTED**: threshold exceeded", rendered)

    def test_save_state_writes_pretty_json(self) -> None:
        state = State(started_at="2026-05-23T00:00:00+00:00")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            save_state(state, path)
            payload = json.loads(path.read_text())
        self.assertEqual(payload["started_at"], "2026-05-23T00:00:00+00:00")
        self.assertIn("outcomes", payload)


if __name__ == "__main__":
    unittest.main()
