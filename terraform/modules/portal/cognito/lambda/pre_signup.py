"""
Cognito Pre-Signup Lambda Trigger

Validates email domain before allowing user registration.
Allows:
- Emails matching allowed domains (e.g., @paloaltonetworks.com)
- Specific whitelisted emails (for external users)
"""

import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)


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
