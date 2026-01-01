"""
Cognito Pre-Signup Lambda Trigger

Validates email domain before allowing user registration.
Allows:
- Emails matching allowed domains (e.g., @paloaltonetworks.com)
- Specific whitelisted emails (for external users)

Logging: Uses Elastic Common Schema (ECS) 8.11 for XDR/XSIAM ingestion.
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
        "log.logger": "pre_signup",
        "message": "Human readable message",
        "ecs.version": "8.11",
        "service.name": "cognito",
        "service.environment": "dev",
        "faas.name": "shifter-dev-pre-signup",
        "log.origin.function": "handler",
        "error.stack_trace": "traceback"
    }
    """

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "@timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "log.level": record.levelname,
            "message": record.getMessage(),
            "ecs.version": ECS_VERSION,
            "service.name": "cognito",
            "service.environment": os.environ.get("ENVIRONMENT", "unknown"),
            "log.logger": record.name,
            "log.origin.function": record.funcName,
            "faas.name": os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "pre-signup"),
        }
        if record.exc_info:
            log_obj["error.stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(log_obj, default=str)


# Backwards compatibility alias
JSONFormatter = ECSFormatter


def _get_logger() -> logging.Logger:
    """Get an ECS-formatted logger."""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(ECSFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    return logger


logger = _get_logger()


def handler(event, context):
    try:
        email = event.get("request", {}).get("userAttributes", {}).get("email", "")
        if email:
            email = email.lower().strip()

        logger.info(f"Pre-signup check for email domain: {email.split('@')[-1] if '@' in email else 'invalid'}")

        # Basic email validation
        if not email or "@" not in email:
            logger.warning("Signup rejected: invalid email format (missing or no @)")
            raise Exception("Invalid email format")

        parts = email.split("@")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            logger.warning("Signup rejected: invalid email format (malformed)")
            raise Exception("Invalid email format")

        local_part, domain = parts

        # Get allowed domains and emails from environment
        allowed_domains = [d.strip().lower() for d in os.environ.get("ALLOWED_DOMAINS", "").split(",") if d.strip()]
        allowed_emails = [e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()]

        # Check if email is explicitly allowed
        if email in allowed_emails:
            logger.info(f"Signup allowed: email in allowlist")
            return event

        # Check if email domain is allowed
        if domain in allowed_domains:
            logger.info(f"Signup allowed: domain {domain} in allowed domains")
            return event

        # Deny signup
        logger.warning(f"Signup rejected: domain {domain} not in allowed list")
        raise Exception("Email domain not allowed. Contact administrator for access.")

    except Exception as e:
        # Re-raise known exceptions, log unexpected ones
        if "Invalid email" in str(e) or "not allowed" in str(e):
            raise
        logger.error(f"Unexpected error during pre-signup: {e}")
        raise Exception("Signup failed. Please try again or contact administrator.")
