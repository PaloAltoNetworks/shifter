"""Secret-safe setup plans for bounded RAES Active Directory realization."""

from __future__ import annotations

import base64

from ._raes_active_directory_scripts import (
    _AUTHORITY,
    _JOIN_MEMBER,
    _MEMBER_STATE,
    _PROMOTE,
    _PROVISION_OFFLINE_JOIN,
    _REALIZE_ACCOUNT,
    _VERIFY_CONTROLLER,
    _VERIFY_MEMBER,
)
from .base import SetupStep


def _b64(value: str) -> str:
    """Encode one UTF-8 runtime value for line-oriented PowerShell stdin."""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _context(**values: str) -> dict[str, str]:
    """Return raw and base64 forms for each setup-plan runtime value."""
    context = dict(values)
    context.update({f"{key}_b64": _b64(value) for key, value in values.items()})
    return context


class RaesDomainControllerPlan:
    """Prepare the RID-500 authority and promote one exact authored domain."""

    def __init__(
        self,
        *,
        dns_name: str,
        netbios_name: str,
        authority_username: str,
        dsrm_password: str,
        authority_password: str,
        require_existing_domain: bool = False,
    ) -> None:
        self._context = _context(
            dns_name=dns_name,
            netbios_name=netbios_name,
            require_existing_domain="1" if require_existing_domain else "0",
            authority_username=authority_username,
            dsrm_password=dsrm_password,
            authority_password=authority_password,
        )

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name="raes_ad_promote",
                script=_PROMOTE,
                stdin_input=(
                    "{{ dns_name_b64 }}\n{{ netbios_name_b64 }}\n{{ authority_username_b64 }}\n"
                    "{{ dsrm_password_b64 }}\n{{ authority_password_b64 }}\n{{ require_existing_domain_b64 }}\n"
                ),
                timeout_seconds=1200,
            )
        ]

    @property
    def verify_step(self) -> None:
        return None

    def get_context(self, _instance: object) -> dict[str, str]:
        return {
            "dns_name": self._context["dns_name"],
            "dns_name_b64": self._context["dns_name_b64"],
            "netbios_name": self._context["netbios_name"],
            "netbios_name_b64": self._context["netbios_name_b64"],
            "authority_username": self._context["authority_username"],
            "authority_username_b64": self._context["authority_username_b64"],
            "dsrm_password": self._context["dsrm_password"],
            "dsrm_password_b64": self._context["dsrm_password_b64"],
            "authority_password": self._context["authority_password"],
            "authority_password_b64": self._context["authority_password_b64"],
            "require_existing_domain_b64": self._context["require_existing_domain_b64"],
        }


class RaesDomainControllerVerificationPlan:
    """Reconcile and read back the domain authority after promotion/reconnect."""

    def __init__(self, *, dns_name: str, netbios_name: str, authority_username: str, authority_password: str) -> None:
        self._context = _context(
            dns_name=dns_name,
            netbios_name=netbios_name,
            authority_username=authority_username,
            authority_password=authority_password,
        )

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name="raes_ad_authority",
                script=_AUTHORITY,
                stdin_input=(
                    "{{ dns_name_b64 }}\n{{ netbios_name_b64 }}\n{{ authority_username_b64 }}\n"
                    "{{ authority_password_b64 }}\n"
                ),
                timeout_seconds=600,
            )
        ]

    @property
    def verify_step(self) -> SetupStep:
        return SetupStep(
            name="raes_ad_verify_controller",
            script=_VERIFY_CONTROLLER,
            stdin_input="{{ dns_name_b64 }}\n{{ netbios_name_b64 }}\n",
            timeout_seconds=600,
            is_verification=True,
        )

    def get_context(self, _instance: object) -> dict[str, str]:
        return {
            "dns_name": self._context["dns_name"],
            "dns_name_b64": self._context["dns_name_b64"],
            "netbios_name": self._context["netbios_name"],
            "netbios_name_b64": self._context["netbios_name_b64"],
            "authority_username": self._context["authority_username"],
            "authority_username_b64": self._context["authority_username_b64"],
            "authority_password": self._context["authority_password"],
            "authority_password_b64": self._context["authority_password_b64"],
        }


class RaesDomainMemberStatePlan:
    """Read the exact local machine identity and current domain membership."""

    def __init__(self, *, dns_name: str, controller_ip: str) -> None:
        self._context = _context(dns_name=dns_name, controller_ip=controller_ip)

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name="raes_ad_member_state",
                script=_MEMBER_STATE,
                stdin_input="{{ dns_name_b64 }}\n{{ controller_ip_b64 }}\n",
                timeout_seconds=600,
            )
        ]

    @property
    def verify_step(self) -> None:
        return None

    def get_context(self, _instance: object) -> dict[str, str]:
        return {
            "dns_name": self._context["dns_name"],
            "dns_name_b64": self._context["dns_name_b64"],
            "controller_ip": self._context["controller_ip"],
            "controller_ip_b64": self._context["controller_ip_b64"],
        }


class RaesDomainOfflineJoinProvisionPlan:
    """Create one machine-scoped offline-domain-join package on the controller."""

    def __init__(self, *, dns_name: str, machine_name: str) -> None:
        self._context = _context(dns_name=dns_name, machine_name=machine_name)

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name="raes_ad_offline_join_provision",
                script=_PROVISION_OFFLINE_JOIN,
                stdin_input=(f"{self._context['dns_name_b64']}\n{self._context['machine_name_b64']}\n"),
                timeout_seconds=600,
            )
        ]

    @property
    def verify_step(self) -> None:
        return None

    def get_context(self, _instance: object) -> dict[str, str]:
        return {
            "dns_name": self._context["dns_name"],
            "dns_name_b64": self._context["dns_name_b64"],
            "machine_name": self._context["machine_name"],
            "machine_name_b64": self._context["machine_name_b64"],
        }


class RaesDomainMemberPlan:
    """Apply a machine-scoped offline-domain-join package to one member."""

    def __init__(self, *, dns_name: str, controller_ip: str, offline_join_blob: str) -> None:
        self._context = _context(
            dns_name=dns_name,
            controller_ip=controller_ip,
            offline_join_blob_secret=offline_join_blob,
        )

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name="raes_ad_join_member",
                script=_JOIN_MEMBER,
                stdin_input=("{{ dns_name_b64 }}\n{{ controller_ip_b64 }}\n{{ offline_join_blob_secret_b64 }}\n"),
                timeout_seconds=1200,
                requires_reboot=True,
            )
        ]

    @property
    def verify_step(self) -> SetupStep:
        return SetupStep(
            name="raes_ad_verify_member",
            script=_VERIFY_MEMBER,
            stdin_input="{{ dns_name_b64 }}\n",
            timeout_seconds=600,
            is_verification=True,
        )

    def get_context(self, _instance: object) -> dict[str, str]:
        return {
            "dns_name": self._context["dns_name"],
            "dns_name_b64": self._context["dns_name_b64"],
            "controller_ip": self._context["controller_ip"],
            "controller_ip_b64": self._context["controller_ip_b64"],
            "offline_join_blob_secret": self._context["offline_join_blob_secret"],
            "offline_join_blob_secret_b64": self._context["offline_join_blob_secret_b64"],
        }


class RaesDomainAccountPlan:
    """Reconcile one domain principal, register its SPN uniquely, and read it back."""

    def __init__(self, *, dns_name: str, username: str, password: str, spn: str | None) -> None:
        self._context = _context(dns_name=dns_name, username=username, password=password, spn=spn or "")

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name="raes_ad_account_spn",
                script=_REALIZE_ACCOUNT,
                stdin_input="{{ dns_name_b64 }}\n{{ username_b64 }}\n{{ password_b64 }}\n{{ spn_b64 }}\n",
                timeout_seconds=600,
            )
        ]

    @property
    def verify_step(self) -> None:
        return None

    def get_context(self, _instance: object) -> dict[str, str]:
        return {
            "dns_name": self._context["dns_name"],
            "dns_name_b64": self._context["dns_name_b64"],
            "username": self._context["username"],
            "username_b64": self._context["username_b64"],
            "password": self._context["password"],
            "password_b64": self._context["password_b64"],
            "spn": self._context["spn"],
            "spn_b64": self._context["spn_b64"],
        }
