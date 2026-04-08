"""Executors for running commands on remote targets.

Executors provide a consistent interface for command execution across
different transports (SSM, SSH, AWS API, KubeVirt API).
"""

from executors.ngfw_executor import NGFWExecutor  # noqa: F401
