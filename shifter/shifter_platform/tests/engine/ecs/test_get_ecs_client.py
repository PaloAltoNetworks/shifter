"""Tests for _get_ecs_client() function."""

import logging
from unittest.mock import MagicMock, patch

import pytest


class TestGetEcsClient:
    """Tests for _get_ecs_client() internal function.

    Contract:
    - Inputs: None
    - Outputs: boto3 ECS client configured for AWS_REGION
    - Side effects: None
    - Errors: Propagates boto3 exceptions
    - Logging: DEBUG on success, ERROR on failure
    """

    # -------------------------------------------------------------------------
    # Happy path - function succeeds
    # -------------------------------------------------------------------------

    def test_returns_ecs_client(self, settings):
        """Function returns a boto3 ECS client."""
        from botocore.client import BaseClient

        from engine.ecs import _get_ecs_client

        settings.AWS_REGION = "us-east-2"

        with patch("engine.ecs.boto3.client") as mock_client:
            mock_ecs = MagicMock(spec=BaseClient)
            mock_client.return_value = mock_ecs

            result = _get_ecs_client()

            assert isinstance(result, BaseClient)

    def test_creates_client_with_correct_region(self, settings):
        """Function creates client with AWS_REGION from settings."""
        from botocore.client import BaseClient

        from engine.ecs import _get_ecs_client

        settings.AWS_REGION = "us-west-2"

        with patch("engine.ecs.boto3.client") as mock_client:
            mock_client.return_value = MagicMock(spec=BaseClient)
            _get_ecs_client()

            mock_client.assert_called_once_with("ecs", region_name="us-west-2")

    # -------------------------------------------------------------------------
    # Response validation - boto3 returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_boto3_returns_none(self, settings):
        """Function raises TypeError if boto3 returns None."""
        from engine.ecs import _get_ecs_client

        settings.AWS_REGION = "us-east-2"

        with (
            patch("engine.ecs.boto3.client", return_value=None),
            pytest.raises(TypeError),
        ):
            _get_ecs_client()

    def test_raises_on_boto3_returns_string(self, settings):
        """Function raises TypeError if boto3 returns string."""
        from engine.ecs import _get_ecs_client

        settings.AWS_REGION = "us-east-2"

        with (
            patch("engine.ecs.boto3.client", return_value="not a client"),
            pytest.raises(TypeError),
        ):
            _get_ecs_client()

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_debug_on_success(self, settings, caplog):
        """Function logs DEBUG when client created successfully."""
        from botocore.client import BaseClient

        from engine.ecs import _get_ecs_client

        settings.AWS_REGION = "us-east-2"

        with (
            patch("engine.ecs.boto3.client") as mock_client,
            caplog.at_level(logging.DEBUG, logger="engine.ecs"),
        ):
            mock_client.return_value = MagicMock(spec=BaseClient)
            _get_ecs_client()

        assert "us-east-2" in caplog.text

    def test_logs_error_on_failure(self, settings, caplog):
        """Function logs ERROR when boto3 raises exception."""
        from engine.ecs import _get_ecs_client

        settings.AWS_REGION = "us-east-2"

        with (
            patch(
                "engine.ecs.boto3.client",
                side_effect=RuntimeError("AWS credentials not found"),
            ),
            caplog.at_level(logging.ERROR, logger="engine.ecs"),
            pytest.raises(RuntimeError),
        ):
            _get_ecs_client()

        assert "error" in caplog.text.lower() or "failed" in caplog.text.lower()

    def test_logs_error_on_invalid_response(self, settings, caplog):
        """Function logs ERROR when boto3 returns invalid response."""
        from engine.ecs import _get_ecs_client

        settings.AWS_REGION = "us-east-2"

        with (
            patch("engine.ecs.boto3.client", return_value=None),
            caplog.at_level(logging.ERROR, logger="engine.ecs"),
            pytest.raises(TypeError),
        ):
            _get_ecs_client()

        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()
