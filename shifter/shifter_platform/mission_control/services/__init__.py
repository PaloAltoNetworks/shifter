"""Services for mission_control app.

Mission Control is a presentation layer - most services have moved to engine.
Backwards compat re-exports are provided for get_ssh_key only during migration.
SSHConnection should be imported directly from engine.ssh.
"""

from mission_control.services.secrets import SecretsError, get_ssh_key

__all__ = ["SecretsError", "get_ssh_key"]
