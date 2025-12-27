"""Setup plans for different instance types."""

from .bootstrap import BootstrapPlan
from .dc_setup import DCSetupPlan
from .xdr_agent_install import XDRAgentInstallPlan

__all__ = ["BootstrapPlan", "DCSetupPlan", "XDRAgentInstallPlan"]
