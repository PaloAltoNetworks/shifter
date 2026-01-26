"""Setup plans for different instance types."""

from .base import SetupStep
from .bootstrap import BootstrapPlan
from .dc_setup import DCSetupPlan
from .domain_join import DomainJoinPlan
from .linux_bootstrap import LinuxBootstrapPlan
from .linux_xdr_agent_install import LinuxXDRAgentInstallPlan
from .xdr_agent_install import XDRAgentInstallPlan

# Caldera plans are NOT activated by default - import explicitly when needed:
#   from shifter.engine.provisioner.plans.caldera_server_setup import (
#       CalderaServerSetupPlan,
#       CalderaServerStopPlan,
#   )
#   from shifter.engine.provisioner.plans.caldera_agent_deploy import (
#       CalderaLinuxAgentDeployPlan,
#       CalderaWindowsAgentDeployPlan,
#       CalderaLinuxAgentStopPlan,
#   )

__all__ = [
    "BootstrapPlan",
    "DCSetupPlan",
    "DomainJoinPlan",
    "LinuxBootstrapPlan",
    "LinuxXDRAgentInstallPlan",
    "SetupStep",
    "XDRAgentInstallPlan",
]
