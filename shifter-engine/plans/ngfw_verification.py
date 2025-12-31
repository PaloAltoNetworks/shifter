"""NGFW verification plan for checking SCM registration.

Verifies that VM-Series has successfully registered with Strata Cloud Manager.
"""

from typing import Any, Dict, List

from .base import SetupStep


class NGFWVerificationPlan:
    """Verification plan for NGFW SCM registration.

    This plan has no setup steps - the NGFW bootstraps itself via
    S3 init-cfg. We only verify that registration succeeded.

    Verification:
    - Run `show panorama-status` and check for connected status

    Attributes:
        steps: Empty list - no setup steps needed
        verify_step: Step to verify SCM connection
        max_retries: Number of retry attempts (1 = retry once then fail)
        retry_delay_seconds: Delay between retries
    """

    steps: List[SetupStep] = []  # No setup steps - bootstrap is automatic

    verify_step: SetupStep = SetupStep(
        name="verify_scm_registration",
        script="show panorama-status",
        timeout_seconds=60,
        is_verification=True,
    )

    # Retry configuration (per user decision: retry once then fail)
    max_retries: int = 1
    retry_delay_seconds: int = 60  # 1 minute between retries

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables (none needed for verification).

        Args:
            instance: NGFW instance (unused)

        Returns:
            Empty dict - no template variables needed
        """
        return {}

    @staticmethod
    def parse_panorama_status(output: str) -> dict:
        """Parse output of 'show panorama-status' command.

        Expected output format (connected):
            Panorama Server 1 : cloud
                Connected     : yes
                HA state      : n/a

        Expected output format (not connected):
            Panorama Server 1 : cloud
                Connected     : no

        Args:
            output: Raw CLI output

        Returns:
            Dict with parsed status fields:
            - connected: bool
            - server: str (e.g., "cloud")
        """
        result = {
            "connected": False,
            "server": None,
        }

        for line in output.splitlines():
            line_lower = line.strip().lower()

            # Check for server line
            if "panorama server" in line_lower:
                parts = line.split(":")
                if len(parts) >= 2:
                    result["server"] = parts[1].strip()

            # Check for connected status
            if "connected" in line_lower:
                if "yes" in line_lower:
                    result["connected"] = True
                elif "no" in line_lower:
                    result["connected"] = False

        return result

    @staticmethod
    def is_registered(output: str) -> bool:
        """Check if NGFW is registered based on panorama-status output.

        Args:
            output: Raw CLI output from 'show panorama-status'

        Returns:
            True if connected to SCM/Panorama
        """
        status = NGFWVerificationPlan.parse_panorama_status(output)
        return status["connected"]
