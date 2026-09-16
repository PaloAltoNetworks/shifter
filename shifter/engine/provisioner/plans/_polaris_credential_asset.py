"""Load the reviewed Polaris splice helper bundled with the provisioner."""

from __future__ import annotations

import base64
from pathlib import Path

_PACKAGED_HELPER = Path(__file__).resolve().parents[1] / "assets" / "polaris-splice-credential.py"
_SOURCE_HELPER = Path(__file__).resolve().parents[3] / "packer" / "files" / "polaris_splice_credential.py"


def splice_credential_helper_b64() -> str:
    """Return the exact helper bytes for secret-free host staging."""
    for path in (_PACKAGED_HELPER, _SOURCE_HELPER):
        if path.is_file():
            return base64.b64encode(path.read_bytes()).decode("ascii")
    raise RuntimeError("Polaris splice credential helper is not packaged")
