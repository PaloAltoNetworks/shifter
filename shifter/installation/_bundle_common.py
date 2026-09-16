"""Shared primitives for the per-backend bundle modules.

The backend bundle definitions live in per-backend modules (:mod:`installation.bundle_aws`,
:mod:`installation.bundle_gcp`) so no single file grows past the SonarCloud S104 file-size
budget, mirroring the ``settings_*`` and ``runtime_inventory_*`` split. This module holds the
constants and generated-output helpers both bundles reuse; it imports only the contract
models, so it introduces no import cycle with the bundle modules or the registry.
"""

from __future__ import annotations

from .contract import (
    BackendCapability,
    CommandSpec,
    GeneratedOutput,
    HealthCheck,
    OutputDestination,
    OutputKind,
    OutputSensitivity,
    ProcessRole,
    ValidationCheck,
)

# The contract-shape version every bundle is written against. Pinned literally so that
# adding a future ``contract_version`` to ``SUPPORTED_CONTRACT_VERSIONS`` does not silently
# re-version the bundles — a new version requires an intentional edit here (and a
# settings/renderer migration for the backend).
CONTRACT_VERSION = 1
ROOT_CONFIG_PATH = "shifter.yaml"
SHIFTER_CHART_PATH = "platform/charts/shifter"

# Process roles that share the derived runtime environment.
RUNTIME_ROLES: tuple[ProcessRole, ...] = (ProcessRole.PORTAL, ProcessRole.WORKER, ProcessRole.PROVISIONER)

# The cloud-neutral capability protocols both AWS and GCP satisfy today, enumerated
# explicitly (not ``frozenset(BackendCapability)``) so a new capability enum member is
# not auto-claimed by every backend — a backend opts in by listing it here.
AWS_AND_GCP_CAPABILITIES: frozenset[BackendCapability] = frozenset(
    {
        BackendCapability.STORAGE,
        BackendCapability.QUEUE_CONSUMER,
        BackendCapability.QUEUE_PUBLISHER,
        BackendCapability.TASK_RUNNER,
        BackendCapability.SECRETS,
        BackendCapability.CONFIG_STORE,
        BackendCapability.EVENT_BUS,
        BackendCapability.DATABASE_AUTH,
        BackendCapability.NETWORK_INVENTORY,
        BackendCapability.CAPACITY_INVENTORY,
    }
)

ROOT_CONFIG_CHECK = ValidationCheck(
    name="root-config",
    command=CommandSpec(
        argv=("uv", "run", "--project", "shifter/installation", "shifter-config", "validate", ROOT_CONFIG_PATH),
        description="Validate the root installation config (shifter.yaml) shape.",
    ),
    description="Fail fast on a malformed shifter.yaml before any backend infrastructure runs.",
)

PORTAL_HEALTH_CHECK = HealthCheck(
    name="portal-health",
    target="https://<deployment.domain>/health/",
    requires_credentials=False,
    timeout_seconds=10,
    description="Read-only probe of the portal /health/ endpoint after deploy.",
)

# Common runtime bindings the platform consumes today: ``CLOUD_PROVIDER`` picks the
# adapter family (``config.settings``); ``entrypoint.sh`` fetches the app and database
# secret bundles from the provider secret store, and only does so when *both* references
# are present, so a backend must declare both. GCP emits the canonical ``*_SECRET_ID``
# names; AWS emits the ``*_SECRET_ARN`` aliases, which ``entrypoint.sh`` normalizes.


def cloud_provider_output(renderer: str) -> GeneratedOutput:
    """Build the shared ``CLOUD_PROVIDER`` generated output for a backend renderer."""
    return GeneratedOutput(
        name="CLOUD_PROVIDER",
        kind=OutputKind.RUNTIME_ENV,
        owner=renderer,
        source="the backend runtime-env renderer",
        destination=OutputDestination.RUNTIME_ENV,
        sensitivity=OutputSensitivity.PUBLIC,
        process_roles=RUNTIME_ROLES,
        description=(
            "Selects the cloud adapter family at runtime for the portal, workers, and provisioner; "
            "emitted by the backend, never set from a branch name."
        ),
    )


def secret_reference_output(name: str, *, renderer: str, store: str, kind: OutputKind, what: str) -> GeneratedOutput:
    """Build one secret-reference generated output (a reference id, never the value)."""
    return GeneratedOutput(
        name=name,
        kind=kind,
        owner=renderer,
        source=f"the backend runtime-env renderer (a {store} reference for the {what})",
        destination=OutputDestination.RUNTIME_ENV,
        sensitivity=OutputSensitivity.SECRET_REFERENCE,
        process_roles=(ProcessRole.PORTAL, ProcessRole.WORKER),
        description=(
            f"Reference to the {what} in the portal/worker runtime environment; the process fetches the value "
            f"from {store} at startup (entrypoint.sh) — a reference only, the secret value stays in {store}."
        ),
    )


def secret_outputs(
    renderer: str, *, store: str, app_name: str, db_name: str, kind: OutputKind
) -> tuple[GeneratedOutput, ...]:
    """Build the app + database secret-reference generated outputs for a backend."""
    alias = " (the AWS-style alias entrypoint.sh normalizes)" if kind is OutputKind.COMPAT_ALIAS else ""
    return (
        secret_reference_output(app_name, renderer=renderer, store=store, kind=kind, what=f"app secret bundle{alias}"),
        secret_reference_output(db_name, renderer=renderer, store=store, kind=kind, what=f"database secret{alias}"),
    )
