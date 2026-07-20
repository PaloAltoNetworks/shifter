"""Structural gate: CTF portal templates must not use inline styles.

Inline ``style="..."`` attributes and ``<style>`` blocks are migrated to static
CSS files loaded via ``{% static %}`` (issue #414).

The ``ctf/email/`` templates are intentionally excluded: HTML email bodies must
keep inline CSS for mail-client compatibility (see the issue's architecture
preflight, "separate surfaces").
"""

from pathlib import Path

import pytest

# tests/ctf/ -> shifter_platform/templates/ctf
TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "ctf"
EXCLUDED_DIRS = {"email"}

TEMPLATES = sorted(
    p for p in TEMPLATE_DIR.rglob("*.html") if not (set(p.relative_to(TEMPLATE_DIR).parts) & EXCLUDED_DIRS)
)


def _ids(paths):
    return [str(p.relative_to(TEMPLATE_DIR)) for p in paths]


@pytest.mark.parametrize("template", TEMPLATES, ids=_ids(TEMPLATES))
def test_no_inline_style_attributes(template):
    content = template.read_text(encoding="utf-8")
    assert 'style="' not in content, f"{template.name} still contains inline style= attributes"


@pytest.mark.parametrize("template", TEMPLATES, ids=_ids(TEMPLATES))
def test_no_style_blocks(template):
    content = template.read_text(encoding="utf-8")
    assert "<style" not in content, f"{template.name} still contains a <style> block"
