"""Backwards compatibility re-export for ECS service.

This module has been moved to engine.services.ecs.
These re-exports maintain backwards compatibility during migration.
"""

from engine.services.ecs import get_task_status, start_provisioning, start_teardown

__all__ = ["get_task_status", "start_provisioning", "start_teardown"]
