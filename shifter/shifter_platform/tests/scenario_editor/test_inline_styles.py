"""Structural gate: scenario editor templates must not use inline styles.

Inline ``style="..."`` attributes and ``<style>`` blocks are migrated to static
CSS files loaded via ``{% static %}`` (issue #414). Scanning the whole directory
(rather than a hardcoded list) keeps newly-added templates covered automatically.
"""

from pathlib import Path

import pytest

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "scenario_editor"

TEMPLATES = sorted(TEMPLATE_DIR.rglob("*.html"))


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


def test_base_links_extracted_stylesheet():
    content = (TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
    assert "css/scenario-editor-base.css" in content, (
        "base.html must link the extracted scenario-editor-base.css stylesheet"
    )
