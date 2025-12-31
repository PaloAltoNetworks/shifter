"""Tests for NGFW CLI commands - TDD: Write tests first, all must fail initially.

Tests the CLI entry points for NGFW lifecycle operations.
"""

import argparse
from unittest.mock import MagicMock, patch

import pytest


class TestNGFWCLIParser:
    """Test NGFW CLI argument parsing."""

    def test_ngfw_subcommand_exists(self):
        """CLI should have ngfw subcommand."""
        from ngfw_cli import create_ngfw_parser

        parser = create_ngfw_parser()
        assert parser is not None

    def test_ngfw_provision_command(self):
        """CLI should parse ngfw provision command."""
        from ngfw_cli import create_ngfw_parser

        parser = create_ngfw_parser()
        args = parser.parse_args(["provision", "--user-ngfw-id", "123"])

        assert args.operation == "provision"
        assert args.user_ngfw_id == 123

    def test_ngfw_start_command(self):
        """CLI should parse ngfw start command."""
        from ngfw_cli import create_ngfw_parser

        parser = create_ngfw_parser()
        args = parser.parse_args(["start", "--user-ngfw-id", "123"])

        assert args.operation == "start"
        assert args.user_ngfw_id == 123

    def test_ngfw_stop_command(self):
        """CLI should parse ngfw stop command."""
        from ngfw_cli import create_ngfw_parser

        parser = create_ngfw_parser()
        args = parser.parse_args(["stop", "--user-ngfw-id", "123"])

        assert args.operation == "stop"
        assert args.user_ngfw_id == 123

    def test_ngfw_deprovision_command(self):
        """CLI should parse ngfw deprovision command."""
        from ngfw_cli import create_ngfw_parser

        parser = create_ngfw_parser()
        args = parser.parse_args(["deprovision", "--user-ngfw-id", "123"])

        assert args.operation == "deprovision"
        assert args.user_ngfw_id == 123

    def test_ngfw_add_route_command(self):
        """CLI should parse ngfw add-route command."""
        from ngfw_cli import create_ngfw_parser

        parser = create_ngfw_parser()
        args = parser.parse_args(["add-route", "--user-ngfw-id", "123", "--subnet-id", "subnet-abc"])

        assert args.operation == "add-route"
        assert args.user_ngfw_id == 123
        assert args.subnet_id == "subnet-abc"

    def test_ngfw_remove_route_command(self):
        """CLI should parse ngfw remove-route command."""
        from ngfw_cli import create_ngfw_parser

        parser = create_ngfw_parser()
        args = parser.parse_args(["remove-route", "--user-ngfw-id", "123", "--endpoint-id", "vpce-xyz"])

        assert args.operation == "remove-route"
        assert args.user_ngfw_id == 123
        assert args.endpoint_id == "vpce-xyz"


class TestNGFWCLIDispatch:
    """Test NGFW CLI operation dispatch."""

    def test_dispatch_provision(self):
        """dispatch_operation should call provision handler."""
        from ngfw_cli import dispatch_operation

        with patch("ngfw_cli.handle_provision") as mock_handler:
            dispatch_operation("provision", user_ngfw_id=123)
            mock_handler.assert_called_once_with(user_ngfw_id=123)

    def test_dispatch_start(self):
        """dispatch_operation should call start handler."""
        from ngfw_cli import dispatch_operation

        with patch("ngfw_cli.handle_start") as mock_handler:
            dispatch_operation("start", user_ngfw_id=123)
            mock_handler.assert_called_once_with(user_ngfw_id=123)

    def test_dispatch_stop(self):
        """dispatch_operation should call stop handler."""
        from ngfw_cli import dispatch_operation

        with patch("ngfw_cli.handle_stop") as mock_handler:
            dispatch_operation("stop", user_ngfw_id=123)
            mock_handler.assert_called_once_with(user_ngfw_id=123)

    def test_dispatch_deprovision(self):
        """dispatch_operation should call deprovision handler."""
        from ngfw_cli import dispatch_operation

        with patch("ngfw_cli.handle_deprovision") as mock_handler:
            dispatch_operation("deprovision", user_ngfw_id=123)
            mock_handler.assert_called_once_with(user_ngfw_id=123)

    def test_dispatch_add_route(self):
        """dispatch_operation should call add_route handler."""
        from ngfw_cli import dispatch_operation

        with patch("ngfw_cli.handle_add_route") as mock_handler:
            dispatch_operation("add-route", user_ngfw_id=123, subnet_id="subnet-abc")
            mock_handler.assert_called_once_with(user_ngfw_id=123, subnet_id="subnet-abc")

    def test_dispatch_remove_route(self):
        """dispatch_operation should call remove_route handler."""
        from ngfw_cli import dispatch_operation

        with patch("ngfw_cli.handle_remove_route") as mock_handler:
            dispatch_operation("remove-route", user_ngfw_id=123, endpoint_id="vpce-xyz")
            mock_handler.assert_called_once_with(user_ngfw_id=123, endpoint_id="vpce-xyz")

    def test_dispatch_unknown_raises(self):
        """dispatch_operation should raise for unknown operation."""
        from ngfw_cli import dispatch_operation

        with pytest.raises(ValueError, match="Unknown operation"):
            dispatch_operation("invalid", user_ngfw_id=123)


class TestNGFWCLIHandlers:
    """Test NGFW CLI handler functions exist."""

    def test_handle_provision_exists(self):
        """handle_provision function should exist."""
        from ngfw_cli import handle_provision

        assert callable(handle_provision)

    def test_handle_start_exists(self):
        """handle_start function should exist."""
        from ngfw_cli import handle_start

        assert callable(handle_start)

    def test_handle_stop_exists(self):
        """handle_stop function should exist."""
        from ngfw_cli import handle_stop

        assert callable(handle_stop)

    def test_handle_deprovision_exists(self):
        """handle_deprovision function should exist."""
        from ngfw_cli import handle_deprovision

        assert callable(handle_deprovision)

    def test_handle_add_route_exists(self):
        """handle_add_route function should exist."""
        from ngfw_cli import handle_add_route

        assert callable(handle_add_route)

    def test_handle_remove_route_exists(self):
        """handle_remove_route function should exist."""
        from ngfw_cli import handle_remove_route

        assert callable(handle_remove_route)
