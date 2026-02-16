"""Setup plans for different instance types."""

from .base import SetupStep
from .bootstrap import BootstrapPlan
from .caldera_agent_deploy import (
    CalderaLinuxAgentDeployPlan,
    CalderaLinuxAgentStopPlan,
    CalderaWindowsAgentDeployPlan,
)
from .caldera_server_setup import CalderaServerSetupPlan, CalderaServerStopPlan
from .dc_setup import DCSetupPlan
from .domain_join import DomainJoinPlan
from .linux_bootstrap import LinuxBootstrapPlan
from .linux_xdr_agent_install import LinuxXDRAgentInstallPlan
from .xdr_agent_install import XDRAgentInstallPlan

__all__ = [
    "BootstrapPlan",
    "CalderaLinuxAgentDeployPlan",
    "CalderaLinuxAgentStopPlan",
    "CalderaServerSetupPlan",
    "CalderaServerStopPlan",
    "CalderaWindowsAgentDeployPlan",
    "DCSetupPlan",
    "DomainJoinPlan",
    "LinuxBootstrapPlan",
    "LinuxXDRAgentInstallPlan",
    "SetupStep",
    "XDRAgentInstallPlan",
]
