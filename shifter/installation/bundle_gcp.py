"""The GCP (GKE) backend bundle definition.

Split out of :mod:`installation.registry` for the SonarCloud S104 file-size budget and
backend symmetry (mirroring ``settings_gcp`` / ``runtime_inventory_gcp``). Shared primitives
come from :mod:`installation._bundle_common`; the registry imports ``GCP_BUNDLE`` from here.
See the registry module docstring for the migration context (#1117 / GH #729, ADR-011-R5).
"""

from __future__ import annotations

from . import runtime_inventory_gcp
from ._bundle_common import (
    AWS_AND_GCP_CAPABILITIES,
    CONTRACT_VERSION,
    PORTAL_HEALTH_CHECK,
    ROOT_CONFIG_CHECK,
    SHIFTER_CHART_PATH,
)
from .contract import (
    BackendBundle,
    BackendMaturity,
    CommandSpec,
    GeneratedOutput,
    OutputDestination,
    OutputKind,
    OutputSensitivity,
    OwnedFiles,
    ProcessRole,
    RequiredSecret,
    RequiredTool,
    ValidationCheck,
)
from .gcp_model_broker import BROKER_RUNTIME_ENV_KEYS
from .settings_gcp import GcpBackendSettings

# The GCP generated runtime env is authored by the GCP backend runtime-env renderer and its
# key set is owned by ``runtime_inventory_gcp``. The bundle's generated outputs are built from
# that single source so the contract projection and the runtime inventory cannot drift (a
# conformance test asserts the two agree).
_GCP_RENDERER = "gcp backend runtime-env renderer (scripts/gcp/render_runtime_env.py)"

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
        "GDC_VM_IMAGE_GCS_SECRET_ID",
        "GDC_VMSERIES_BOOTSTRAP_XML_TEMPLATE_SECRET_ID",
        "GDC_VMSERIES_IMAGE_GCS_SECRET_ID",
        "GCP_RANGE_VERTEX_SHARED_KEY_SECRET_ID",
        "DC_DOMAIN_PASSWORD_SECRET_ID",
        "EMAIL_API_KEY_SECRET_ID",
    }
)


def _gcp_output_roles(name: str) -> tuple[ProcessRole, ...]:
    """The exact ProcessRole consumers of one GCP generated runtime-env key.

    Every generated key rides the shared runtime env the portal/worker platform image
    loads, so portal and worker always consume it. The standalone provisioner Job receives
    only the forwarded subset the platform task runner propagates
    (``runtime_inventory_gcp.GCP_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS``, kept in parity with
    ``engine.ecs._GCP_PROVISIONER_ENV_KEYS``). Among those, the ``GCP_RANGE_*`` keys are the
    range-guest realization configuration the provisioner applies to range tasks, so they
    also declare the range-task consumer. This is derived per key, not a blanket assignment.
    """
    roles: list[ProcessRole] = [ProcessRole.PORTAL, ProcessRole.WORKER]
    if name in runtime_inventory_gcp.GCP_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS:
        roles.append(ProcessRole.PROVISIONER)
        if name.startswith("GCP_RANGE_") and name not in _GCP_SECRET_REFERENCE_RUNTIME_KEYS:
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

    Built from ``runtime_inventory_gcp``'s required and optional GCP key sets so the contract's
    generated outputs are exactly the keys the renderer emits — enumerated, not just the
    handful the provisional entry carried.
    """
    required = sorted(runtime_inventory_gcp.GCP_GENERATED_RUNTIME_ENV_KEYS)
    optional = sorted(runtime_inventory_gcp.GCP_OPTIONAL_GENERATED_RUNTIME_ENV_KEYS)
    return (
        *(
            GeneratedOutput(
                name=name,
                kind=OutputKind.RUNTIME_ENV,
                owner="canonical model broker Helm projection",
                source="validated deployment transport and mounted catalog identity",
                destination=OutputDestination.RUNTIME_ENV,
                sensitivity=OutputSensitivity.PUBLIC,
                process_roles=(ProcessRole.MODEL_BROKER,),
                description="Broker-only configuration or mounted-file path; never a credential value.",
            )
            for name in sorted(BROKER_RUNTIME_ENV_KEYS)
        ),
        *(_gcp_runtime_output(name, optional=False) for name in required),
        *(_gcp_runtime_output(name, optional=True) for name in optional),
    )


# Canonical pre-mutation validation front doors for the GCP bundle. Each is a pure,
# repository-relative argv array whose executable is a declared required tool. They are the
# fast, credential-free checks a setup/doctor flow runs before touching infrastructure;
# the fuller pre-mutation suite (tflint with init, kubeconform, runtime-env rendering from
# representative Terraform outputs, admission parity) stays CI-enforced in _gcp-dev.yml.
_GCP_VALIDATION_CHECKS: tuple[ValidationCheck, ...] = (
    ROOT_CONFIG_CHECK,
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
            argv=("helm", "template", SHIFTER_CHART_PATH),
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


GCP_BUNDLE = BackendBundle(
    contract_version=CONTRACT_VERSION,
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
    health_checks=(PORTAL_HEALTH_CHECK,),
    capabilities=AWS_AND_GCP_CAPABILITIES,
    owned_files=OwnedFiles(
        infrastructure=("platform/terraform/gcp",),
        kubernetes=("platform/k8s/gcp", SHIFTER_CHART_PATH),
        scripts=("scripts/gcp", "scripts/bootstrap"),
        workflows=(".github/workflows/_gcp-dev.yml",),
        examples=("shifter/installation/examples/gcp.yaml",),
        docs=("platform/terraform/gcp/README.md", "platform/k8s/gcp/README.md"),
    ),
    docs=("docs/architecture/root-configured-backend-bundles.md", "shifter/installation/README.md"),
)
