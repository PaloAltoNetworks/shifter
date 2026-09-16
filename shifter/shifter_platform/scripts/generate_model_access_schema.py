"""Generate the installation-facing schema from canonical model-access DTOs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

REPO_SHIFTER_ROOT = PLATFORM_ROOT.parent
OUTPUT = REPO_SHIFTER_ROOT / "installation/published_contract/model-access-policy.v1.schema.json"


def rendered_schema() -> str:
    """Operation for rendered schema."""
    from shared.model_access import model_access_catalog_schema

    return json.dumps(model_access_catalog_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    """Operation for main."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_schema()
    if args.check:
        return 0 if OUTPUT.is_file() and OUTPUT.read_text(encoding="utf-8") == rendered else 1
    OUTPUT.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
