"""Backwards compatibility re-export for Secrets service.

This module has been moved to engine.services.secrets.
These re-exports maintain backwards compatibility during migration.
"""

from engine.services.secrets import SecretsError, get_ssh_key

__all__ = ["SecretsError", "get_ssh_key"]
