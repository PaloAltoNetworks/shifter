"""CMS service interface.

Content and asset management for Shifter platform.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.contrib.auth.models import User


# =============================================================================
# Agents
# =============================================================================


def create_agent(user: User, **kwargs: Any) -> Any:
    """Create agent record."""
    raise NotImplementedError


def delete_agent(user: User, agent_id: int) -> None:
    """Soft delete agent."""
    raise NotImplementedError


def list_agents(user: User) -> list[Any]:
    """Get user's agents."""
    raise NotImplementedError


def get_agent(user: User, agent_id: int) -> Any:
    """Get single agent."""
    raise NotImplementedError


# =============================================================================
# Credentials
# =============================================================================


def create_credential(user: User, credential_type: str, **kwargs: Any) -> Any:
    """Create credential (scm, authcode)."""
    raise NotImplementedError


def delete_credential(user: User, credential_id: int) -> None:
    """Delete credential."""
    raise NotImplementedError


def list_credentials(user: User) -> list[Any]:
    """Get user's credentials (includes type)."""
    raise NotImplementedError


def get_credential(user: User, credential_id: int) -> Any:
    """Get single credential."""
    raise NotImplementedError


# =============================================================================
# Ranges
# =============================================================================


def create_range(user: User, scenario: str, agent_id: int, **kwargs: Any) -> Any:
    """Compose scenario, trigger provisioning."""
    raise NotImplementedError


def destroy_range(user: User, range_id: int) -> None:
    """Tear down range."""
    raise NotImplementedError


def list_ranges(user: User) -> list[Any]:
    """Get user's ranges."""
    raise NotImplementedError


def get_range(user: User, range_id: int) -> Any:
    """Get single range."""
    raise NotImplementedError


def cancel_range(user: User, range_id: int) -> None:
    """Cancel provisioning range."""
    raise NotImplementedError


def pause_range(user: User, range_id: int) -> None:
    """Pause range."""
    raise NotImplementedError


def resume_range(user: User, range_id: int) -> None:
    """Resume range."""
    raise NotImplementedError


# =============================================================================
# Uploads
# =============================================================================


def initiate_upload(user: User, name: str, filename: str, file_size: int) -> dict[str, Any]:
    """Validate, generate presigned URL."""
    raise NotImplementedError


def complete_upload(user: User, upload_token: str, sha256: str) -> Any:
    """Verify and finalize upload."""
    raise NotImplementedError


def cancel_upload(user: User, upload_token: str) -> None:
    """Clean up failed upload."""
    raise NotImplementedError


# =============================================================================
# User Quota
# =============================================================================


def get_storage_used(user: User) -> int:
    """Check storage quota."""
    raise NotImplementedError


# =============================================================================
# Scenarios
# =============================================================================


def list_scenarios(user: User) -> list[Any]:
    """Get available scenarios."""
    raise NotImplementedError
