"""PAN-OS poll/parse/wait helpers for the Shifter Engine provisioner.

Extracted from ``ngfw_runtime.py`` (Sonar S104). Owns the parsers for
``show system info`` (serial / device-certificate-status), the post-
boot poll loops, and the autocommit waiter.
"""

from __future__ import annotations

import logging
import re
import time

from executors.ngfw_executor import NGFWExecutor

logger = logging.getLogger(__name__)

# Default timeout for waiting for NGFW SSH to become available. PAN-OS boot time
# is typically 15-25 minutes, but can take longer on first boot.
NGFW_SSH_WAIT_TIMEOUT_DEFAULT = 1500


def parse_serial_number(system_info_output: str) -> str | None:
    """Extract serial number from PAN-OS 'show system info' output."""
    match = re.search(r"serial:\s*(\S+)", system_info_output, re.IGNORECASE)
    if not match:
        logger.warning("Serial number not found in system info output")
        return None

    serial = match.group(1).strip()

    if not serial or serial.lower() in ("unknown", "none", "n/a", ""):
        logger.warning("Serial number is placeholder value: %s", serial)
        return None

    logger.info("Extracted NGFW serial number: %s", serial)
    return serial


def poll_for_serial_number(
    ssh_executor: NGFWExecutor,
    host: str,
    timeout_seconds: int = 600,
    poll_interval: int = 30,
) -> str:
    """Poll NGFW for serial number until it appears or timeout."""
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            raise RuntimeError(
                f"NGFW serial number not found after {timeout_seconds}s - license registration may have failed"
            )

        logger.info(
            "Polling for NGFW serial number... (%.0fs / %ds)",
            elapsed,
            timeout_seconds,
        )

        try:
            result = ssh_executor.run_command(
                instance_id=host,
                script="show system info",
                timeout_seconds=60,
            )
            serial = parse_serial_number(result.stdout)
            if serial:
                logger.info(
                    "NGFW serial number found after %.0fs: %s",
                    elapsed,
                    serial,
                )
                return serial

            logger.info("Serial not yet available, retrying in %ds...", poll_interval)

        except Exception as e:
            logger.warning("Error polling for serial (will retry): %s", e)

        time.sleep(poll_interval)


def parse_device_certificate_status(system_info_output: str) -> str | None:
    """Extract device certificate status from PAN-OS 'show system info' output."""
    match = re.search(r"device-certificate-status:\s*(\S+)", system_info_output, re.IGNORECASE)
    if not match:
        return None

    return match.group(1).strip()


def _format_serial_cert_status(serial_value: str | None, cert_status: str | None) -> str:
    """Format the per-poll serial/cert progress string for the retry log line."""
    serial_part = f"serial={serial_value}" if serial_value else "serial=waiting"
    cert_part = f"cert={cert_status}" if cert_status == "Valid" else f"cert={cert_status or 'waiting'}"
    return f"{serial_part}, {cert_part}"


def _raise_serial_cert_timeout(timeout_seconds: int, serial_value: str | None, cert_status: str | None) -> None:
    """Raise RuntimeError describing which of serial/cert were still missing at timeout."""
    missing = []
    if not serial_value:
        missing.append("serial number")
    if cert_status != "Valid":
        missing.append(f"device certificate (status: {cert_status or 'not found'})")
    raise RuntimeError(f"NGFW verification failed after {timeout_seconds}s - missing: {', '.join(missing)}")


def poll_for_serial_and_cert(
    ssh_executor: NGFWExecutor,
    host: str,
    timeout_seconds: int = 1800,
    poll_interval: int = 30,
) -> str:
    """Poll NGFW until both serial number AND device certificate are present."""
    start_time = time.time()
    serial_value: str | None = None
    cert_status: str | None = None

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            _raise_serial_cert_timeout(timeout_seconds, serial_value, cert_status)

        logger.info(
            "Polling for NGFW serial and certificate... (%.0fs / %ds)",
            elapsed,
            timeout_seconds,
        )

        try:
            result = ssh_executor.run_command(
                instance_id=host,
                script="show system info",
                timeout_seconds=60,
            )

            logger.debug("Raw SSH output (first 500 chars): %r", result.stdout[:500])

            serial_value = parse_serial_number(result.stdout)
            cert_status = parse_device_certificate_status(result.stdout)

            if serial_value and cert_status == "Valid":
                logger.info(
                    "NGFW verification complete after %.0fs: serial=%s, cert=%s",
                    elapsed,
                    serial_value,
                    cert_status,
                )
                return serial_value

            logger.info(
                "NGFW not ready (%s), retrying in %ds...",
                _format_serial_cert_status(serial_value, cert_status),
                poll_interval,
            )

        except Exception as e:
            logger.warning("Error polling NGFW (will retry): %s", e)

        time.sleep(poll_interval)


def wait_for_autocommit(
    ssh_executor: NGFWExecutor,
    host: str,
    timeout_seconds: int = 600,
    poll_interval: int = 15,
) -> None:
    """Wait for NGFW boot autocommit to complete before configuring."""
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            raise RuntimeError(
                f"NGFW autocommit did not complete after {timeout_seconds}s - management plane may be stuck"
            )

        logger.info(
            "Checking for active NGFW jobs... (%.0fs / %ds)",
            elapsed,
            timeout_seconds,
        )

        try:
            result = ssh_executor.run_command(
                instance_id=host,
                script="show jobs all",
                timeout_seconds=60,
            )

            output = result.stdout
            has_active_jobs = bool(re.search(r"\bACT\b", output))

            if not has_active_jobs:
                logger.info(
                    "No active NGFW jobs found after %.0fs - ready for configuration",
                    elapsed,
                )
                return

            active_lines = [line.strip() for line in output.split("\n") if "ACT" in line]
            logger.info(
                "Found %d active job(s), waiting %ds: %s",
                len(active_lines),
                poll_interval,
                # Show first 3 for brevity
                active_lines[:3],
            )

        except Exception as e:
            logger.warning("Error checking NGFW jobs (will retry): %s", e)

        time.sleep(poll_interval)
