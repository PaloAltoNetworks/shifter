"""Pytest configuration for cyberscript library tests.

This conftest adds the parent directory to sys.path so that imports
like `from cyberscript.enums import ...` work correctly.
"""

import sys
from pathlib import Path

# Add shifter/ to path so 'cyberscript' package is importable
SHIFTER_DIR = Path(__file__).resolve().parent.parent.parent
if str(SHIFTER_DIR) not in sys.path:
    sys.path.insert(0, str(SHIFTER_DIR))
