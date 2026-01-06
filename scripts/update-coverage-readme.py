#!/usr/bin/env python3
"""Update README.md with coverage percentages from coverage.xml files."""

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Coverage file locations relative to repo root
COVERAGE_FILES = {
    "shifter_platform": "shifter/shifter_platform/coverage.xml",
    "provisioner": "shifter/engine/provisioner/coverage.xml",
    "packer": "shifter/packer/coverage.xml",
    "bootstrap": "scripts/bootstrap/coverage.xml",
    "check_layer_imports": "scripts/check_layer_imports/coverage.xml",
}

README_PATH = "README.md"

# Markers in README for coverage table
START_MARKER = "<!-- COVERAGE-TABLE-START -->"
END_MARKER = "<!-- COVERAGE-TABLE-END -->"


def get_coverage_percent(xml_path: Path) -> str | None:
    """Extract line coverage percentage from coverage.xml."""
    if not xml_path.exists():
        return None
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        line_rate = float(root.get("line-rate", 0))
        return f"{line_rate * 100:.1f}%"
    except (ET.ParseError, ValueError):
        return None


def get_badge_color(percent_str: str | None) -> str:
    """Return shield.io color based on coverage percentage."""
    if not percent_str:
        return "lightgrey"
    try:
        pct = float(percent_str.rstrip("%"))
        if pct >= 80:
            return "brightgreen"
        if pct >= 60:
            return "yellow"
        if pct >= 40:
            return "orange"
        return "red"
    except ValueError:
        return "lightgrey"


def generate_coverage_table(repo_root: Path) -> str:
    """Generate markdown coverage table."""
    lines = [
        "| Component | Coverage |",
        "|-----------|----------|",
    ]

    for name, rel_path in COVERAGE_FILES.items():
        xml_path = repo_root / rel_path
        coverage = get_coverage_percent(xml_path)
        color = get_badge_color(coverage)

        if coverage:
            # Use shields.io badge
            badge = f"![{coverage}](https://img.shields.io/badge/coverage-{coverage.replace('%', '%25')}-{color})"
        else:
            badge = "![N/A](https://img.shields.io/badge/coverage-N%2FA-lightgrey)"

        lines.append(f"| {name} | {badge} |")

    return "\n".join(lines)


def update_readme(repo_root: Path) -> bool:
    """Update README.md with coverage table. Returns True if changed."""
    readme_path = repo_root / README_PATH
    if not readme_path.exists():
        print(f"README not found: {readme_path}", file=sys.stderr)
        return False

    content = readme_path.read_text()

    # Check for markers
    if START_MARKER not in content or END_MARKER not in content:
        print(
            f"Coverage markers not found in README. Add these markers:\n"
            f"  {START_MARKER}\n  {END_MARKER}",
            file=sys.stderr,
        )
        return False

    # Generate new table
    table = generate_coverage_table(repo_root)

    # Replace content between markers
    pattern = re.compile(
        rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}",
        re.DOTALL,
    )
    new_content = pattern.sub(
        f"{START_MARKER}\n{table}\n{END_MARKER}",
        content,
    )

    if new_content == content:
        return False

    readme_path.write_text(new_content)
    print(f"Updated {README_PATH} with coverage data")
    return True


def main() -> int:
    """Main entry point."""
    # Find repo root (where README.md is)
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent

    if not (repo_root / README_PATH).exists():
        print(f"Cannot find {README_PATH} in {repo_root}", file=sys.stderr)
        return 1

    changed = update_readme(repo_root)

    # Return 0 even if changed - pre-commit will detect modified file
    return 0


if __name__ == "__main__":
    sys.exit(main())
