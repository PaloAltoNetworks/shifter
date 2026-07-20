"""Tests for provider-aware email backend configuration (PLAT-002, #671).

AWS sends through django-ses (IAM auth, no committed credentials). GCP has no
native SES equivalent, so a GCP deployment sends through an operator-chosen
transactional-email SaaS (SendGrid or Mailgun) via django-anymail, with the ESP
API key hydrated at runtime from the secret store and never committed. When no
backend is configured the console backend is used (email is optional).
"""

from __future__ import annotations

import importlib

import pytest
from django.core.exceptions import ImproperlyConfigured

SENDGRID_BACKEND = "anymail.backends.sendgrid.EmailBackend"
MAILGUN_BACKEND = "anymail.backends.mailgun.EmailBackend"
CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"


def _reload_email_module():
    import config._email as email_module

    return importlib.reload(email_module)


# ---------------------------------------------------------------------------
# build_anymail_config — pure function, no env / no I/O
# ---------------------------------------------------------------------------


def test_anymail_config_sendgrid_carries_only_the_api_key() -> None:
    from config._email import build_anymail_config

    assert build_anymail_config(SENDGRID_BACKEND, "SG.secret") == {"SENDGRID_API_KEY": "SG.secret"}


def test_anymail_config_mailgun_carries_key_and_sender_domain() -> None:
    from config._email import build_anymail_config

    config = build_anymail_config(MAILGUN_BACKEND, "mg-secret", mailgun_sender_domain="mg.example.com")

    assert config == {"MAILGUN_API_KEY": "mg-secret", "MAILGUN_SENDER_DOMAIN": "mg.example.com"}


def test_anymail_config_is_empty_for_non_anymail_backend() -> None:
    from config._email import build_anymail_config

    assert build_anymail_config(CONSOLE_BACKEND, "ignored") == {}


def test_anymail_config_is_empty_when_api_key_missing() -> None:
    # An ESP backend without a hydrated key must NOT emit an empty-credential
    # ANYMAIL dict; the deployment is simply unconfigured.
    from config._email import build_anymail_config

    assert build_anymail_config(SENDGRID_BACKEND, "") == {}


# ---------------------------------------------------------------------------
# Module-level settings derived from the environment
# ---------------------------------------------------------------------------


def test_defaults_use_console_backend_and_no_anymail(monkeypatch) -> None:
    for var in ("EMAIL_BACKEND", "DEFAULT_FROM_EMAIL", "EMAIL_API_KEY", "MAILGUN_SENDER_DOMAIN"):
        monkeypatch.delenv(var, raising=False)

    email_module = _reload_email_module()

    assert email_module.EMAIL_BACKEND == CONSOLE_BACKEND
    assert email_module.ANYMAIL == {}


def test_production_requires_explicit_email_backend(monkeypatch) -> None:
    for var in ("EMAIL_BACKEND", "DEFAULT_FROM_EMAIL", "EMAIL_API_KEY", "MAILGUN_SENDER_DOMAIN", "TESTING"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DJANGO_DEBUG", "false")

    with pytest.raises(ImproperlyConfigured, match="EMAIL_BACKEND"):
        _reload_email_module()


def test_production_anymail_backend_requires_hydrated_api_key(monkeypatch) -> None:
    for var in ("DEFAULT_FROM_EMAIL", "EMAIL_API_KEY", "MAILGUN_SENDER_DOMAIN", "TESTING"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DJANGO_DEBUG", "false")
    monkeypatch.setenv("EMAIL_BACKEND", SENDGRID_BACKEND)

    with pytest.raises(ImproperlyConfigured, match="EMAIL_API_KEY"):
        _reload_email_module()


def test_gcp_sendgrid_backend_reads_key_from_env(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_BACKEND", SENDGRID_BACKEND)
    monkeypatch.setenv("EMAIL_API_KEY", "SG.hydrated")
    monkeypatch.setenv("DEFAULT_FROM_EMAIL", "noreply@shifter.example.com")

    email_module = _reload_email_module()

    assert email_module.EMAIL_BACKEND == SENDGRID_BACKEND
    assert email_module.DEFAULT_FROM_EMAIL == "noreply@shifter.example.com"
    assert email_module.ANYMAIL == {"SENDGRID_API_KEY": "SG.hydrated"}


def test_aws_ses_region_defaults_preserved_and_overridable(monkeypatch) -> None:
    for var in ("AWS_SES_REGION_NAME", "AWS_SES_REGION_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)

    email_module = _reload_email_module()
    # AWS behavior is unchanged: the SES region constants keep their us-east-2 default.
    assert email_module.AWS_SES_REGION_NAME == "us-east-2"
    assert email_module.AWS_SES_REGION_ENDPOINT == "email.us-east-2.amazonaws.com"

    monkeypatch.setenv("AWS_SES_REGION_NAME", "us-west-2")
    monkeypatch.setenv("AWS_SES_REGION_ENDPOINT", "email.us-west-2.amazonaws.com")
    email_module = _reload_email_module()
    assert email_module.AWS_SES_REGION_NAME == "us-west-2"
    assert email_module.AWS_SES_REGION_ENDPOINT == "email.us-west-2.amazonaws.com"
