"""The Shifter backend bundle registry.

This is the single source of truth for which backends an OSS deployment can select
(PLAT-2002) and what each one exposes (the :mod:`installation.contract` shape,
PLAT-2003). The root schema (:mod:`installation.schema`) derives backend and profile
validation from the data here, and :mod:`installation.loader` runs each backend's
``settings`` and secret-reference checks against the selected bundle — so adding a
backend or a profile is a registry entry, not a schema change or a branch router. There
is exactly one such table in the repo; Django, workflows, bootstrap scripts, and CI
consume *this* one rather than maintaining their own.

The ``aws`` and ``gcp`` entries below are intentionally *provisional*. They carry the
backend identity, supported profiles, owned repo roots, required Terraform/CLI tools,
the root-config validation check, a portal health probe, and the ``CLOUD_PROVIDER`` and
app/database secret-reference runtime bindings the platform actually consumes today —
enough to exercise the contract end to end — but their ``settings_model`` and each
``RequiredSecret.reference_pattern`` are left unset (any ``settings`` mapping is
accepted; references are checked at deploy time), and the per-backend renderer,
validation-check, and infrastructure-entrypoint detail is filled in by the AWS and GCP
backend bundle migration issues (#1116/#1117). The ``local`` backend is #1119.
Constrained by ADR-011.
"""

from __future__ import annotations

from .contract import (
    BackendBundle,
    BackendCapability,
    BackendMaturity,
    CommandSpec,
    GeneratedOutput,
    HealthCheck,
    OutputDestination,
    OutputKind,
    OutputSensitivity,
    OwnedFiles,
    ProcessRole,
    RequiredSecret,
    RequiredTool,
    ValidationCheck,
)

# The contract-shape version every bundle below is written against. Pinned literally so
# that adding a future ``contract_version`` to ``SUPPORTED_CONTRACT_VERSIONS`` does not
# silently re-version these bundles — a new version requires an intentional edit here
# (and a settings/renderer migration for the backend).
_CONTRACT_VERSION = 1

# Process roles that share the derived runtime environment.
_RUNTIME_ROLES: tuple[ProcessRole, ...] = (ProcessRole.PORTAL, ProcessRole.WORKER, ProcessRole.PROVISIONER)

# The cloud-neutral capability protocols both AWS and GCP satisfy today, enumerated
# explicitly (not ``frozenset(BackendCapability)``) so a new capability enum member is
# not auto-claimed by every backend — a backend opts in by listing it here.
_AWS_AND_GCP_CAPABILITIES: frozenset[BackendCapability] = frozenset(
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
    }
)

_ROOT_CONFIG_CHECK = ValidationCheck(
    name="root-config",
    command=CommandSpec(
        argv=("uv", "run", "--project", "shifter/installation", "shifter-config", "validate", "shifter.yaml"),
        description="Validate the root installation config (shifter.yaml) shape.",
    ),
    description="Fail fast on a malformed shifter.yaml before any backend infrastructure runs.",
)

_PORTAL_HEALTH_CHECK = HealthCheck(
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


def _cloud_provider_output(renderer: str) -> GeneratedOutput:
    return GeneratedOutput(
        name="CLOUD_PROVIDER",
        kind=OutputKind.RUNTIME_ENV,
        owner=renderer,
        source="the backend runtime-env renderer",
        destination=OutputDestination.RUNTIME_ENV,
        sensitivity=OutputSensitivity.PUBLIC,
        process_roles=_RUNTIME_ROLES,
        description=(
            "Selects the cloud adapter family at runtime for the portal, workers, and provisioner; "
            "emitted by the backend, never set from a branch name."
        ),
    )


def _secret_reference_output(name: str, *, renderer: str, store: str, kind: OutputKind, what: str) -> GeneratedOutput:
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


def _secret_outputs(
    renderer: str, *, store: str, app_name: str, db_name: str, kind: OutputKind
) -> tuple[GeneratedOutput, ...]:
    alias = " (the AWS-style alias entrypoint.sh normalizes)" if kind is OutputKind.COMPAT_ALIAS else ""
    return (
        _secret_reference_output(app_name, renderer=renderer, store=store, kind=kind, what=f"app secret bundle{alias}"),
        _secret_reference_output(db_name, renderer=renderer, store=store, kind=kind, what=f"database secret{alias}"),
    )


_AWS_BUNDLE = BackendBundle(
    contract_version=_CONTRACT_VERSION,
    name="aws",
    title="Amazon Web Services",
    maturity=BackendMaturity.STABLE,
    description=(
        "Shifter on AWS: ECS task execution, RDS, SQS, S3, Secrets Manager, and Cognito/OIDC identity, "
        "provisioned by the Terraform modules under platform/terraform (and the CloudFormation under "
        "platform/cloudformation) and deployed by the AWS workflow."
    ),
    supported_profiles=frozenset({"prod", "dev"}),
    settings_model=None,  # the AWS backend bundle migration (#1116) supplies the real schema
    required_tools=(
        RequiredTool(name="uv", purpose="run the Shifter installation tooling (shifter-config validate)"),
        RequiredTool(name="terraform", purpose="provision AWS infrastructure (platform/terraform)"),
        RequiredTool(name="aws", purpose="AWS CLI: authentication, Secrets Manager, and ECS deployment"),
        RequiredTool(name="docker", purpose="build the Shifter Platform container image"),
    ),
    required_secrets=(
        RequiredSecret(
            logical_name="django_secret_key",
            purpose="seeds the app secret bundle (Django SECRET_KEY) for the portal and workers",
            reference_grammar=(
                "an AWS Secrets Manager secret name or ARN, a GitHub Actions secret name, an environment "
                "variable, or the literal 'prompt'"
            ),
        ),
        RequiredSecret(
            logical_name="db_password",
            purpose="application database password",
            reference_grammar=(
                "an AWS Secrets Manager secret name or ARN, a GitHub Actions secret name, an environment "
                "variable, or the literal 'prompt'"
            ),
        ),
    ),
    generated_outputs=(
        _cloud_provider_output("aws backend runtime-env renderer"),
        *_secret_outputs(
            "aws backend runtime-env renderer",
            store="AWS Secrets Manager",
            app_name="APP_SECRET_ARN",
            db_name="DB_SECRET_ARN",
            kind=OutputKind.COMPAT_ALIAS,
        ),
    ),
    validation_checks=(_ROOT_CONFIG_CHECK,),
    health_checks=(_PORTAL_HEALTH_CHECK,),
    capabilities=_AWS_AND_GCP_CAPABILITIES,
    owned_files=OwnedFiles(
        infrastructure=("platform/terraform/modules", "platform/terraform/environments", "platform/cloudformation"),
        scripts=("scripts/bootstrap",),
        workflows=(".github/workflows/deploy.yml",),
        examples=("shifter/installation/examples/aws.yaml",),
        docs=("shifter/shifter_platform/documentation/docs/technical/dev/ci-cd.md",),
    ),
    docs=("docs/architecture/root-configured-backend-bundles.md", "shifter/installation/README.md"),
)

_GCP_BUNDLE = BackendBundle(
    contract_version=_CONTRACT_VERSION,
    name="gcp",
    title="Google Cloud Platform",
    maturity=BackendMaturity.STABLE,
    description=(
        "Shifter on GCP: GKE workloads, Cloud SQL, Pub/Sub, GCS, Secret Manager, and Identity Platform "
        "identity, provisioned by the Terraform configuration under platform/terraform/gcp with Kubernetes "
        "overlays under platform/k8s/gcp and the shared Helm chart under platform/charts/shifter."
    ),
    supported_profiles=frozenset({"prod", "dev"}),
    settings_model=None,  # the GCP backend bundle migration (#1117) supplies the real schema
    required_tools=(
        RequiredTool(name="uv", purpose="run the Shifter installation tooling (shifter-config validate)"),
        RequiredTool(name="terraform", purpose="provision GCP infrastructure (platform/terraform/gcp)"),
        RequiredTool(name="gcloud", purpose="Google Cloud SDK: authentication, GKE credentials, Secret Manager"),
        RequiredTool(name="helm", purpose="render and install the platform chart (platform/charts/shifter)"),
        RequiredTool(name="kubectl", purpose="apply Kubernetes manifests under platform/k8s/gcp"),
        RequiredTool(name="docker", purpose="build the Shifter Platform container image"),
    ),
    required_secrets=(
        RequiredSecret(
            logical_name="django_secret_key",
            purpose="seeds the app secret bundle (Django SECRET_KEY) for the portal and workers",
            reference_grammar=(
                "a Google Secret Manager resource name (projects/<project>/secrets/<name>/versions/<v>), a "
                "GitHub Actions secret name, an environment variable, or the literal 'prompt'"
            ),
        ),
    ),
    generated_outputs=(
        _cloud_provider_output("gcp backend runtime-env renderer (scripts/gcp/render_runtime_env.py)"),
        *_secret_outputs(
            "gcp backend runtime-env renderer (scripts/gcp/render_runtime_env.py)",
            store="Google Secret Manager",
            app_name="APP_SECRET_ID",
            db_name="DB_SECRET_ID",
            kind=OutputKind.RUNTIME_ENV,
        ),
    ),
    validation_checks=(_ROOT_CONFIG_CHECK,),
    health_checks=(_PORTAL_HEALTH_CHECK,),
    capabilities=_AWS_AND_GCP_CAPABILITIES,
    owned_files=OwnedFiles(
        infrastructure=("platform/terraform/gcp",),
        kubernetes=("platform/k8s/gcp", "platform/charts/shifter"),
        scripts=("scripts/gcp", "scripts/bootstrap"),
        workflows=(".github/workflows/_gcp-dev.yml",),
        examples=("shifter/installation/examples/gcp.yaml",),
        docs=("platform/terraform/gcp/README.md", "platform/k8s/gcp/README.md"),
    ),
    docs=("docs/architecture/root-configured-backend-bundles.md", "shifter/installation/README.md"),
)

#: The backend bundle registry: backend name -> bundle. Adding a backend is a new entry
#: here (plus its worked example under ``examples/``) and nothing else.
BACKEND_BUNDLES: dict[str, BackendBundle] = {
    _AWS_BUNDLE.name: _AWS_BUNDLE,
    _GCP_BUNDLE.name: _GCP_BUNDLE,
}


def get_backend_bundle(name: str) -> BackendBundle | None:
    """Return the backend bundle named ``name``, or ``None`` if no such backend exists."""
    return BACKEND_BUNDLES.get(name)


#: Backend names the root installation config accepts (derived from the registry).
KNOWN_BACKENDS: frozenset[str] = frozenset(BACKEND_BUNDLES)

#: Every deployment profile any backend supports (derived from the registry).
KNOWN_PROFILES: frozenset[str] = frozenset().union(*(bundle.supported_profiles for bundle in BACKEND_BUNDLES.values()))

#: Each backend mapped to the deployment profiles it supports (derived from the
#: registry). This is the lookup the root schema uses for the profile/backend
#: combination check; it carries over the ``ALLOWED_PROFILES`` data from the pre-#1113
#: ``installation.backends`` module unchanged.
ALLOWED_PROFILES: dict[str, frozenset[str]] = {
    name: bundle.supported_profiles for name, bundle in BACKEND_BUNDLES.items()
}
