# AWS EKS backend bundle

The AWS backend uses EKS and `platform/charts/shifter` as the canonical
packaging for Shifter platform workloads, and the provisioner dispatches as a
Kubernetes Job on the cluster (mirroring GCP). Range and target delivery (the
VMs inside a range) remain ECS/VM behind the existing ADR-039 range adapter;
Cognito remains the user identity provider. These are separate boundaries.

## Authoritative inputs and owners

The explicit entrypoint is:

```console
./scripts/bootstrap/deploy.py eks-deploy \
  --config shifter.yaml \
  --images .shifter/images.json \
  --profile operator
```

`shifter.yaml` must select `backend: aws`. The image file is a JSON mapping
whose values are attested `repository@sha256:<digest>` identities. Tags are
rejected. Protected input files must resolve beneath the repository, the system
temporary directory, `RUNNER_TEMP`, or an operator-selected
`SHIFTER_PROTECTED_INPUT_ROOT`; symbolic links are rejected.
The lifecycle owner validates root config, runs shared preflight,
applies a saved plan from the isolated
`platform/terraform/environments/<profile>/eks` root, acquires cluster access
through the Terraform-output deploy role, and performs an atomic Helm upgrade.

Terraform owns the cluster, private placement, workload identity roles,
certificate/WAF/DNS prerequisites, KMS, and secret stores. Helm owns namespaced
platform workloads. ECS/ASG portal state and range task state are outside the
EKS root and are never imported, adopted, renamed, or destroyed by it.

The protected EKS JSON var-file supplies a closed `addon_versions` object for
VPC CNI, CoreDNS, kube-proxy, EBS CSI, EFS CSI, and the AWS Secrets Store CSI
provider. Every value is a reviewed `vX.Y.Z-eksbuild.N` release compatible with
the root's pinned Kubernetes version. The EKS module owns the Load Balancer
Controller permission document; deployment inputs must not supply a controller
policy ARN. Before enabling EKS, apply `platform/terraform/global/iam` so the
GitHub deploy role has its environment-scoped EKS/OIDC policy.
The chart renderer gives the sole platform ingress the deterministic
`<cluster>-platform` ALB name. The controller policy uses that exact ARN
namespace for WAF association because WAFv2 does not honor ELB ownership-tag
conditions.

## Security boundaries

- GitHub OIDC authorizes the protected deployment runner.
- EKS workload identity binds exact namespace/service-account subjects to
  workload roles; pods do not inherit node-wide credentials.
- Cognito/OIDC authenticates users and is not cluster authentication.
- Provider values carry public settings and secret references only. Runtime
  values are hydrated from Secrets Manager by the existing entrypoint boundary;
  they do not enter Helm values, ConfigMaps, argv, or committed files.
- The shared chart renders restricted, non-root, read-only workloads with
  bounded resources and default-deny network policy. The Kubernetes Job
  launcher is enabled for AWS: the provisioner dispatches as a fail-closed,
  admission-gated Kubernetes Job (ADR-044-R6) using exact-subject IRSA for the
  launcher and provisioner service accounts, the dedicated-launcher RBAC, and
  restricted Pod Security. Range and target delivery remain ECS/VM behind the
  ADR-039 range adapter.
- Every module-created role carries the installation CI permissions boundary.
  Controller roles remain separate: VPC CNI, EBS CSI, EFS CSI, the Load
  Balancer Controller, and cluster-autoscaler each bind their exact
  `kube-system` ServiceAccount. The Secrets Store CSI provider receives no
  controller-wide secret-reader role; a future consumer continues to use its
  own exact-subject workload role.
- VPC CNI enables NetworkPolicy with strict startup enforcement. Public client
  CIDRs restrict the ALB through `alb.ingress.kubernetes.io/inbound-cidrs`;
  pod-side NetworkPolicy separately admits target traffic from the EKS public
  ALB subnets. These are different network hops and are not interchangeable.

## Provisioner environment sourcing (ADR-044-R6)

The provisioner Job's environment is composed over the existing portal and
range data plane rather than owned by the EKS bundle. The range stack publishes
its topology (VPC/subnet/route-table/security-group IDs, endpoint IDs, ARNs) to
`/shifter/<env>/range/*` in SSM Parameter Store, since those opaque IDs are not
discoverable by a native `data.aws_*` lookup. The `eks-provisioner-env`
Terraform module reads that contract, reads the shared portal RDS/secrets
KMS/agent bucket/VPC via native AWS data sources, reads the prebaked
`/shifter/ami/*` pointers, and merges the result with the deploy-tooling
management-plane runtime env. `terraform_remote_state` is never used
(enforced by the `eks-cross-stack-sourcing` guard); secret payloads flow only as
references through the existing hydration boundary.

## Bundle metadata and doctor

The AWS entry in the backend bundle registry
(`shifter/installation/registry.py`) is the machine-readable contract that
`shifter-config doctor` reads to detect missing prerequisites and secret wiring
before a deploy. There is one generic doctor entrypoint; AWS-specific readiness
is declared through the bundle's `required_tools`, `required_secrets`,
`validation_checks`, and `health_checks`, not through provider-specific doctor
code.

The AWS bundle declares the pre-mutation validation front doors, the fast
credential-free checks doctor runs before touching infrastructure:

- `root-config`: validate the `shifter.yaml` shape with `shifter-config validate`.
- `terraform-fmt`: `terraform fmt -check -recursive platform/terraform/environments`.
- `helm-template`: render `platform/charts/shifter` with
  `values-aws-dev.yaml` so an AWS value-shape error fails before deploy, not
  just a default-values template error.
- `eks-preflight`: run the canonical EKS deploy preflight
  (`scripts/bootstrap/preflight.py --config shifter.yaml --component eks`),
  which derives the cloud and profile from the same root config the deploy uses
  and checks the tools plus the isolated EKS root and backend inputs. doctor and
  the deploy lifecycle therefore share one prerequisite contract instead of
  drifting apart; the check invokes the shared spec rather than re-listing it.

AWS has no `platform/k8s/aws` overlay; its Kubernetes surface is the shared
chart, so `helm-template` is the Kubernetes front door rather than a kustomize
overlay render or a raw-manifest kube-linter pass. The fuller pre-mutation suite
(tflint with init, Checkov, kube-linter and kubeconform on the rendered chart,
and effective-values schema validation) stays enforced in CI and the deploy
lifecycle.

The bundle's `generated_outputs` enumerate the complete runtime-env key set the
renderer emits into the ConfigMap, derived from
`installation.runtime_inventory_aws.AWS_GENERATED_RUNTIME_ENV_KEYS`. That set
mirrors the Terraform `merged_runtime_env` (the renderer-validated required
bindings, the `eks-provisioner-env` range and portal topology the
`provisioner_env` block re-supplies, and deployment extras such as
`AWS_POLARIS_AGENT_*`) plus the renderer-owned keys, so the published contract
and `render_aws_values` cannot drift. An oracle test drives a representative
`render_aws_values` and asserts the emitted keys equal the classified set.
`OIDC_SECRET_ID` is classified as a Secrets Manager reference; `APP_SECRET_ARN`
and `DB_SECRET_ARN` are the compatibility aliases `entrypoint.sh` normalizes;
every other projected key is public runtime configuration. Process roles are
derived per key (portal and worker always, provisioner for the keys the launcher
forwards to the Job). AWS ranges are delivered on ECS/VM rather than Kubernetes
range-task pods, so no AWS output declares the range-task consumer. Keys whose
value is hydrated from a secret reference after startup (`DC_DOMAIN_PASSWORD`)
are excluded from the projection, because a hydrated secret is not a
renderer-emitted value and must never enter a ConfigMap.

The AWS operator settings model (`AwsSettings`) and secret-reference grammar
live in `installation.settings_aws`, mirroring `installation.settings_gcp`.

## Teardown and evidence

```console
./scripts/bootstrap/deploy.py eks-teardown \
  --config shifter.yaml \
  --profile operator
```

Teardown removes the Helm release, destroys only the isolated EKS root, and
fails if that Terraform state remains non-empty. Deploy succeeds only after all
managed add-ons are `ACTIVE`, controller and chart rollouts complete, the
admission policy rejects a non-launcher provisioner Job, live Deployment and
Job probes observe default-deny NetworkPolicy, every workload/controller
ServiceAccount receives its expected caller role and cannot assume a sibling
role, and HTTPS `/health/` succeeds. Diagnostic objects are bounded and removed
unconditionally; projected tokens remain inside pod files and are never logged
or passed in process arguments.

For transition guidance, follow
[Migrate an AWS deployment from ECS to EKS](../../how-to/aws-ecs-to-eks-migration.md).
