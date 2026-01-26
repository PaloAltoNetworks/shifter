"""Range stack component tests for Shifter Engine.

RangeStack composes NetworkComponent(s) and InstanceComponent(s) to create
complete cyber range infrastructure. Integration tests verify actual AWS
resource creation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestRangeStackProtocol:
    """Tests for RangeStack interface compliance."""

    def test_stack_can_be_imported(self):
        """RangeStack can be imported from the stacks module."""
        from stacks.range_stack import RangeStack

        assert RangeStack is not None

    def test_config_classes_can_be_imported(self):
        """Config classes can be imported."""
        from config import InstanceConfig, RangeConfig, SubnetConfig

        assert RangeConfig is not None
        assert SubnetConfig is not None
        assert InstanceConfig is not None
