"""Celery tasks for Shifter Engine provisioning operations.

Each task:
1. Loads request/range data via Django ORM
2. Calls the appropriate provisioner function
3. Updates models via engine services
4. Emits Django signals for cross-app notification

Tasks are thin wrappers — the heavy lifting stays in the provisioner modules.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0)
def provision_range(self, request_id: str) -> None:
    """Provision range infrastructure via Terraform.

    Args:
        request_id: UUID string of the Request to provision.
    """
    logger.info("Task provision_range started: request_id=%s", request_id)
    try:
        from engine.provisioner.main import run_range_provision

        run_range_provision(request_id)
    except Exception:
        logger.exception("Task provision_range failed: request_id=%s", request_id)
        raise


@shared_task(bind=True, max_retries=0)
def destroy_range(self, request_id: str) -> None:
    """Destroy range infrastructure via Terraform.

    Args:
        request_id: UUID string of the Request to destroy.
    """
    logger.info("Task destroy_range started: request_id=%s", request_id)
    try:
        from engine.provisioner.main import run_range_destroy

        run_range_destroy(request_id)
    except Exception:
        logger.exception("Task destroy_range failed: request_id=%s", request_id)
        raise


@shared_task(bind=True, max_retries=0)
def pause_range(self, request_id: str) -> None:
    """Pause all instances in a range.

    Args:
        request_id: UUID string of the Request to pause.
    """
    logger.info("Task pause_range started: request_id=%s", request_id)
    try:
        from engine.provisioner.main import run_range_pause

        run_range_pause(request_id)
    except Exception:
        logger.exception("Task pause_range failed: request_id=%s", request_id)
        raise


@shared_task(bind=True, max_retries=0)
def resume_range(self, request_id: str) -> None:
    """Resume all instances in a range.

    Args:
        request_id: UUID string of the Request to resume.
    """
    logger.info("Task resume_range started: request_id=%s", request_id)
    try:
        from engine.provisioner.main import run_range_resume

        run_range_resume(request_id)
    except Exception:
        logger.exception("Task resume_range failed: request_id=%s", request_id)
        raise


@shared_task(bind=True, max_retries=0)
def provision_ngfw(self, request_id: str) -> None:
    """Provision NGFW infrastructure via Terraform.

    Args:
        request_id: UUID string of the Request to provision.
    """
    logger.info("Task provision_ngfw started: request_id=%s", request_id)
    try:
        from engine.provisioner.main import run_ngfw_provision

        run_ngfw_provision(request_id)
    except Exception:
        logger.exception("Task provision_ngfw failed: request_id=%s", request_id)
        raise


@shared_task(bind=True, max_retries=0)
def deprovision_ngfw(self, request_id: str) -> None:
    """Deprovision NGFW infrastructure via Terraform.

    Args:
        request_id: UUID string of the Request to deprovision.
    """
    logger.info("Task deprovision_ngfw started: request_id=%s", request_id)
    try:
        from engine.provisioner.main import run_ngfw_deprovision

        run_ngfw_deprovision(request_id)
    except Exception:
        logger.exception("Task deprovision_ngfw failed: request_id=%s", request_id)
        raise


@shared_task(bind=True, max_retries=0)
def start_ngfw(self, request_id: str) -> None:
    """Start a stopped NGFW instance.

    Args:
        request_id: UUID string of the Request.
    """
    logger.info("Task start_ngfw started: request_id=%s", request_id)
    try:
        from engine.provisioner.main import run_ngfw_start

        run_ngfw_start(request_id)
    except Exception:
        logger.exception("Task start_ngfw failed: request_id=%s", request_id)
        raise


@shared_task(bind=True, max_retries=0)
def stop_ngfw(self, request_id: str) -> None:
    """Stop a running NGFW instance.

    Args:
        request_id: UUID string of the Request.
    """
    logger.info("Task stop_ngfw started: request_id=%s", request_id)
    try:
        from engine.provisioner.main import run_ngfw_stop

        run_ngfw_stop(request_id)
    except Exception:
        logger.exception("Task stop_ngfw failed: request_id=%s", request_id)
        raise


@shared_task(bind=True, max_retries=0)
def complete_ngfw_setup(self, request_id: str) -> None:
    """Complete NGFW setup after user associates device.

    Args:
        request_id: UUID string of the Request.
    """
    logger.info("Task complete_ngfw_setup started: request_id=%s", request_id)
    try:
        from engine.provisioner.main import run_ngfw_complete_setup

        run_ngfw_complete_setup(request_id)
    except Exception:
        logger.exception("Task complete_ngfw_setup failed: request_id=%s", request_id)
        raise
