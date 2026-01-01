"""Centralized logging configuration for Shifter platform using Elastic Common Schema (ECS).

Provides ECS-compliant log formatting for XDR/XSIAM ingestion with consistent schema
across all platform components. ECS is the industry standard adopted by OpenTelemetry
for semantic conventions.

Usage in settings.py:
    LOGGING = {
        "formatters": {"ecs": {"()": "config.logging.ECSFormatter"}},
        ...
    }

Reference: https://www.elastic.co/guide/en/ecs/current/ecs-reference.html
"""

import json
import logging
from datetime import UTC, datetime

# ECS version we're conforming to
ECS_VERSION = "8.11"


class ECSFormatter(logging.Formatter):
    """Format logs as ECS-compliant JSON for XDR/XSIAM ingestion.

    Output schema (ECS 8.11):
    {
        "@timestamp": "2025-12-18T12:34:56.789Z",
        "log.level": "INFO",
        "log.logger": "mission_control.views",
        "message": "Human readable message",
        "ecs.version": "8.11",
        "service.name": "portal",
        "service.environment": "dev",
        "log.origin.function": "launch_range",
        "log.origin.file.line": 42,
        "http.request.method": "POST",
        "url.path": "/...",
        "user.id": "...",
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
        "agent_config_id",
        "execution_arn",
    )

    def __init__(self, environment: str = "unknown"):
        super().__init__()
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as ECS-compliant JSON."""
        # Import settings lazily to avoid circular imports
        try:
            from django.conf import settings

            environment = getattr(settings, "ENVIRONMENT", self._environment)
        except Exception:
            environment = self._environment

        # Core ECS fields (order matters per spec: @timestamp, log.level, message)
        log_obj = {
            "@timestamp": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "log.level": record.levelname,
            "message": record.getMessage(),
            "ecs.version": ECS_VERSION,
            # Service fields
            "service.name": "portal",
            "service.environment": environment,
            # Log metadata
            "log.logger": record.name,
            "log.origin.function": record.funcName,
            "log.origin.file.line": record.lineno,
        }

        # Add HTTP request context if available (using ECS HTTP fields)
        if hasattr(record, "request"):
            try:
                req = record.request
                if hasattr(req, "method"):
                    log_obj["http.request.method"] = req.method
                if hasattr(req, "path"):
                    log_obj["url.path"] = req.path
                if hasattr(req, "user") and req.user.is_authenticated:
                    log_obj["user.id"] = str(req.user.id)
            except Exception:  # noqa: S110  # nosec B110
                pass  # Intentional: don't fail logging if request context is malformed

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
