"""Local subprocess provisioner fallback for development.

Runs the provisioner as a local subprocess instead of submitting a remote
task, gated by the ``LOCAL_PROVISIONER`` setting. Split out of
``engine/ecs.py`` (#685).
"""

from __future__ import annotations

import logging
import os
import subprocess  # nosec B404 - local dev provisioner only  # NOSONAR

from django.conf import settings

# Log under the stable "engine.ecs" namespace (asserted by tests and used in
# dashboards) even though this code now lives in a package submodule.
logger = logging.getLogger("engine.ecs")


def _run_local_provisioner(command: list[str]) -> str | None:
    """Run the provisioner locally as a subprocess.

    Args:
        command: Command arguments
            (e.g., ["range", "provision", "--request-id", "..."])

    Returns:
        "local-{pid}" if started successfully, None if not configured

    Raises:
        RuntimeError: If provisioner fails to start
    """
    provisioner_path = getattr(settings, "PROVISIONER_PATH", None)
    if not provisioner_path:
        # Default to relative path from Django app. This module lives one
        # package level deeper than the pre-#685 ``engine/ecs.py`` module
        # (``engine/ecs/_local.py``), so the walk up to the repo root takes
        # one extra ``dirname()`` hop to resolve the same
        # ``shifter/engine/provisioner`` default.
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        provisioner_path = os.path.join(base, "engine", "provisioner")

    main_py = os.path.join(provisioner_path, "main.py")
    if not os.path.exists(main_py):
        logger.error("Provisioner not found at %s", main_py)
        return None

    # Build environment for provisioner
    env = os.environ.copy()

    # Ensure required env vars are set (from Django settings or environment)
    env.setdefault("ENVIRONMENT", getattr(settings, "ENVIRONMENT", "dev"))
    env.setdefault("CLOUD_PROVIDER", settings.CLOUD_PROVIDER)
    env.setdefault("CLOUD_REGION", getattr(settings, "CLOUD_REGION", "us-east-2"))
    env.setdefault("AWS_REGION", getattr(settings, "AWS_REGION", "us-east-2"))
    gcp_project_id = getattr(settings, "GCP_PROJECT_ID", "")
    if gcp_project_id:
        env.setdefault("GCP_PROJECT_ID", gcp_project_id)
        env.setdefault("GOOGLE_CLOUD_PROJECT", gcp_project_id)

    # For local dev, use standard DB connection (not IAM auth)
    # The provisioner will need DB_HOST, DB_USER, DB_PASSWORD, DB_NAME
    if hasattr(settings, "DATABASES"):
        db_config = settings.DATABASES.get("default", {})
        env.setdefault("DB_HOST", str(db_config.get("HOST", "localhost")))
        env.setdefault("DB_PORT", str(db_config.get("PORT", 5432)))
        env.setdefault("DB_USER", str(db_config.get("USER", "postgres")))
        env.setdefault("DB_PASSWORD", str(db_config.get("PASSWORD", "")))
        env.setdefault("DB_NAME", str(db_config.get("NAME", "shifter")))

    aws_endpoint = getattr(settings, "AWS_ENDPOINT_URL", "")
    if aws_endpoint:
        env.setdefault("AWS_ENDPOINT_URL", aws_endpoint)

    full_command = ["python", main_py, *command]
    logger.info("Starting local provisioner: %s", " ".join(full_command))

    # Security: command is a hardcoded path to our first-party provisioner, not
    # user input; run non-blocking (background) so dispatch returns immediately.
    try:
        process = subprocess.Popen(  # noqa: S603  # nosec B603  # NOSONAR
            full_command,
            cwd=provisioner_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info("Local provisioner started with PID %s", process.pid)
        return f"local-{process.pid}"

    except Exception as e:
        logger.exception("Failed to start local provisioner: %s", e)
        raise RuntimeError(f"Local provisioner failed: {e}") from e


def _is_local_provisioner_enabled() -> bool:
    """Check if local provisioner mode is enabled."""
    mode = getattr(settings, "LOCAL_PROVISIONER", None)
    return mode in ("subprocess", "docker")
