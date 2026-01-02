"""Backwards compatibility re-export for SSH service.

This module has been moved to engine.services.ssh.
These re-exports maintain backwards compatibility during migration.
"""

from engine.services.ssh import SSHConnection, SSHConnectionError

__all__ = ["SSHConnection", "SSHConnectionError"]
