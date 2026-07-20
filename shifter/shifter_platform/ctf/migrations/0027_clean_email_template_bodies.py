"""Clean legacy organizer email-template bodies (issue #1095).

Custom ``CTFEmailTemplate`` bodies are no longer rendered with the Django
template engine; they are substituted against a flat ``{{ name }}``
placeholder allowlist. Existing rows may use the legacy dotted placeholder
vocabulary (``{{ event.name }}``); this migration rewrites those to their
flat equivalents so historical rows keep rendering their custom content.

Rows containing Django tags or comments (``{% ... %}`` / ``{# ... #}``) are
deliberately left untouched. The safe renderer rejects any body with those
delimiters and falls back to the trusted default template, so the row is
effectively rejected at send time. Stripping the delimiters here would be a
data-exposure regression: text hidden inside ``{% comment %}...{% endcomment %}``
or a false ``{% if %}...{% endif %}`` block (which Django never rendered)
would become ordinary email body content.

The transform is self-contained (no app/service imports) and idempotent.
"""

from __future__ import annotations

import re

from django.db import migrations

# Legacy dotted placeholder -> flat allowlist name. ``|filter`` suffixes
# (e.g. ``{{ event.event_start|date:"..." }}``) are tolerated and dropped.
_LEGACY_RENAMES = {
    "event.name": "event_name",
    "event.description": "event_description",
    "event.event_start": "event_start",
    "event.event_end": "event_end",
    "participant.name": "participant_name",
    "participant.email": "participant_email",
}


def clean_body(body: str) -> str:
    """Rewrite legacy dotted placeholders to flat names.

    Bodies containing template tags/comments are returned unchanged so the
    render-time validator fails them closed to the default template (stripping
    delimiters could expose previously-hidden block content).
    """
    if not body:
        return body
    cleaned = body
    for dotted, flat in _LEGACY_RENAMES.items():
        pattern = re.compile(r"{{\s*" + re.escape(dotted) + r"(?:\|[^}]*)?\s*}}")
        cleaned = pattern.sub("{{ " + flat + " }}", cleaned)
    return cleaned


def _clean_existing_templates(apps, schema_editor):
    model = apps.get_model("ctf", "CTFEmailTemplate")
    for template in model.objects.all().iterator():
        new_html = clean_body(template.html_body)
        new_text = clean_body(template.text_body)
        if new_html != template.html_body or new_text != template.text_body:
            template.html_body = new_html
            template.text_body = new_text
            template.save(update_fields=["html_body", "text_body", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0026_backfill_ctf_leaderboard"),
    ]

    operations = [
        migrations.RunPython(_clean_existing_templates, migrations.RunPython.noop),
    ]
