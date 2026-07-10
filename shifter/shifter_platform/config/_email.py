"""Email backend configuration (PLAT-002 GCP parity, #671).

Extracted from ``config/settings.py`` (Sonar S104 500-line cap) so the email
keys have a single owner. ``config.settings`` star-imports the public names.

Provider model
~~~~~~~~~~~~~~
* **AWS** sends through ``django-ses`` (``EMAIL_BACKEND=django_ses.SESBackend``),
  authenticated by the portal's IAM role — no credential is ever committed. The
  ``AWS_SES_REGION_*`` constants below feed django-ses; they default to the
  established ``us-east-2`` values so AWS behavior is unchanged (ADR-005
  continuity) and are env-overridable rather than hardcoded.
* **GCP** has no native SES equivalent, so a GCP deployment sends through an
  operator-chosen transactional-email SaaS (SendGrid or Mailgun) via
  ``django-anymail``. The ESP **API key is a secret value**: it is hydrated at
  runtime into ``EMAIL_API_KEY`` from the active provider's secret store
  (Secret Manager) and is never written to checked-in config, Helm values, or
  logs. Only the backend choice, sender address, and (for Mailgun) the sender
  domain are non-secret config.

Email is optional only when the selected backend is explicit. Dev/test/build
imports default to the console backend; production runtimes must pass
``EMAIL_BACKEND`` so a missing renderer/SSM value does not silently discard mail.
"""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from config._runtime_env import required_runtime_env, runtime_allows_dev_defaults

__all__ = [
    "ANYMAIL",
    "AWS_SES_REGION_ENDPOINT",
    "AWS_SES_REGION_NAME",
    "DEFAULT_FROM_EMAIL",
    "EMAIL_BACKEND",
]

_CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"
_MAILGUN_BACKEND = "anymail.backends.mailgun.EmailBackend"

# Maps an anymail ``EMAIL_BACKEND`` to the ``ANYMAIL`` settings key that carries
# its API key. Non-anymail backends (console, SES, SMTP) are absent by design.
_ANYMAIL_API_KEY_NAMES = {
    "anymail.backends.sendgrid.EmailBackend": "SENDGRID_API_KEY",
    _MAILGUN_BACKEND: "MAILGUN_API_KEY",
}


def build_anymail_config(email_backend: str, api_key: str, *, mailgun_sender_domain: str = "") -> dict[str, str]:
    """Build the Django ``ANYMAIL`` settings dict for the selected ESP backend.

    Returns an empty dict for non-anymail backends or when no API key has been
    hydrated. The ``api_key`` is a runtime secret value; callers must never log
    or persist it to checked-in config.
    """
    key_name = _ANYMAIL_API_KEY_NAMES.get(email_backend)
    if not key_name or not api_key:
        return {}
    config = {key_name: api_key}
    if email_backend == _MAILGUN_BACKEND and mailgun_sender_domain:
        config["MAILGUN_SENDER_DOMAIN"] = mailgun_sender_domain
    return config


EMAIL_BACKEND = required_runtime_env("EMAIL_BACKEND", dev_default=_CONSOLE_BACKEND)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "webmaster@localhost")
_EMAIL_API_KEY = os.environ.get("EMAIL_API_KEY", "")
_MAILGUN_SENDER_DOMAIN = os.environ.get("MAILGUN_SENDER_DOMAIN", "")

if _ANYMAIL_API_KEY_NAMES.get(EMAIL_BACKEND) and not _EMAIL_API_KEY and not runtime_allows_dev_defaults():
    raise ImproperlyConfigured(f"EMAIL_API_KEY environment variable is required when EMAIL_BACKEND={EMAIL_BACKEND}")
if EMAIL_BACKEND == _MAILGUN_BACKEND and not _MAILGUN_SENDER_DOMAIN and not runtime_allows_dev_defaults():
    raise ImproperlyConfigured("MAILGUN_SENDER_DOMAIN environment variable is required when EMAIL_BACKEND is Mailgun")

# django-ses (AWS path) reads these; inert under any non-SES backend. Defaults
# preserve the prior hardcoded us-east-2 values so AWS delivery is unchanged.
AWS_SES_REGION_NAME = os.environ.get("AWS_SES_REGION_NAME", "us-east-2")
AWS_SES_REGION_ENDPOINT = os.environ.get("AWS_SES_REGION_ENDPOINT", "email.us-east-2.amazonaws.com")

# The ESP API key is hydrated from the secret store into ``EMAIL_API_KEY`` at
# runtime (entrypoint secret hydration); it is never a checked-in value.
ANYMAIL = build_anymail_config(
    EMAIL_BACKEND,
    _EMAIL_API_KEY,
    mailgun_sender_domain=_MAILGUN_SENDER_DOMAIN,
)
