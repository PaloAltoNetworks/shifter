"""The AWS (EKS) backend bundle definition.

Split out of :mod:`installation.registry` for the SonarCloud S104 file-size budget and
backend symmetry (mirroring ``settings_aws`` / ``runtime_inventory_aws``). Shared primitives
come from :mod:`installation._bundle_common`; the registry imports ``AWS_BUNDLE`` from here.
See the registry module docstring for the migration context (#1116 / GH #728, ADR-011-R5).
"""

from __future__ import annotations

from . import runtime_inventory_aws
from ._bundle_common import (
    AWS_AND_GCP_CAPABILITIES,
    CONTRACT_VERSION,
    PORTAL_HEALTH_CHECK,
    ROOT_CONFIG_CHECK,
    ROOT_CONFIG_PATH,
    SHIFTER_CHART_PATH,
    cloud_provider_output,
    secret_outputs,
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
from .settings_aws import AWS_REFERENCE_GRAMMAR, AWS_REFERENCE_PATTERN, AwsSettings

# The AWS platform runtime env is authored by the AWS backend runtime-env renderer
# (scripts/bootstrap/aws_eks.py render_aws_values). Its complete emitted key set is owned by
# ``runtime_inventory_aws``. The bundle's generated outputs are built from that single source
# so the contract projection and the renderer cannot drift (an oracle test asserts they agree).
_AWS_RENDERER = "aws backend runtime-env renderer (scripts/bootstrap/aws_eks.py render_aws_values)"

# Generated runtime-env keys whose *value* is an AWS Secrets Manager reference (fetched at
# startup by entrypoint.sh); the reference id rides the ConfigMap-bound env, the value never
# does. Everything else in the AWS runtime projection is public runtime configuration.
_AWS_SECRET_REFERENCE_RUNTIME_KEYS: frozenset[str] = frozenset({"OIDC_SECRET_ID"})


def _aws_output_roles(name: str) -> tuple[ProcessRole, ...]:
    """The exact ProcessRole consumers of one AWS generated runtime-env key.

    Every generated key rides the shared runtime env the portal/worker platform image loads,
    so portal and worker always consume it. The standalone provisioner Job receives the
    forwarded subset the platform launcher propagates
    (``runtime_inventory_aws.AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS``), so those keys
    (including the range/portal topology and range-realization keys) also declare the
    provisioner consumer. This is derived per key, not a blanket assignment. AWS ranges are
    delivered on ECS/VM rather than as Kubernetes range-task pods, so no projection key
    declares the range-task consumer (contrast the GCP bundle's GDC range pods).
    """
    roles: list[ProcessRole] = [ProcessRole.PORTAL, ProcessRole.WORKER]
    if name in runtime_inventory_aws.AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS:
        roles.append(ProcessRole.PROVISIONER)
    return tuple(roles)


def _aws_runtime_output(name: str) -> GeneratedOutput:
    """Build one classified AWS generated runtime-env output."""
    if name == "CLOUD_PROVIDER":
        return cloud_provider_output(_AWS_RENDERER)
    roles = _aws_output_roles(name)
    if name in _AWS_SECRET_REFERENCE_RUNTIME_KEYS:
        return GeneratedOutput(
            name=name,
            kind=OutputKind.RUNTIME_ENV,
            owner=_AWS_RENDERER,
            source="an AWS Secrets Manager reference rendered from validated Terraform outputs",
            destination=OutputDestination.RUNTIME_ENV,
            sensitivity=OutputSensitivity.SECRET_REFERENCE,
            process_roles=roles,
            description=(
                f"Reference to the {name} secret in the platform runtime environment; the process fetches the "
                f"value from AWS Secrets Manager at startup (entrypoint.sh) — a reference only, the secret value "
                f"stays in Secrets Manager."
            ),
        )
    return GeneratedOutput(
        name=name,
        kind=OutputKind.RUNTIME_ENV,
        owner=_AWS_RENDERER,
        source="rendered from validated Terraform outputs and the normalized root config",
        destination=OutputDestination.RUNTIME_ENV,
        sensitivity=OutputSensitivity.PUBLIC,
        process_roles=roles,
        description=f"Public AWS runtime configuration value ({name}) emitted into the platform runtime environment.",
    )


def _aws_generated_outputs() -> tuple[GeneratedOutput, ...]:
    """The full AWS generated runtime-env projection, plus the ``*_SECRET_ARN`` compat aliases.

    The RUNTIME_ENV projection is built from ``runtime_inventory_aws.AWS_GENERATED_RUNTIME_ENV_KEYS``
    (the complete set the renderer emits into the ConfigMap: required, renderer-owned, and the
    range/portal topology the Terraform provisioner_env re-supplies, minus hydrated-secret keys)
    so the contract's generated outputs are exactly the keys the renderer emits, sorted by name.
    Hydrated-secret keys are excluded: a value hydrated from a secret reference after startup is
    not a renderer-emitted ConfigMap value. An oracle test (``test_aws_eks``) asserts a
    representative ``render_aws_values`` emits exactly this classified set.
    """
    projection = sorted(runtime_inventory_aws.AWS_GENERATED_RUNTIME_ENV_KEYS)
    return (
        *(_aws_runtime_output(name) for name in projection),
        *secret_outputs(
            _AWS_RENDERER,
            store="AWS Secrets Manager",
            app_name="APP_SECRET_ARN",
            db_name="DB_SECRET_ARN",
            kind=OutputKind.COMPAT_ALIAS,
        ),
    )


# Canonical pre-mutation validation front doors for the AWS bundle. Each is a pure,
# repository-relative argv array whose executable is a declared required tool — the fast,
# credential-free checks a setup/doctor flow runs before touching infrastructure. AWS has no
# ``platform/k8s/aws`` overlay; its Kubernetes surface is the shared chart, so helm-template
# (rendered with the AWS profile values) is the k8s front door rather than a kustomize
# overlay render or a raw-manifest kube-linter pass. The fuller pre-mutation suite (tflint
# with init, checkov, kube-linter/kubeconform on the rendered chart, and effective-values
# schema validation) stays CI-enforced and in the deploy lifecycle.
_AWS_VALIDATION_CHECKS: tuple[ValidationCheck, ...] = (
    ROOT_CONFIG_CHECK,
    ValidationCheck(
        name="terraform-fmt",
        command=CommandSpec(
            argv=("terraform", "fmt", "-check", "-recursive", "platform/terraform/environments"),
            description="Check the AWS Terraform deployment roots are canonically formatted.",
        ),
        description="Fail on unformatted AWS Terraform before planning or applying.",
    ),
    ValidationCheck(
        name="helm-template",
        command=CommandSpec(
            argv=(
                "helm",
                "template",
                SHIFTER_CHART_PATH,
                "--values",
                "platform/charts/shifter/values-aws-dev.yaml",
            ),
            description="Render the shared platform chart with the AWS profile values to catch template/value errors.",
        ),
        description="Fail closed if the platform chart does not render with the AWS values projection.",
    ),
    # Connect doctor to the canonical EKS deploy preflight rather than re-listing its checks
    # (ADR-011 lifecycle boundary): preflight derives cloud+profile from the same shifter.yaml
    # and runs the eks component, so doctor and the deploy lifecycle share one prerequisite
    # contract (tools plus the isolated EKS root/backend inputs) instead of drifting apart.
    ValidationCheck(
        name="eks-preflight",
        command=CommandSpec(
            argv=(
                "python3",
                "scripts/bootstrap/preflight.py",
                "--config",
                ROOT_CONFIG_PATH,
                "--component",
                "eks",
                "--mode",
                "local",
                "--headless",
            ),
            description="Run the canonical EKS deploy preflight (tools + EKS root/backend inputs) for the profile.",
        ),
        description="Detect missing EKS prerequisites and root/backend inputs before deploy via the shared preflight.",
    ),
)


AWS_BUNDLE = BackendBundle(
    contract_version=CONTRACT_VERSION,
    name="aws",
    title="Amazon Web Services",
    maturity=BackendMaturity.STABLE,
    description=(
        "Shifter on AWS: platform workloads run on EKS through the shared Helm chart, while ECS remains "
        "the private range task transport alongside RDS, SQS, S3, Secrets Manager, and Cognito/OIDC."
    ),
    # prod / dev are the OSS profiles; proof is the internal new-tenant readiness tier that
    # has its own Terraform root (platform/terraform/environments/proof) and aws-proof
    # deploy path (.github/workflows/deploy.yml, _core.yml, _range.yml). Admit it explicitly
    # rather than strand a real environment the deploy paths already target (preflight #728).
    supported_profiles=frozenset({"prod", "dev", "proof"}),
    # Migrated by #1116 / GH #728: the closed operator-intent schema, no longer None.
    settings_model=AwsSettings,
    deploy=CommandSpec(
        argv=("python3", "scripts/bootstrap/deploy.py", "eks-deploy", "--config", ROOT_CONFIG_PATH),
        description="Deploy the AWS EKS bundle selected by the validated root config.",
    ),
    teardown=CommandSpec(
        argv=("python3", "scripts/bootstrap/deploy.py", "eks-teardown", "--config", ROOT_CONFIG_PATH),
        description="Tear down only the AWS EKS bundle selected by the validated root config.",
    ),
    required_tools=(
        RequiredTool(name="python3", purpose="run the explicit backend lifecycle entrypoint"),
        RequiredTool(name="uv", purpose="run the Shifter installation tooling (shifter-config validate)"),
        RequiredTool(name="terraform", purpose="provision AWS infrastructure (platform/terraform)"),
        RequiredTool(name="aws", purpose="AWS CLI: authentication, EKS access, Secrets Manager, and ECS tasks"),
        RequiredTool(name="docker", purpose="build the Shifter Platform container image"),
        RequiredTool(name="helm", purpose="validate and atomically roll out the shared Shifter chart"),
        RequiredTool(name="kubectl", purpose="validate bounded EKS access and inspect rollout health"),
    ),
    required_secrets=(
        RequiredSecret(
            logical_name="django_secret_key",
            purpose="seeds the app secret bundle (Django SECRET_KEY) for the portal and workers",
            reference_grammar=AWS_REFERENCE_GRAMMAR,
            reference_pattern=AWS_REFERENCE_PATTERN,
        ),
        RequiredSecret(
            logical_name="db_password",
            purpose="application database password",
            reference_grammar=AWS_REFERENCE_GRAMMAR,
            reference_pattern=AWS_REFERENCE_PATTERN,
        ),
    ),
    generated_outputs=_aws_generated_outputs(),
    validation_checks=_AWS_VALIDATION_CHECKS,
    health_checks=(PORTAL_HEALTH_CHECK,),
    capabilities=AWS_AND_GCP_CAPABILITIES,
    owned_files=OwnedFiles(
        infrastructure=("platform/terraform/modules", "platform/terraform/environments", "platform/cloudformation"),
        kubernetes=(SHIFTER_CHART_PATH,),
        scripts=("scripts/bootstrap",),
        workflows=(".github/workflows/deploy.yml",),
        examples=("shifter/installation/examples/aws.yaml",),
        docs=(
            "docs/technical/dev/ci-cd.md",
            "docs/technical/platform_infrastructure/aws-eks-bundle.md",
            "docs/how-to/aws-ecs-to-eks-migration.md",
        ),
    ),
    docs=(
        "docs/architecture/root-configured-backend-bundles.md",
        "docs/technical/platform_infrastructure/aws-eks-bundle.md",
        "shifter/installation/README.md",
    ),
)
