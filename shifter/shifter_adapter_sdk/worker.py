"""Entrypoint for an isolated plugin image, never imported by the portal."""

from __future__ import annotations

import contextlib
import importlib.metadata
import json
import os
import re
import sys

from .runtime import (
    ENTRY_POINT_GROUP,
    InspectionInput,
    InspectionResult,
    PluginManifest,
    RuntimeInput,
    RuntimePlan,
    parse_input,
)


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _load_plugin(selection: PluginManifest) -> object:
    candidates = [
        entry
        for entry in importlib.metadata.entry_points().select(group=ENTRY_POINT_GROUP)
        if entry.dist is not None
        and _normalize(entry.dist.name) == _normalize(selection.distribution)
        and entry.dist.version == selection.version
        and entry.name == selection.entry_point
    ]
    if len(candidates) != 1:
        raise ValueError("installed selection is unavailable or ambiguous")
    plugin = candidates[0].load()()
    if not callable(getattr(plugin, "plan", None)):
        raise ValueError("installed plugin does not implement planning")
    return plugin


def plan_invocation(request: RuntimeInput) -> RuntimePlan:
    """Load one exact installed distribution; all exceptions become bounded failures."""
    original = RuntimeInput.model_validate_json(request.model_dump_json())
    try:
        plugin = _load_plugin(request.manifest)
        result = RuntimePlan.model_validate(plugin.plan(request))
        result.authorize(original)
        return result
    except Exception:
        return RuntimePlan(
            protocol=original.protocol,
            invocation_id=original.invocation_id,
            input_digest=original.digest,
            phase=original.phase,
            status="failed",
            failure_code="planning-failed",
        )


def inspect_invocation(request: InspectionInput) -> InspectionResult:
    """Import and instantiate the exact package only inside the isolated worker."""
    digest = request.digest
    try:
        _load_plugin(request.manifest)
        status = "compatible"
    except Exception:
        status = "failed"
    return InspectionResult(
        protocol=request.protocol,
        invocation_id=request.invocation_id,
        input_digest=digest,
        phase="inspect",
        status=status,
    )


def main() -> int:
    """Read bounded injected input and emit only the versioned plan response."""
    raw = os.environ.pop("SHIFTER_PLUGIN_INPUT", "")
    try:
        request = parse_input(raw)
    except ValueError:
        # Invalid input cannot be safely bound to an invocation. No input values
        # or validation diagnostics are emitted, including Pydantic input echoes.
        sys.stderr.write("invalid plugin input\n")
        return 2
    # A convenience for well-behaved plugins, not an isolation boundary: the
    # host still rejects polluted/malformed output and bounds the log read.
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        result = inspect_invocation(request) if isinstance(request, InspectionInput) else plan_invocation(request)
    sys.stdout.write(json.dumps(result.model_dump(mode="json"), separators=(",", ":")) + "\n")
    return 1 if result.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
