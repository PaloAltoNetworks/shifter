"""Private, persistent plan evidence and value-free summaries for both GCP stacks."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from inventory_bootstrap import invalid, write_private


def create_plan_directory(path: Path) -> Path:
    """Require a new operator-selected directory; never overwrite prior evidence."""
    try:
        path.mkdir(mode=0o700)
    except OSError:
        raise invalid("plan output must be a new directory under an existing private location") from None
    return path.resolve()


def publish_plan(stack: str, plan: dict[str, Any], binary: Path, destination: Path) -> dict[str, Any]:
    """Persist full private evidence; print only addresses, action kinds and counts.

    Called after validation and before apply by both stack adapters. Detailed
    before/after values remain in mode-0600 files, including obsolete principals
    and any sensitive Terraform values. The temporary execution tree may be
    deleted independently of this operator-owned evidence.
    """
    resources = [
        {"address": item.get("address", item.get("type", "unknown")), "actions": item["change"]["actions"]}
        for item in plan.get("resource_changes", [])
    ]
    outputs = [{"name": name, "actions": change["actions"]} for name, change in plan.get("output_changes", {}).items()]
    summary = {
        "has_changes": any(item["actions"] != ["no-op"] for item in resources + outputs),
        "counts": dict(sorted(Counter("/".join(item["actions"]) for item in resources).items())),
        "resources": resources,
        "outputs": outputs,
    }
    payload = binary.read_bytes()
    summary["plan_sha256"] = hashlib.sha256(payload).hexdigest()
    write_private(destination / f"{stack}.plan", payload)
    write_private(destination / f"{stack}.plan.json", json.dumps(plan, sort_keys=True, indent=2))
    write_private(destination / f"{stack}.summary.json", json.dumps(summary, sort_keys=True, indent=2))
    print(json.dumps({"stage": stack, "plan": summary}, sort_keys=True), flush=True)
    return summary
