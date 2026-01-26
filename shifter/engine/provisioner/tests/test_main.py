"""Tests for main.py parsing and utility functions.

Only tests for pure logic - no mock-heavy integration tests.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestParseSerialNumber:
    """Tests for parse_serial_number helper function."""

    def test_extracts_serial_from_system_info(self):
        """Extracts serial from PAN-OS show system info output."""
        from main import parse_serial_number

        system_info = """hostname: PA-VM
serial: 007200001267
software-version: 11.1.0
"""
        assert parse_serial_number(system_info) == "007200001267"

    def test_extracts_serial_case_insensitive(self):
        """Handles case variations."""
        from main import parse_serial_number

        assert parse_serial_number("SERIAL: ABC123DEF456") == "ABC123DEF456"

    def test_extracts_serial_with_extra_whitespace(self):
        """Handles extra whitespace."""
        from main import parse_serial_number

        result = parse_serial_number("serial:   007200001267   ")
        assert result == "007200001267"

    def test_returns_none_when_not_found(self):
        """Returns None when serial not in output."""
        from main import parse_serial_number

        result = parse_serial_number("hostname: PA-VM\nsoftware-version: 11.1.0")
        assert result is None

    def test_returns_none_for_unknown_placeholder(self):
        """Returns None for 'unknown' placeholder."""
        from main import parse_serial_number

        assert parse_serial_number("serial: unknown") is None

    def test_returns_none_for_none_placeholder(self):
        """Returns None for 'none' placeholder."""
        from main import parse_serial_number

        assert parse_serial_number("serial: none") is None

    def test_returns_none_for_empty_output(self):
        """Returns None for empty output."""
        from main import parse_serial_number

        assert parse_serial_number("") is None


class TestParseDeviceCertificateStatus:
    """Tests for parse_device_certificate_status helper function."""

    def test_extracts_valid_cert_status(self):
        """Extracts 'Valid' certificate status."""
        from main import parse_device_certificate_status

        system_info = "device-certificate-status: Valid"
        assert parse_device_certificate_status(system_info) == "Valid"

    def test_extracts_cert_status_case_insensitive(self):
        """Handles case variations in field name."""
        from main import parse_device_certificate_status

        result = parse_device_certificate_status("DEVICE-CERTIFICATE-STATUS: Valid")
        assert result == "Valid"

    def test_returns_none_when_not_found(self):
        """Returns None when cert status not in output."""
        from main import parse_device_certificate_status

        assert parse_device_certificate_status("serial: 12345") is None

    def test_returns_none_for_empty_output(self):
        """Returns None for empty output."""
        from main import parse_device_certificate_status

        assert parse_device_certificate_status("") is None


class TestPollForSerialAndCert:
    """Tests for poll_for_serial_and_cert function."""

    def test_returns_serial_when_both_present(self, mocker):
        """Returns serial when both serial and cert are valid."""
        from main import poll_for_serial_and_cert

        mock_ssh = MagicMock()
        mock_ssh.run_command.return_value = MagicMock(stdout="serial: 007200001267\ndevice-certificate-status: Valid")

        serial = poll_for_serial_and_cert(
            ssh_executor=mock_ssh,
            host="10.1.4.10",
            timeout_seconds=60,
            poll_interval=5,
        )

        assert serial == "007200001267"

    def test_retries_until_both_present(self, mocker):
        """Retries when serial present but cert missing."""
        mocker.patch("time.sleep")
        from main import poll_for_serial_and_cert

        mock_ssh = MagicMock()
        mock_ssh.run_command.side_effect = [
            MagicMock(stdout="serial: 007200001267"),
            MagicMock(stdout="serial: 007200001267\ndevice-certificate-status: Valid"),
        ]

        serial = poll_for_serial_and_cert(
            ssh_executor=mock_ssh,
            host="10.1.4.10",
            timeout_seconds=600,
            poll_interval=30,
        )

        assert serial == "007200001267"
        assert mock_ssh.run_command.call_count == 2

    def test_raises_after_timeout(self, mocker):
        """Raises RuntimeError after timeout with details."""
        mocker.patch("time.sleep")
        from main import poll_for_serial_and_cert

        mock_ssh = MagicMock()
        mock_ssh.run_command.return_value = MagicMock(stdout="serial: unknown")

        with pytest.raises(RuntimeError, match="verification failed"):
            poll_for_serial_and_cert(
                ssh_executor=mock_ssh,
                host="10.1.4.10",
                timeout_seconds=0,
                poll_interval=30,
            )
