"""Canonical audit vocabulary (neutral contracts layer).

This is the single source of truth for the audit action / entity / actor
vocabulary. Emitters across every layer reference these enums; the
``risk_register.AuditLog`` ORM model derives its field ``choices`` from them so
there is exactly one vocabulary and one event shape (ADR-001, #1523). Values and
human labels are stable — historical ``AuditLog`` rows and migrations depend on
them — so new members are added, never renamed or re-valued.
"""

from __future__ import annotations

from django.db import models

# Shared label for the retired risk-register API key entity/actor (kept for
# parity with historical rows). Distinct from the ``risk_register`` model's own
# ``verbose_name`` constant so the vocabulary stays self-contained.
API_KEY_LABEL = "API Key"


class AuditAction(models.TextChoices):
    """Auditable actions performed against a platform entity."""

    # Entity lifecycle
    CREATE = "create", "Create"
    UPDATE = "update", "Update"
    DELETE = "delete", "Delete"
    RESTORE = "restore", "Restore"
    CLOSE = "close", "Close"
    REOPEN = "reopen", "Reopen"
    # Authentication
    LOGIN = "login", "Login"
    LOGOUT = "logout", "Logout"
    LOGIN_FAILED = "login_failed", "Login Failed"
    ACCESS_DENIED = "access_denied", "Access Denied"
    # Authorization
    ROLE_SYNC = "role_sync", "Role Sync"
    # Sessions
    CONNECT = "connect", "Connect"
    DISCONNECT = "disconnect", "Disconnect"
    DOWNLOAD = "download", "Download"
    # Resource lifecycle
    PROVISION = "provision", "Provision"
    DEPROVISION = "deprovision", "Deprovision"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"
    PAUSE = "pause", "Pause"
    RESUME = "resume", "Resume"
    CANCEL = "cancel", "Cancel"
    RECOVER = "recover", "Recover"
    SPARE_PROVISION = "spare_provision", "Spare Provision"


class AuditEntityType(models.TextChoices):
    """Types of entity an audit event can be recorded against."""

    # Risk Register entities
    RISK = "risk", "Risk"
    COMMENT = "comment", "Comment"
    APIKEY = "apikey", API_KEY_LABEL
    # Platform entities
    RANGE = "range", "Range"
    CREDENTIAL = "credential", "Credential"
    AGENT = "agent", "Agent"
    USER = "user", "User"
    SESSION = "session", "Session"
    NGFW = "ngfw", "NGFW"
    CONFIG = "config", "Configuration"
    EXPERIMENT = "experiment", "Experiment"
    SCENARIO = "scenario", "Scenario"
    SCRIPT = "script", "Script"


class AuditActorType(models.TextChoices):
    """Types of actor that can trigger an audit event."""

    USER = "user", "User"
    APIKEY = "apikey", API_KEY_LABEL
    SYSTEM = "system", "System"
    COGNITO = "cognito", "Cognito"
