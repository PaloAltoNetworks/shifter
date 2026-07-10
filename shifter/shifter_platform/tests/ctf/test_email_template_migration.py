"""Tests for the legacy email-template cleanup migration (issue #1095)."""

from __future__ import annotations

import importlib

_migration = importlib.import_module("ctf.migrations.0027_clean_email_template_bodies")
clean_body = _migration.clean_body


class TestCleanBody:
    def test_rewrites_legacy_dotted_placeholders(self):
        assert clean_body("Hi {{ participant.name }} for {{ event.name }}") == (
            "Hi {{ participant_name }} for {{ event_name }}"
        )

    def test_drops_filters_on_legacy_placeholders(self):
        assert clean_body('{{ event.event_start|date:"F j, Y" }}') == "{{ event_start }}"

    def test_preserves_template_tags_for_render_fallback(self):
        # Tags are NOT stripped: the renderer fails the row closed to the
        # default template. Stripping delimiters could expose hidden block
        # content (e.g. inside {% comment %}...{% endcomment %}).
        body = "{% load i18n %}<p>{{ event.name }}</p>"
        assert clean_body(body) == "{% load i18n %}<p>{{ event_name }}</p>"

    def test_does_not_expose_hidden_comment_block_content(self):
        body = "Visible {% comment %}SECRET{% endcomment %}"
        # The block tags remain, so the safe renderer rejects the body; SECRET
        # is never promoted to renderable email content by this migration.
        cleaned = clean_body(body)
        assert "{% comment %}" in cleaned
        assert "{% endcomment %}" in cleaned

    def test_is_idempotent(self):
        once = clean_body("{% if x %}Hi {{ participant.name }}{% endif %}")
        assert clean_body(once) == once

    def test_leaves_already_flat_bodies_unchanged(self):
        body = "Hi {{ participant_name }}, join {{ event_name }}"
        assert clean_body(body) == body

    def test_handles_empty_body(self):
        assert clean_body("") == ""
