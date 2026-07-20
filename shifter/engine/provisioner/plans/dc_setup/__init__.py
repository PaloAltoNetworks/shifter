"""DC (Domain Controller) setup plan.

Supports two operating modes:
- prebaked: DC image already has AD DS promoted
- runtime promotion: install/promote AD DS during setup

The embedded PowerShell scripts are split into ``_scripts`` (Sonar /
500-line-cap) and re-exported here so callers keep using
``from plans.dc_setup import DCSetupPlan`` / ``plans.dc_setup.<name>``
exactly as before the split.
"""

from typing import Any, ClassVar

from ..base import SetupStep
from ._scripts import (
    ENABLE_SSH_AUTH_SCRIPT,
    PROMOTE_DC_SCRIPT,
    SET_ADMIN_CREDENTIAL_SCRIPT,
    VERIFY_AD_SCRIPT,
)

__all__ = [
    "ENABLE_SSH_AUTH_SCRIPT",
    "PROMOTE_DC_SCRIPT",
    "SET_ADMIN_CREDENTIAL_SCRIPT",
    "VERIFY_AD_SCRIPT",
    "DCSetupPlan",
]


class DCSetupPlan:
    """Setup plan for Windows Domain Controller.

    In prebaked mode, this plan configures runtime settings and verifies AD.
    In runtime-promotion mode, it promotes the instance first, then applies the
    same runtime settings and verification.
    """

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_ad_running",
        script=VERIFY_AD_SCRIPT,
        # 15 min - allows 15 retries x 20s delays + verification time
        timeout_seconds=900,
        is_verification=True,
    )

    def __init__(self, runtime_promotion: bool = False) -> None:
        self.runtime_promotion = runtime_promotion

    @property
    def steps(self) -> list[SetupStep]:
        steps: list[SetupStep] = []
        if self.runtime_promotion:
            steps.append(
                SetupStep(
                    name="promote_domain_controller",
                    script=PROMOTE_DC_SCRIPT,
                    timeout_seconds=1800,
                    requires_reboot=True,
                )
            )

        steps.extend(
            [
                SetupStep(
                    name="set_admin_password",
                    # Must exceed the script's AD-DS readiness wait loop
                    # (15 attempts x 20s ~= 300s) so the orchestrator does not
                    # kill the step mid-wait on a slow-to-start cloned DC.
                    script=SET_ADMIN_CREDENTIAL_SCRIPT,
                    timeout_seconds=420,
                ),
                SetupStep(
                    name="enable_ssh_password_auth",
                    script=ENABLE_SSH_AUTH_SCRIPT,
                    timeout_seconds=600,
                ),
            ]
        )
        return steps

    @staticmethod
    # NOSONAR - instance is duck-typed per the SetupPlan protocol (plans/base.py);
    # consistent with every other get_context implementation in this package.
    def get_context(instance: Any) -> dict[str, Any]:  # NOSONAR
        """Get template variables for DC setup scripts.

        Args:
            instance: DC instance with domain configuration

        Returns:
            Dict with domain_name, netbios_name, dsrm_password, domain_admin_password

        Raises:
            ValueError: If required attributes are missing or None
        """
        required_attrs = [
            "domain_name",
            "netbios_name",
            "dsrm_password",
            "domain_admin_password",
        ]

        context = {}
        for attr in required_attrs:
            value = getattr(instance, attr, None)
            if value is None:
                raise ValueError(f"Instance missing required attribute '{attr}' for DC setup")
            context[attr] = value

        return context
