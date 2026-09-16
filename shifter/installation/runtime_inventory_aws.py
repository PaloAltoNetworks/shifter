"""AWS (EKS) backend runtime-env key inventories.

Split out of ``runtime_inventory`` for GCP symmetry (its GCP counterpart lives in
``runtime_inventory_gcp``) and so that module stays within the file-size budget
(SonarCloud S104). These frozensets are re-exported by ``runtime_inventory`` for
its existing public import surface (``scripts/bootstrap/aws_eks.py`` and
``engine.ecs`` import the required/forwarded sets from there); the registry and
the AWS bundle parity test import the full AWS set directly from this module.

The building-block sets are:

- ``AWS_EKS_REQUIRED_RUNTIME_ENV_KEYS`` — public settings and secret references
  the renderer validates as present before Helm may mutate a release.
- ``AWS_RENDERER_OWNED_RUNTIME_ENV_KEYS`` — keys the renderer sets itself (and
  forbids the Terraform ``runtime_env`` from overriding).
- ``AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS`` — the runtime-env contract the
  standalone provisioner Job receives from the platform launcher. It mirrors the
  ECS task-definition env, which is exactly what the ``eks-provisioner-env``
  Terraform module's ``provisioner_env`` block re-supplies into the merged
  runtime env, so it is the canonical surface for the range/portal topology keys
  the renderer emits (kept in parity with ``engine.ecs`` by
  ``tests/shared/cloud/test_aws_runtime_role_parity.py``).
- ``AWS_PROVISIONER_HYDRATED_SECRET_KEYS`` — forwarded keys whose *value* is
  hydrated from a secret store after process startup (``DC_DOMAIN_PASSWORD``).
  The launcher injects them as secret references, and the Terraform
  ``provisioner_env`` deliberately excludes them, so they never enter the
  ConfigMap-bound runtime env.

``AWS_GENERATED_RUNTIME_ENV_KEYS`` is the complete set of keys the renderer emits
into the ConfigMap-bound runtime env, mirroring the Terraform
``merged_runtime_env = merge(var.runtime_env, local.provisioner_env,
var.extra_env)`` plus the renderer-owned keys. The backend bundle's
generated-output projection is derived from it so the published contract and the
renderer cannot drift, and an oracle test runs ``render_aws_values`` against a
representative Terraform output to assert the emitted keys equal that classified
set. Hydrated-secret keys are excluded because a value hydrated from a secret
reference after startup is not a renderer-emitted ConfigMap value.
"""

from __future__ import annotations

# Public settings and secret references that an AWS EKS deployment must project
# into the shared chart. The EKS lifecycle validates this inventory before Helm
# can mutate a release, so a new runtime consumer cannot silently disappear from
# the provider renderer.
AWS_EKS_REQUIRED_RUNTIME_ENV_KEYS: frozenset[str] = frozenset(
    {
        "AWS_REGION",
        # ENGINE_TASK_* ECS coordinates are retired (#1826). The AWS provisioner
        # dispatches as a Kubernetes Job: ENGINE_TASK_NAMESPACE and
        # ENGINE_TASK_SERVICE_ACCOUNT_NAME are set by the chart, ENGINE_TASK_IMAGE
        # is renderer-generated (aws_eks.render_aws_values), and the range/portal
        # provisioner env is assembled by the eks-provisioner-env Terraform module
        # (AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS), not required as a deploy
        # tooling input here.
        "OIDC_AUTH_DOMAIN",
        "OIDC_ISSUER_URL",
        "OIDC_RP_CLIENT_ID",
        "OIDC_SECRET_ID",
        "QUEUE_CMS_CONSUMER_ID",
        "QUEUE_CMS_PUBLISHER_ID",
        "QUEUE_ENGINE_CONSUMER_ID",
        "QUEUE_ENGINE_PUBLISHER_ID",
        "QUEUE_MC_CONSUMER_ID",
        "QUEUE_MC_PUBLISHER_ID",
        "RANGE_EVENTS_TOPIC_ID",
        "STORAGE_BUCKET_NAME",
    }
)

# Runtime-env keys the AWS renderer sets itself (aws_eks._runtime_env). The
# renderer forbids the Terraform ``runtime_env`` output from supplying these, so
# they are guaranteed present in the rendered runtime env. This is the single
# source of truth for the renderer-owned set: ``aws_eks.py`` imports it, and the
# backend bundle's generated-output projection is built from it, so the renderer
# and the published contract cannot drift.
AWS_RENDERER_OWNED_RUNTIME_ENV_KEYS: frozenset[str] = frozenset(
    {
        "AUTH_PROVIDER",
        "CLOUD_PROVIDER",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        # ENGINE_TASK_IMAGE is generated from the attested provisioner image
        # digest (mirrors GCP's render_runtime_env.py); the Terraform runtime_env
        # must not supply it.
        "ENGINE_TASK_IMAGE",
        "ENVIRONMENT",
        # Mission Control lease policy (#27): rendered from the validated
        # settings.mission_control_leases block, not the Terraform runtime_env.
        "MISSION_CONTROL_LEASE_POLICY_JSON",
        "MODEL_ACCESS_CATALOG_DIGEST",
        "MODEL_ACCESS_CATALOG_PATH",
        "MODEL_ACCESS_ENABLED",
        "SITE_URL",
    }
)

# The runtime-env keys the standalone AWS (EKS) provisioner Job receives (#1826).
# On EKS the provisioner dispatches as a Kubernetes Job with no ECS task
# definition, so the platform launcher worker forwards this contract from the
# platform runtime env. The installation package is standalone (it must not import
# the Django platform), so the set is declared here as data; a platform-side
# parity test (``tests/shared/cloud/test_aws_runtime_role_parity.py``) fails if it
# drifts from the authoritative forwarding list ``engine.ecs._AWS_PROVISIONER_ENV_KEYS``.
# It mirrors the environment the AWS provisioner previously received from its ECS
# task definition (``platform/terraform/modules/engine-provisioner/task_definition.tf``).
AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS: frozenset[str] = frozenset(
    {
        "CLOUD_PROVIDER",
        "ENVIRONMENT",
        "AWS_REGION",
        "SECRETS_KMS_KEY_ARN",
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "STATE_BUCKET_URL",
        "RANGE_VPC_ID",
        "RANGE_VPC_CIDR",
        "RANGE_ROUTE_TABLE_ID",
        "RANGE_AVAILABILITY_ZONE",
        "RANGE_VPN_EDGE_SUBNET_ID",
        "RANGE_VPN_GATEWAY_PERMISSIONS_BOUNDARY_ARN",
        "RANGE_VPN_PROVIDER_ENDPOINT_SECURITY_GROUP_ID",
        "RANGE_INSTANCE_PROFILE_NAME",
        "RANGE_INSTANCE_ROLE_ARN",
        "RANGE_EGRESS_MODE",
        "KALI_AMI_ID",
        "VICTIM_AMI_ID",
        "WINDOWS_AMI_ID",
        "DC_AMI_ID",
        "DC_DOMAIN_NAME",
        "KALI_INSTANCE_TYPE",
        "VICTIM_INSTANCE_TYPE",
        "AGENT_S3_BUCKET",
        "S3_ENDPOINT_ID",
        "FIREWALL_ENDPOINT_ID",
        "SSM_ENDPOINTS_SUBNET_CIDR",
        "PORTAL_VPC_CIDR",
        "PORTAL_VPC_PEERING_ID",
        "NGFW_AMI_ID",
        "NGFW_INSTANCE_TYPE",
        "NGFW_MGMT_SECURITY_GROUP_ID",
        "NGFW_DATA_SECURITY_GROUP_ID",
        "NGFW_VPC_ID",
        "NGFW_SUBNET_ID",
        "NGFW_SUBNET_CIDR",
        "NGFW_BOOTSTRAP_BUCKET",
        "NGFW_INSTANCE_PROFILE_NAME",
        "AWS_POLARIS_AGENT_REGION",
        "AWS_POLARIS_AGENT_MAIN_MODEL_ID",
        "AWS_POLARIS_AGENT_SMALL_MODEL_ID",
        "AWS_POLARIS_AGENT_MAIN_INFERENCE_PROFILE_ARN",
        "AWS_POLARIS_AGENT_SMALL_INFERENCE_PROFILE_ARN",
        "AWS_POLARIS_AGENT_MAIN_BACKING_MODEL_ARNS",
        "AWS_POLARIS_AGENT_SMALL_BACKING_MODEL_ARNS",
        "AWS_POLARIS_AGENT_STS_SESSION_DURATION_SECONDS",
        "AWS_POLARIS_AGENT_REFRESH_WINDOW_SECONDS",
        "AWS_POLARIS_AGENT_PERMISSIONS_BOUNDARY_ARN",
        "DC_DOMAIN_PASSWORD",
    }
)

# Forwarded keys whose value is hydrated from a secret store after process startup
# (the launcher injects them as secret references). The Terraform provisioner_env
# excludes them by design, so they never enter the ConfigMap-bound runtime env and
# must not be projected as generated ConfigMap outputs. DB_PASSWORD and
# FIELD_ENCRYPTION_KEY are not forwarded at all (the provisioner uses RDS IAM auth),
# so DC_DOMAIN_PASSWORD is the only hydrated-secret member of the forwarded set.
AWS_PROVISIONER_HYDRATED_SECRET_KEYS: frozenset[str] = frozenset({"DC_DOMAIN_PASSWORD"})

# The complete set of keys render_aws_values emits into the ConfigMap-bound runtime
# env. It mirrors the Terraform merged_runtime_env (var.runtime_env carrying the
# required bindings, the eks-provisioner-env provisioner_env range/portal topology,
# and deployment extras such as AWS_POLARIS_AGENT_*) plus the renderer-owned keys,
# minus the hydrated-secret keys that flow as references. The bundle's generated
# outputs are derived from this so the published contract and the renderer cannot
# drift; an oracle test asserts a representative render emits exactly this set.
AWS_GENERATED_RUNTIME_ENV_KEYS: frozenset[str] = (
    AWS_EKS_REQUIRED_RUNTIME_ENV_KEYS
    | AWS_RENDERER_OWNED_RUNTIME_ENV_KEYS
    | (AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS - AWS_PROVISIONER_HYDRATED_SECRET_KEYS)
)
