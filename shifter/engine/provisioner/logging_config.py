"""ECS-compliant logging configuration for the provisioner.

Matches the ECS format used by the Django platform for consistent log ingestion.
"""

import json
import logging
import os
from datetime import UTC, datetime

ECS_VERSION = "8.11"


class ECSFormatter(logging.Formatter):
    """Format logs as ECS-compliant JSON."""

    LABEL_FIELDS = ("range_id", "user_id", "trace_id", "execution_arn")

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "@timestamp": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "log.level": record.levelname,
            "message": record.getMessage(),
            "ecs.version": ECS_VERSION,
            "service.name": "provisioner",
            "service.environment": os.environ.get("ENVIRONMENT", "unknown"),
            "log.logger": record.name,
            "log.origin.function": record.funcName,
            "log.origin.file.line": record.lineno,
        }

        for key in self.LABEL_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                log_obj[f"labels.{key}"] = value

        if record.exc_info:
            log_obj["error.stack_trace"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger with ECS formatting."""
    handler = logging.StreamHandler()
    handler.setFormatter(ECSFormatter())
    logging.root.handlers = [handler]
    logging.root.setLevel(level)
