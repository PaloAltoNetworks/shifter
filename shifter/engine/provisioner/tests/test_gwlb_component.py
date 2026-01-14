"""Tests for GWLBComponent.

GWLBComponent creates Gateway Load Balancer infrastructure for NGFW traffic
steering. Integration tests verify actual AWS resource creation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestGWLBComponentProtocol:
    """Tests for GWLBComponent interface compliance."""

    def test_component_can_be_imported(self):
        """GWLBComponent can be imported from the components module."""
        from components.gwlb_component import GWLBComponent

        assert GWLBComponent is not None
