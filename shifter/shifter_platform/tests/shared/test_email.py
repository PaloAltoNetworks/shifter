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

    @patch("shared.email.send_email")
    def test_dispatches_to_thread(self, mock_send):
        """Submits email to thread pool and returns immediately."""
        mock_send.return_value = True

        # Should not raise and should return None (fire-and-forget)
        email.send_email_async("a@b.com", "Sub", "<h>", "t")

        # Wait for the thread pool to finish
        email._get_executor().shutdown(wait=True)

        # Re-create executor for other tests
        email._executor = None

        mock_send.assert_called_once_with("a@b.com", "Sub", "<h>", "t")
