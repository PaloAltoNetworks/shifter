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
    AUTHORIZATION_REQUESTED = "authorization_requested", "Authorization Requested"
    AUTHORIZATION_CONFIRMED = "authorization_confirmed", "Authorization Confirmed"
    AUTHORIZATION_DENIED = "authorization_denied", "Authorization Denied"
    AUTHORIZATION_UNRESOLVED = "authorization_unresolved", "Authorization Unresolved"
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
    # Model-access request accounting (PLAT-202, #2121, M04): budget reservation,
    # settlement, retained-unknown charge, revocation fence and reconciliation
    # adjustment. Prompts, responses, fingerprints and credentials never appear.
    MODEL_REQUEST_RESERVE = "request_reserve", "Model Request Reserve"
    MODEL_REQUEST_SETTLE = "request_settle", "Model Request Settle"
    MODEL_REQUEST_UNKNOWN = "request_unknown", "Model Request Unknown"
    MODEL_REQUEST_REVOKE = "request_revoke", "Model Request Revoke"
    MODEL_REQUEST_ADJUST = "request_adjust", "Model Request Adjust"


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
    ACCOUNT = "account", "Account"
    ACCOUNT_MEMBERSHIP = "account_membership", "Account Membership"
    PRINCIPAL = "principal", "Principal"
    PROVIDER_BINDING = "provider_binding", "Provider Binding"
    AUTHORIZATION_GROUP = "authorization_group", "Authorization Group"
    AUTHORIZATION_POLICY = "authorization_policy", "Authorization Policy"
    AUTHORIZATION_OPERATION = "authorization_operation", "Authorization Operation"
    # ADR-051, #2048: scoped CTF communications (campaigns, intents, deliveries).
    COMMUNICATION = "communication", "Communication"
    # Model-access sharing binding (PLAT-202, #2139).
    SHARING_BINDING = "sharing_binding", "Sharing Binding"
    # Model-access request accounting (PLAT-202, #2121, M04).
    MODEL_REQUEST = "model_request", "Model Request"
    MODEL_CREDENTIAL = "model_credential", "Model Credential"
    PREPARATION_ADAPTER = "preparation_adapter", "Preparation Adapter"
    RUNTIME_PLUGIN = "runtime_plugin", "Runtime Plugin"
    PREPARATION_GRANT = "preparation_grant", "Preparation Grant"
    ARTIFACT_PREPARATION = "artifact_preparation", "Artifact Preparation"


class AuditActorType(models.TextChoices):
    """Types of actor that can trigger an audit event."""

    USER = "user", "User"
    APIKEY = "apikey", API_KEY_LABEL
    SYSTEM = "system", "System"
    COGNITO = "cognito", "Cognito"
    PRINCIPAL = "principal", "Principal"
