"""Setup plans for different instance types."""

from .bootstrap import BootstrapPlan
from .dc_setup import DCSetupPlan
from .domain_join import DomainJoinPlan
from .kali_setup import KaliSetupPlan
from .linux_bootstrap import LinuxBootstrapPlan
from .linux_xdr_agent_install import LinuxXDRAgentInstallPlan
from .xdr_agent_install import XDRAgentInstallPlan

__all__ = [
    "BootstrapPlan",
    "DCSetupPlan",
    "DomainJoinPlan",
    "KaliSetupPlan",
    "LinuxBootstrapPlan",
    "LinuxXDRAgentInstallPlan",
    "XDRAgentInstallPlan",
]
