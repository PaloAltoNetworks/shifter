"""The Shifter backend bundle registry.

This is the single source of truth for which backends an OSS deployment can select
(PLAT-2002) and what each one exposes (the :mod:`installation.contract` shape,
PLAT-2003). The root schema (:mod:`installation.schema`) derives backend and profile
validation from the data here, and :mod:`installation.loader` runs each backend's
``settings`` and secret-reference checks against the selected bundle — so adding a
backend or a profile is a registry entry, not a schema change or a branch router. There
is exactly one such table in the repo; Django, workflows, bootstrap scripts, and CI
consume *this* one rather than maintaining their own.

The ``aws`` (#1116 / GH #728) and ``gcp`` (#1117 / GH #729) entries below are both migrated
backend bundles. Each carries a closed ``settings_model`` (:class:`AwsSettings` /
:class:`installation.settings_gcp.GcpBackendSettings`), machine-readable
``RequiredSecret.reference_pattern`` secret grammars, the full generated runtime-env
projection, the deployment profiles its deploy paths actually use, and the backend identity,
owned repo roots, required tools, root-config validation check, and portal health probe.
Describing these contracts does not move Terraform/state, rewrite workflows, or build a
renderer — those stay in their existing owners (branch-routing replacement is #730);
constrained by ADR-011-R5.

``range_egress`` is a *shared, cross-backend* platform setting owned and validated by
:mod:`installation.range_egress` (verbatim, non-secret CIDR diagnostics, #775). It is not a
backend-owned key, so the closed ``settings_model`` classes deliberately do not declare it;
the loader strips it out of ``settings`` and validates it separately for every backend. The
``local`` backend is #1119. Constrained by ADR-011.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from . import runtime_inventory
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
from .settings_gcp import GcpBackendSettings

# The contract-shape version every bundle below is written against. Pinned literally so
# that adding a future ``contract_version`` to ``SUPPORTED_CONTRACT_VERSIONS`` does not
# silently re-version these bundles — a new version requires an intentional edit here
# (and a settings/renderer migration for the backend).
_CONTRACT_VERSION = 1

# A plausible AWS region token: two letters, one or more lowercase words, then a trailing
# number — ``us-east-2``, ``us-gov-east-1``, ``ap-southeast-4``. Deliberately permissive:
# the exact region set is an AWS concern validated at deploy time, so this only catches
# config-time typos (wrong case, underscores, missing number) rather than pinning a list.
# It is applied via ``Field(pattern=...)`` (not a ``@field_validator``) so the *same*
# constraint governs both runtime validation and the published JSON schema — a validator
# would enforce it at load time while leaving the published contract permitting any string
# (the boundary-contract gap #728 must not open).
_AWS_REGION_PATTERN = r"^[a-z]{2}(?:-[a-z]+)+-\d+$"

# The reference grammar shared by both AWS secrets: an AWS Secrets Manager secret name or
# ARN, a GitHub Actions secret name, or an environment variable name — a single-line token
# of reference-safe characters, matched full-string by ``RequiredSecret.matches_reference``
# (which accepts ``prompt`` independently). This is a *positive* grammar layered on top of
# the root schema's raw-material rejection (multi-line / PEM / over-long), not a duplicate
# of it; it never sees or echoes the value.
_AWS_REFERENCE_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._/+=@:-]*"

# The reference_grammar description shared by both AWS secrets (kept in one place so the
# human text and the machine pattern stay in step).
_AWS_REFERENCE_GRAMMAR = (
    "an AWS Secrets Manager secret name or ARN, a GitHub Actions secret name, an environment "
    "variable, or the literal 'prompt'"
)


class AwsSettings(BaseModel):
    """Closed operator-intent settings for the AWS backend (PLAT-2006, GH #728).

    Only genuine operator intent lives here. Terraform variables, generated runtime
    outputs, workflow secret names, and provider SDK payloads are *not* settings — copying
    them in would turn ``settings`` into a second provider schema (preflight #728).
    ``extra='forbid'`` fails unknown AWS settings closed, so a typo or a stale key is a
    config-time error rather than a silently-ignored value.

    The shared cross-backend ``range_egress`` policy is intentionally *absent*: it is owned
    and validated by :mod:`installation.range_egress` (which surfaces verbatim, non-secret
    CIDR diagnostics, #775), and the loader validates it separately for every backend. See
    the module docstring.
    """

    model_config = ConfigDict(extra="forbid")

    region: str = Field(pattern=_AWS_REGION_PATTERN)


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

# Anchored grammar for a GCP ``django_secret_key`` reference: a Google Secret Manager
# resource name (``projects/<project>/secrets/<name>/versions/<version>``), or a
# GitHub Actions secret name / environment variable identifier. ``prompt`` is accepted
# separately by ``RequiredSecret.matches_reference``. AWS Secrets Manager paths
# (``shifter/prod/...``) are intentionally not valid GCP references.
_GCP_SECRET_REFERENCE_PATTERN = (
    # An anchored (^...$) reference grammar, not a credential — silence the hardcoded-secret
    # heuristics. Anchoring is explicit so the *published* pattern enforces the same full-string
    # grammar as ``RequiredSecret.matches_reference`` (which applies re.fullmatch), rather than
    # letting an external consumer's re.match/re.search accept substring garbage.
    r"^(?:projects/[^/\s]+/secrets/[^/\s]+/versions/[^/\s]+|[A-Za-z_][A-Za-z0-9_]*)$"  # noqa: S105 # nosec B105
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
    # prod / dev are the OSS profiles; proof is the internal new-tenant readiness tier that
    # has its own Terraform root (platform/terraform/environments/proof) and aws-proof
    # deploy path (.github/workflows/deploy.yml, _core.yml, _range.yml). Admit it explicitly
    # rather than strand a real environment the deploy paths already target (preflight #728).
    supported_profiles=frozenset({"prod", "dev", "proof"}),
    # Migrated by #1116 / GH #728: the closed operator-intent schema, no longer None.
    settings_model=AwsSettings,
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
            reference_grammar=_AWS_REFERENCE_GRAMMAR,
            reference_pattern=_AWS_REFERENCE_PATTERN,
        ),
        RequiredSecret(
            logical_name="db_password",
            purpose="application database password",
            reference_grammar=_AWS_REFERENCE_GRAMMAR,
            reference_pattern=_AWS_REFERENCE_PATTERN,
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
        docs=("docs/technical/dev/ci-cd.md",),
    ),
    docs=("docs/architecture/root-configured-backend-bundles.md", "shifter/installation/README.md"),
)

# The GCP generated runtime env is authored by the GCP backend runtime-env renderer and
# its key set is owned by ``installation.runtime_inventory``. The bundle's generated
# outputs are built from that single source so the contract projection and the runtime
# inventory cannot drift (a conformance test asserts the two agree).
_GCP_RENDERER = "gcp backend runtime-env renderer (scripts/gcp/render_runtime_env.py)"

# Generated runtime-env keys whose *value* is a Google Secret Manager reference (fetched
# at startup by entrypoint.sh); the reference id rides the ConfigMap-bound env, the value
# never does. Everything else is public runtime configuration.
_GCP_SECRET_REFERENCE_RUNTIME_KEYS: frozenset[str] = frozenset(
    {
        "APP_SECRET_ID",
        "DB_SECRET_ID",
        "REDIS_SECRET_ID",
        "GUACAMOLE_SECRET_ID",
        "GDC_ACCESS_SECRET_ID",
        "DC_DOMAIN_PASSWORD_SECRET_ID",
        "EMAIL_API_KEY_SECRET_ID",
    }
)


def _gcp_output_roles(name: str) -> tuple[ProcessRole, ...]:
    """The exact ProcessRole consumers of one GCP generated runtime-env key.

    Every generated key rides the shared runtime env the portal/worker platform image
    loads, so portal and worker always consume it. The standalone provisioner Job receives
    only the forwarded subset the platform task runner propagates
    (``runtime_inventory.GCP_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS``, kept in parity with
    ``engine.ecs._GCP_PROVISIONER_ENV_KEYS``). Among those, the ``GCP_RANGE_*`` keys are the
    range-guest realization configuration the provisioner applies to range tasks, so they
    also declare the range-task consumer. This is derived per key, not a blanket assignment.
    """
    roles: list[ProcessRole] = [ProcessRole.PORTAL, ProcessRole.WORKER]
    if name in runtime_inventory.GCP_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS:
        roles.append(ProcessRole.PROVISIONER)
        if name.startswith("GCP_RANGE_"):
            roles.append(ProcessRole.RANGE_TASK)
    return tuple(roles)


def _gcp_runtime_output(name: str, *, optional: bool) -> GeneratedOutput:
    """Build one classified GCP generated runtime-env output."""
    optional_note = " Optional; emitted only when the deployment configures it." if optional else ""
    roles = _gcp_output_roles(name)
    if name in _GCP_SECRET_REFERENCE_RUNTIME_KEYS:
        return GeneratedOutput(
            name=name,
            kind=OutputKind.RUNTIME_ENV,
            owner=_GCP_RENDERER,
            source="a Google Secret Manager reference rendered from the Terraform runtime_secret_ids output",
            destination=OutputDestination.RUNTIME_ENV,
            sensitivity=OutputSensitivity.SECRET_REFERENCE,
            process_roles=roles,
            description=(
                f"Reference to the {name} secret in the platform runtime environment; the process fetches the "
                f"value from Google Secret Manager at startup (entrypoint.sh) — a reference only, the secret "
                f"value stays in Secret Manager.{optional_note}"
            ),
        )
    api_key_note = (
        " Browser client configuration for Identity Platform, not an authentication secret: it is public, "
        "but must not be dumped through logs or error messages."
        if name == "IDENTITY_PLATFORM_API_KEY"
        else ""
    )
    return GeneratedOutput(
        name=name,
        kind=OutputKind.RUNTIME_ENV,
        owner=_GCP_RENDERER,
        source="rendered from validated Terraform outputs and the normalized root config",
        destination=OutputDestination.RUNTIME_ENV,
        sensitivity=OutputSensitivity.PUBLIC,
        process_roles=roles,
        description=(
            f"Public GCP runtime configuration value ({name}) emitted into the platform runtime "
            f"environment.{api_key_note}{optional_note}"
        ),
    )


def _gcp_generated_outputs() -> tuple[GeneratedOutput, ...]:
    """The full GCP generated runtime-env projection, classified and sorted by key name.

    Built from ``runtime_inventory``'s required and optional GCP key sets so the contract's
    generated outputs are exactly the keys the renderer emits — enumerated, not just the
    handful the provisional entry carried.
    """
    required = sorted(runtime_inventory.GCP_GENERATED_RUNTIME_ENV_KEYS)
    optional = sorted(runtime_inventory.GCP_OPTIONAL_GENERATED_RUNTIME_ENV_KEYS)
    return (
        *(_gcp_runtime_output(name, optional=False) for name in required),
        *(_gcp_runtime_output(name, optional=True) for name in optional),
    )


# Canonical pre-mutation validation front doors for the GCP bundle. Each is a pure,
# repository-relative argv array whose executable is a declared required tool. They are the
# fast, credential-free checks a setup/doctor flow runs before touching infrastructure;
# the fuller pre-mutation suite (tflint with init, kubeconform, runtime-env rendering from
# representative Terraform outputs, admission parity) stays CI-enforced in _gcp-dev.yml.
_GCP_VALIDATION_CHECKS: tuple[ValidationCheck, ...] = (
    _ROOT_CONFIG_CHECK,
    ValidationCheck(
        name="terraform-fmt",
        command=CommandSpec(
            argv=("terraform", "fmt", "-check", "-recursive", "platform/terraform/gcp"),
            description="Check the GCP Terraform is canonically formatted.",
        ),
        description="Fail on unformatted GCP Terraform before planning or applying.",
    ),
    ValidationCheck(
        name="helm-template",
        command=CommandSpec(
            argv=("helm", "template", "platform/charts/shifter"),
            description="Render the shared platform Helm chart to catch template errors.",
        ),
        description="Fail closed if the platform chart does not render.",
    ),
    ValidationCheck(
        name="kustomize-render",
        command=CommandSpec(
            argv=("kubectl", "kustomize", "platform/k8s/gcp/overlays/gcp-dev"),
            description="Render the GCP Kubernetes overlay to catch kustomize errors.",
        ),
        description="Fail closed if the GCP Kubernetes overlay does not render.",
    ),
    ValidationCheck(
        name="kube-linter",
        command=CommandSpec(
            argv=("kube-linter", "lint", "--config", ".kube-linter.yaml", "platform/k8s/gcp/"),
            description="Lint the GCP Kubernetes manifests for workload security posture.",
        ),
        description="Enforce the Kubernetes workload security posture (PSS, capabilities, limits).",
    ),
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
    settings_model=GcpBackendSettings,
    required_tools=(
        RequiredTool(name="uv", purpose="run the Shifter installation tooling (shifter-config validate)"),
        RequiredTool(name="terraform", purpose="provision GCP infrastructure (platform/terraform/gcp)"),
        RequiredTool(name="gcloud", purpose="Google Cloud SDK: authentication, GKE credentials, Secret Manager"),
        RequiredTool(name="helm", purpose="render and install the platform chart (platform/charts/shifter)"),
        RequiredTool(name="kubectl", purpose="apply Kubernetes manifests under platform/k8s/gcp"),
        RequiredTool(
            name="kube-linter",
            purpose="lint the GCP Kubernetes manifests (platform/k8s/gcp) for security posture",
        ),
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
            reference_pattern=_GCP_SECRET_REFERENCE_PATTERN,
        ),
    ),
    generated_outputs=_gcp_generated_outputs(),
    validation_checks=_GCP_VALIDATION_CHECKS,
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
