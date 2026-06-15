"""Polaris provisioning state data model and IO (issue #691).

Extracted from ``orchestrate_provisioning.py`` so the orchestrator
entrypoint stays a thin CLI wrapper and the persisted-state contract has a
single owner.

The state lives in two artifacts:

- ``provisioning_state.json`` — machine-readable; resumable across runs.
- ``provisioning_status.md`` — human-readable running log written every
  time an outcome flips.

Both paths are caller-provided so callers can keep their current
script-local defaults without this module hard-coding them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    """ISO-8601 UTC timestamp matching the existing operator-script format."""
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ParticipantOutcome:
    """Per-participant tracking record for one provisioning batch."""

    participant_id: str
    email: str
    name: str
    range_instance_id: str | None = None
    status: str = "pending"  # pending|triggered|ready|failed|trigger_error|retrying
    error: str | None = None
    batch_num: int = 0
    started_at: str = ""
    finished_at: str = ""


@dataclass
class State:
    """Aggregate provisioning state across all batches."""

    started_at: str = ""
    finished_at: str = ""
    total_participants: int = 0
    batches_completed: int = 0
    outcomes: dict[str, ParticipantOutcome] = field(default_factory=dict)
    halted: bool = False
    halt_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_participants": self.total_participants,
            "batches_completed": self.batches_completed,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "outcomes": {pid: vars(o) for pid, o in self.outcomes.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "State":
        s = cls(
            started_at=d.get("started_at", ""),
            finished_at=d.get("finished_at", ""),
            total_participants=d.get("total_participants", 0),
            batches_completed=d.get("batches_completed", 0),
            halted=d.get("halted", False),
            halt_reason=d.get("halt_reason", ""),
        )
        for pid, raw in (d.get("outcomes") or {}).items():
            s.outcomes[pid] = ParticipantOutcome(**raw)
        return s


def save_state(state: State, path: Path) -> None:
    path.write_text(json.dumps(state.to_dict(), indent=2))


def load_state(path: Path) -> State:
    if path.exists():
        try:
            return State.from_dict(json.loads(path.read_text()))
        except Exception:
            # Corrupt or partially-written state — treat as fresh so the
            # caller's run can recover. The DB is authoritative for what's
            # already provisioned; the json is diagnostic.
            pass
    return State(started_at=now_iso())


def write_status_doc(
    state: State,
    current_batch_log: list[str],
    *,
    status_md_path: Path,
) -> None:
    """Render a markdown summary of ``state`` to ``status_md_path``.

    Failure rows escape ``|`` characters so the markdown table renders even
    when an exception message contains pipes.
    """
    lines: list[str] = []
    lines.append("# Polaris provisioning status")
    lines.append("")
    lines.append(f"- started: {state.started_at}")
    if state.finished_at:
        lines.append(f"- finished: {state.finished_at}")
    lines.append(f"- batches completed: {state.batches_completed}")
    lines.append(f"- participants tracked: {len(state.outcomes)}")
    if state.halted:
        lines.append(f"- **HALTED**: {state.halt_reason}")

    by_status: dict[str, int] = {}
    for o in state.outcomes.values():
        by_status[o.status] = by_status.get(o.status, 0) + 1
    if by_status:
        lines.append("")
        lines.append("## Outcome tally")
        for k, v in sorted(by_status.items()):
            lines.append(f"- {k}: {v}")

    failures = [o for o in state.outcomes.values() if o.status in ("failed", "trigger_error")]
    if failures:
        lines.append("")
        lines.append("## Failures")
        lines.append("| batch | email | status | error |")
        lines.append("|---|---|---|---|")
        pipe = r"\|"
        for o in sorted(failures, key=lambda x: (x.batch_num, x.email)):
            err_cell = (o.error or "")[:200].replace("|", pipe)
            lines.append(f"| {o.batch_num} | {o.email} | {o.status} | {err_cell} |")

    if current_batch_log:
        lines.append("")
        lines.append("## Current / last batch log")
        lines.extend("- " + x for x in current_batch_log)

    status_md_path.write_text("\n".join(lines) + "\n")


__all__ = [
    "ParticipantOutcome",
    "State",
    "load_state",
    "now_iso",
    "save_state",
    "write_status_doc",
]
