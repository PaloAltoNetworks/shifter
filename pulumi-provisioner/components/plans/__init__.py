"""Setup plans for different instance types."""

from .bootstrap import BootstrapPlan
from .dc_setup import DCSetupPlan

__all__ = ["BootstrapPlan", "DCSetupPlan"]
