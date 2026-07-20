"""Structural gate: standalone + partial portal templates must not use inline styles.

Covers the top-level standalone pages (coming soon, dev login, identity platform
login/logout) and shared partials. Inline ``style="..."`` attributes and
``<style>`` blocks are migrated to static CSS loaded via ``{% static %}`` (#414).
"""

from pathlib import Path

import pytest

# tests/ -> shifter_platform/templates
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates"

TEMPLATES = sorted(list(TEMPLATE_ROOT.glob("*.html")) + list((TEMPLATE_ROOT / "partials").glob("*.html")))


def _ids(paths):
    return [str(p.relative_to(TEMPLATE_ROOT)) for p in paths]


@pytest.mark.parametrize("template", TEMPLATES, ids=_ids(TEMPLATES))
def test_no_inline_style_attributes(template):
    content = template.read_text(encoding="utf-8")
    assert 'style="' not in content, f"{template.name} still contains inline style= attributes"


@pytest.mark.parametrize("template", TEMPLATES, ids=_ids(TEMPLATES))
def test_no_style_blocks(template):
    content = template.read_text(encoding="utf-8")
    assert "<style" not in content, f"{template.name} still contains a <style> block"
