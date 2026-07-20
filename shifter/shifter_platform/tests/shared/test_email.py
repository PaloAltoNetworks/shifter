"""Tests for shared.email — platform email templating and delivery service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared import email

# ---------------------------------------------------------------------------
# render_template
# ---------------------------------------------------------------------------


class TestRenderTemplate:
    """Tests for render_template()."""

    @patch("django.template.loader.render_to_string")
    def test_renders_html_and_text(self, mock_render):
        """Renders both .html and .txt templates."""
        mock_render.side_effect = ["<html>Hello</html>", "Hello"]

        html, text = email.render_template("ctf/email/invitation", {"key": "val"})

        assert html == "<html>Hello</html>"
        assert text == "Hello"
        assert mock_render.call_count == 2
        mock_render.assert_any_call("ctf/email/invitation.html", {"key": "val"})
        mock_render.assert_any_call("ctf/email/invitation.txt", {"key": "val"})


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------


class TestSendEmail:
    """Tests for send_email()."""

    @patch("django.core.mail.EmailMultiAlternatives")
    def test_send_success(self, mock_cls):
        """Returns True on successful send."""
        mock_msg = MagicMock()
        mock_cls.return_value = mock_msg

        result = email.send_email("a@b.com", "Subject", "<html>", "text")

        assert result is True
        mock_msg.attach_alternative.assert_called_once_with("<html>", "text/html")
        mock_msg.send.assert_called_once()

    @patch("django.core.mail.EmailMultiAlternatives")
    def test_send_failure_returns_false(self, mock_cls):
        """Returns False and logs on failure without raising."""
        mock_msg = MagicMock()
        mock_msg.send.side_effect = RuntimeError("SMTP down")
        mock_cls.return_value = mock_msg

        result = email.send_email("a@b.com", "Subject", "<html>", "text")

        assert result is False


# ---------------------------------------------------------------------------
# send_email_async
# ---------------------------------------------------------------------------


class TestSendEmailAsync:
    """Tests for send_email_async()."""

    def test_dispatches_to_thread_and_delivers(self, mailoutbox):
        """Submits the real send_email to the thread pool; the message lands.

        Drives the real ``send_email`` (no first-party patch) so the locmem
        email backend records the delivery — asserting the effect rather than
        that ``send_email`` was called.
        """
        # Fire-and-forget: returns None immediately.
        assert email.send_email_async("a@b.com", "Sub", "<h>", "t") is None

        # Flush the background thread so the send completes before asserting.
        email._get_executor().shutdown(wait=True)
        # Re-create the module-level executor for other tests.
        email._executor = None

        assert len(mailoutbox) == 1
        message = mailoutbox[0]
        assert message.to == ["a@b.com"]
        assert message.subject == "Sub"
        assert message.body == "t"
        assert message.alternatives == [("<h>", "text/html")]
