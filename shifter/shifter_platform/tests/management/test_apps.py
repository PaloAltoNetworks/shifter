"""Management app configuration tests."""

import logging
from unittest.mock import patch

import pytest

from management.apps import ManagementConfig


class TestManagementConfigReady:
    """Tests for ManagementConfig.ready signal registration."""

    def test_registers_on_user_created_handler(self):
        """ready() registers post_save handler for user creation."""
        app_config = ManagementConfig("management", __import__("management"))

        with patch("management.apps.post_save") as mock_post_save:
            app_config.ready()

        calls = list(mock_post_save.connect.call_args_list)
        assert any(c.kwargs.get("dispatch_uid") == "management_create_user_profile" for c in calls)

    def test_registers_on_user_saved_handler(self):
        """ready() registers post_save handler for user save."""
        app_config = ManagementConfig("management", __import__("management"))

        with patch("management.apps.post_save") as mock_post_save:
            app_config.ready()

        calls = list(mock_post_save.connect.call_args_list)
        assert any(c.kwargs.get("dispatch_uid") == "management_save_user_profile" for c in calls)

    def test_registers_with_auth_user_model_sender(self):
        """ready() registers handlers with AUTH_USER_MODEL as sender."""
        app_config = ManagementConfig("management", __import__("management"))

        with (
            patch("management.apps.post_save") as mock_post_save,
            patch("management.apps.settings") as mock_settings,
        ):
            mock_settings.AUTH_USER_MODEL = "auth.User"
            app_config.ready()

        for call in mock_post_save.connect.call_args_list:
            assert call.kwargs.get("sender") == "auth.User"

    def test_logs_debug_on_successful_registration(self, caplog):
        """ready() logs debug when handlers registered successfully."""
        app_config = ManagementConfig("management", __import__("management"))

        with (
            caplog.at_level(logging.DEBUG, logger="management.apps"),
            patch("management.apps.post_save"),
        ):
            app_config.ready()

        assert "register" in caplog.text.lower()

    def test_logs_errors(self, caplog):
        """ready() logs any exception as error."""
        app_config = ManagementConfig("management", __import__("management"))

        with (
            caplog.at_level(logging.ERROR, logger="management.apps"),
            patch("management.apps.post_save") as mock_post_save,
        ):
            mock_post_save.connect.side_effect = RuntimeError()

            with pytest.raises(RuntimeError):
                app_config.ready()

        assert caplog.text

    def test_propagates_errors(self):
        """ready() propagates any exception."""
        app_config = ManagementConfig("management", __import__("management"))

        with patch("management.apps.post_save") as mock_post_save:
            mock_post_save.connect.side_effect = RuntimeError()

            with pytest.raises(RuntimeError):
                app_config.ready()
