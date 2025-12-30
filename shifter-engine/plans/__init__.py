"""Setup plans for different instance types."""

from .base import SetupStep
from .bootstrap import BootstrapPlan
from .dc_setup import DCSetupPlan
from .domain_join import DomainJoinPlan
from .linux_bootstrap import LinuxBootstrapPlan
from .linux_xdr_agent_install import LinuxXDRAgentInstallPlan
from .ngfw_verification import NGFWVerificationPlan
from .xdr_agent_install import XDRAgentInstallPlan

__all__ = [
    "SetupStep",
    "BootstrapPlan",
    "DCSetupPlan",
    "DomainJoinPlan",
    "LinuxBootstrapPlan",
    "LinuxXDRAgentInstallPlan",
    "NGFWVerificationPlan",
    "XDRAgentInstallPlan",
]
