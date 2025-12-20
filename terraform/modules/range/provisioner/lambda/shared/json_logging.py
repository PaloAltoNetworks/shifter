"""Structured JSON logging for Lambda functions using Elastic Common Schema (ECS).

Provides ECS-compliant log formatting for XDR/XSIAM ingestion across all
provisioner Lambda functions. ECS is the industry standard adopted by
OpenTelemetry for semantic conventions.

Usage:
    from shared.json_logging import get_logger
    logger = get_logger(__name__)
    logger.info("Creating subnet", extra={"range_id": "abc-123"})

Reference: https://www.elastic.co/guide/en/ecs/current/ecs-reference.html
"""

import json
import logging
import os
from datetime import datetime, timezone

# ECS version we're conforming to
ECS_VERSION = "8.11"


class ECSFormatter(logging.Formatter):
    """Format logs as ECS-compliant JSON for XDR/XSIAM ingestion.

    Output schema (ECS 8.11):
    {
        "@timestamp": "2025-12-18T12:34:56.789Z",
        "log.level": "INFO",
        "log.logger": "handler",
        "message": "Human readable message",
        "ecs.version": "8.11",
        "service.name": "provisioner",
        "service.environment": "dev",
        "faas.name": "shifter-dev-create-subnet",
        "labels.range_id": "uuid",
        "error.stack_trace": "traceback"
    }
    """

    # Fields that can be passed via extra={} in log calls
    # These get prefixed with "labels." per ECS convention for custom fields
    LABEL_FIELDS = (
        "range_id",
        "user_id",
        "trace_id",
        "subnet_id",
        "instance_id",
        "subnet_cidr",
        "kali_ip",
        "victim_ip",
    )

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as ECS-compliant JSON."""
        # Core ECS fields (order matters per spec: @timestamp, log.level, message)
        log_obj = {
            "@timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "log.level": record.levelname,
            "message": record.getMessage(),
            "ecs.version": ECS_VERSION,
            # Service fields
            "service.name": "provisioner",
            "service.environment": os.environ.get("ENVIRONMENT", "unknown"),
            # Log metadata
            "log.logger": record.name,
            # FaaS (Function as a Service) fields for Lambda
            "faas.name": os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown"),
        }

        # Add custom fields as labels (ECS convention for custom data)
        for key in self.LABEL_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                log_obj[f"labels.{key}"] = value

        # Add exception info using ECS error fields
        if record.exc_info:
            log_obj["error.stack_trace"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, default=str)


# Backwards compatibility alias
JSONFormatter = ECSFormatter


def get_logger(name: str | None = None) -> logging.Logger:
    """Get an ECS-formatted logger for Lambda functions.

    Args:
        name: Logger name, typically __name__ of the calling module.

    Returns:
        Configured logger with ECS formatting.

    Example:
        logger = get_logger(__name__)
        logger.info("Starting subnet creation", extra={"range_id": range_id})
        logger.error("Failed to create subnet", extra={"range_id": range_id}, exc_info=True)
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Only add handler if not already configured (avoid duplicates)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(ECSFormatter())
        logger.addHandler(handler)
        logger.propagate = False

    return logger
