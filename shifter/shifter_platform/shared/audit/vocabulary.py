"""Canonical audit vocabulary (neutral contracts layer).

This is the single source of truth for the audit action / entity / actor
vocabulary. Emitters across every layer reference these enums; the
``shared.AuditLog`` ORM model derives its field ``choices`` from them so
there is exactly one vocabulary and one event shape (ADR-001, #1523). Values and
human labels are stable — historical ``AuditLog`` rows and migrations depend on
them — so new members are added, never renamed or re-valued.
"""

from __future__ import annotations

from django.db import models

# Shared label for platform API-token entity and actor events.
API_KEY_LABEL = "API Key"


class AuditAction(models.TextChoices):
    """Auditable actions performed against a platform entity."""

    # Entity lifecycle
    CREATE = "create", "Create"
    UPDATE = "update", "Update"
    DELETE = "delete", "Delete"
    ARCHIVE = "archive", "Archive"
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
    CAPACITY_ASSESS = "capacity_assess", "Capacity Assess"
    # Tenant quota enforcement (PLAT-239)
    QUOTA_APPLIED = "quota_applied", "Quota Applied"
    # Warm pool (#28): closed vocabulary for pool lifecycle and claim events so
    # pool operations, claims, fallbacks, and cleanup are audited and observable.
    WARM_PREPARE = "warm_prepare", "Warm Prepare"
    WARM_CLAIM = "warm_claim", "Warm Claim"
    WARM_FALLBACK = "warm_fallback", "Warm Fallback"
    WARM_ACTIVATE = "warm_activate", "Warm Activate"
    WARM_RETIRE = "warm_retire", "Warm Retire"
    # Model-access sharing (PLAT-202, #2139): binding publication, withdrawal and
    # authoritative membership projection changes are audited with safe IDs and
    # revisions only.
    SHARING_PUBLISH = "sharing_publish", "Sharing Publish"
    SHARING_DRAIN = "sharing_drain", "Sharing Drain"
    SHARING_MEMBERSHIP = "sharing_membership", "Sharing Membership"


class AuditEntityType(models.TextChoices):
    """Types of entity an audit event can be recorded against."""

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
    WORKSPACE_MEMBERSHIP = "workspace_membership", "Workspace Membership"
    WORKSPACE_INVITATION = "workspace_invitation", "Workspace Invitation"
    WORKSPACE = "workspace", "Workspace"
    ORGANIZATION = "organization", "Organization"
    # ADR-051, #2048: scoped CTF communications (campaigns, intents, deliveries).
    COMMUNICATION = "communication", "Communication"
    # Model-access sharing binding (PLAT-202, #2139).
    SHARING_BINDING = "sharing_binding", "Sharing Binding"
    PREPARATION_ADAPTER = "preparation_adapter", "Preparation Adapter"
    PREPARATION_GRANT = "preparation_grant", "Preparation Grant"
    ARTIFACT_PREPARATION = "artifact_preparation", "Artifact Preparation"


class AuditActorType(models.TextChoices):
    """Types of actor that can trigger an audit event."""

    USER = "user", "User"
    APIKEY = "apikey", API_KEY_LABEL
    SYSTEM = "system", "System"
    COGNITO = "cognito", "Cognito"
