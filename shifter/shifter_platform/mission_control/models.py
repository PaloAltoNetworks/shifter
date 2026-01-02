"""Mission Control models.

Asset base classes (Asset, FileAsset, CredentialBase) have been moved to cms.models.
AgentConfig and OperatingSystem have been moved to cms.models.
Range and UserNGFW have been moved to engine.models.
See issues #446, #437.

This module re-exports Range and UserNGFW for backwards compatibility.
Import from engine.models for new code.
"""

# Re-export from engine for backwards compatibility
# TODO: Remove these re-exports once all consumers are updated (Issue #437)
from engine.models import Range, UserNGFW

__all__ = ["Range", "UserNGFW"]
