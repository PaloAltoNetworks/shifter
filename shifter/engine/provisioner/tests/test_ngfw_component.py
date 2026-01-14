"""Tests for NGFWComponent.

NGFWComponent creates the NGFW EC2 instance with ENIs and bootstrap config.
Integration tests verify actual AWS resource creation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestNGFWComponentProtocol:
    """Tests for NGFWComponent interface compliance."""

    def test_component_can_be_imported(self):
        """NGFWComponent can be imported from the components module."""
        from components.ngfw_component import NGFWComponent

        assert NGFWComponent is not None
