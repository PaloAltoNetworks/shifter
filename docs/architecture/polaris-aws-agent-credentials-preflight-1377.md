# Polaris AWS Agent Credential Preflight (#1377)

Status: pre-implementation guidance

Date: 2026-07-12

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1377>

This note records the security and architecture boundary for the AWS Polaris
agent credential fix. It is not an implementation plan. The issue is
requirement-free; the GitHub issue is the authoritative contract.

## Decision

Do not retain the current participant-to-IMDS credential path as the intended
AWS Polaris design.

The premise that the exposed EC2 role is Bedrock-only does not hold in this
repository. `platform/terraform/modules/range/vpc/iam.tf` attaches the shared
range role to every AWS range VM and grants it:

- `AmazonSSMManagedInstanceCore`;
- `s3:GetObject` across the configured agent bucket; and
- Bedrock invocation against wildcard inference-profile and foundation-model
  resources.

Raising the IMDSv2 response hop limit to two therefore exposes a host
operations identity, not a participant agent identity. IMDSv2 prevents
unauthenticated IMDSv1 use; it does not make credentials safe to hand to an
untrusted container that can request its own token.

The durable AWS boundary is:

- Keep the existing EC2 instance profile available to the host for SSM, the S3
  smoke-test fetch, and host-side credential refresh. It is a host operations
  identity and must not be reachable from any Compose container.
- Give each Polaris range host a Terraform-owned, per-range Bedrock agent role.
  The role is not attached to EC2. The host assumes it for short-lived STS
  sessions and delivers only those temporary credentials to `a14-kali`.
- Scope the target role to the exact approved Bedrock inference profiles and
  backing foundation-model ARNs required by the configured main and small/fast
  models. Allow only the proven invocation actions. Do not grant S3, SSM, IAM,
  Secrets Manager, KMS, arbitrary STS, or wildcard Bedrock access.
- Bind the target role trust to the shared range-host role **and** the exact
  Polaris EC2 source instance with `ec2:SourceInstanceARN`. The shared source
  role may receive `sts:AssumeRole` only for the Shifter-owned agent-role
  namespace. Another range host must not be able to assume this range's role.
- Request the minimum practical STS duration (AWS permits 900-second
  `AssumeRole` sessions) and refresh before expiry. Use an auditable session
  name/source identity containing the existing environment and range ID, but
  no user data or secrets.
- Materialize the STS response only on the host under a root-owned runtime
  directory such as `/run`, atomically and with mode `0600`. Expose that
  directory read-only to `a14-kali`; configure the existing Claude/Bedrock
  environment to use an AWS SDK-supported refreshing credential provider such
  as `credential_process`. Credential JSON must never enter Python render
  context, Terraform values/state/outputs, EC2 user data, SSM command bodies,
  process arguments, durable files, database state, or logs.
- Keep IMDSv2 required, keep the response hop limit at one, and install a
  persistent host firewall rule that drops forwarded container traffic to
  `169.254.169.254/32`. Keep the IPv6 IMDS endpoint disabled, or block it too.
  The rule must be restored after host reboot and Docker daemon restart; a
  one-time `iptables` mutation during bootstrap is not a durable control.
- Destroy/revoke the per-range agent role before the range host is destroyed
  and before the range is marked destroyed. Terraform should own the non-secret
  IAM role and its dependency on the exact EC2 instance so failed apply and
  normal destroy use the existing cleanup path. Deleting a local credential
  file is cleanup, not revocation.

This is parity with the GCP design at the security boundary, not at the
credential mechanism. GCP needs a service-account key plus Secret Manager;
AWS supports short-lived STS role credentials. Creating IAM users/access keys
or copying the GCP storage mechanism would introduce long-lived credentials
without improving the boundary.

No ADR is required while the implementation stays within the existing AWS
range Terraform lifecycle, setup-plan boundary, and secret-handling rules. Add
or revise an ADR only if the implementation moves IAM ownership out of
Terraform, adds a public credential-broker service, changes the range lifecycle
contract, or weakens a repository security gate.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1377 |
| --- | --- | --- |
| Stable host identity | `platform/terraform/modules/range/vpc/iam.tf` and its range instance profile | Keep SSM/S3 host duties here. Do not describe or reuse this identity as the participant agent role. Do not remove Bedrock from it without checking the former TechVault scenario-pack host-seat path. |
| STS and Bedrock private reachability | `platform/terraform/modules/range/vpc/ssm-endpoints.tf` | Reuse the existing STS and Bedrock Runtime interface endpoints. Do not add public egress or a second endpoint stack for credential refresh. |
| Per-range AWS resources | `shifter/engine/provisioner/terraform/modules/range/**` | Own the non-secret per-range agent role, tags, trust, policy, and output here so apply failure and destroy converge through the existing Terraform state. |
| Terraform input binding | `terraform_vars._build_tf_instance`, `_build_range_terraform_variables`, and `build_range_variables` | Derive the internal Polaris-agent enablement once from the existing `ami_key == "polaris-vm"` decision. Do not add a public scenario field or Polaris-only DTO. |
| Polaris dispatch | `instance_orchestrator._setup_one_other_instance` and `polaris_bootstrap._run_polaris_range_bootstrap` | Continue gating on the existing Polaris AMI key and passing only non-secret role/config references into the setup plan. |
| Agent shard | `PolarisRangeBootstrapPlan` and `KALI_BEDROCK_SHARD_SCRIPT` | Replace the AWS shard's IMDS dependency here. Do not resurrect a one-off operator hotfix or add a second bootstrap controller. |
| Remote execution | `SetupStep`, `SetupOrchestrator`, and `SSMExecutor` | Reuse rendering, retry, verification, timeout, and error behavior. SSM receives fixed scripts plus non-secret references, never an STS response. |
| Sensitive logging | `SetupOrchestrator._mask_sensitive_output` and `log_redact.safe_log_fingerprint` | Do not rely on key-name masking for credentials that should never enter context. Log range/step correlation and fingerprints only; never access-key IDs, tokens, credential JSON, environment dumps, or rendered secret-bearing commands. |
| GCP parity reference | `gcp_range_vertex_creds.py` and `KALI_VERTEX_SHARD_SCRIPT` | Reuse the lifecycle properties: participant identity separated from host identity, host-side delivery, metadata denial, idempotent cleanup, and fail-closed verification. Do not force AWS through the GCP key/Secret Manager mechanism. |
| IAM naming and delegation | `docs/architecture/iam-role-naming-preflight-253.md` and `docs/architecture/range-ssm-iam-scope-preflight-1178.md` | Use the repo IAM name prefix, Shifter/environment/range/purpose tags, permissions boundary, narrowly scoped provisioner IAM, and exact per-range principal binding. |
| Operator health | `scripts/polaris-aws-range/range_health.py`, `check_range_health.py`, and Polaris smoke tests | Update health evidence to prove the target assumed-role identity and IMDS denial. Do not keep “no static access-key exports” as the only credential check. |

## Cross-Cutting Layers The Intended Design Must Pass

### Authentication and IAM policy

- No new Django, CTF, Mission Control, or participant auth surface is needed.
  Existing participant access still terminates at the `a14-kali` shell.
- The host instance profile remains the SSM/S3 operations principal. The
  participant receives a distinct assumed-role principal whose trust is bound
  to the exact source EC2 instance and whose permissions contain only approved
  Bedrock invocation resources/actions.
- Cross-region inference needs both the selected inference-profile ARN and the
  exact backing foundation-model ARNs for its destination Regions. Restrict
  backing-model access with the inference-profile condition so the participant
  cannot invoke those models outside the approved profile. `List*` actions must
  not be added unless runtime evidence proves they are required; actions that
  do not support resource scoping belong in a separate reviewed statement.
- The engine-provisioner task role may manage only tagged, correctly prefixed
  agent roles for its environment, with the repository permissions boundary.
  The target role is not passed to EC2, so `iam:PassRole` must not be widened
  for it.

### Config and shape validation

- The CMS scenario schema and shared `RangeSpec` remain unchanged. Polaris is
  already identified by `ami_key`; do not add an `agent_credentials` scenario
  schema for one provider-specific runtime detail.
- Put AWS agent region, main/small model IDs, their approved inference-profile
  and backing-model ARNs, STS duration, and refresh window behind one validated
  provisioner config seam. Both Terraform policy rendering and
  `PolarisRangeBootstrapPlan` must consume it. Do not keep independent model
  defaults in IAM, Python, embedded shell, and deployment Terraform.
- Terraform types/validation must reject an enabled agent role with an empty or
  malformed ARN/model set. `PolarisRangeBootstrapPlan.get_context` and the host
  script must validate the non-secret target role ARN, range ID, Region, and
  refresh timing before shell interpolation.
- Embedded scripts continue through `SetupOrchestrator._render_script` and
  `tests/test_plan_template_tokens.py`; do not add Jinja, ad hoc substitution,
  or a second config parser.

### Secret handling and OS/runtime exposure

- STS credentials are generated on the range host from its instance profile,
  not by the provisioner task. This keeps them out of SSM Run Command history
  and the setup orchestrator's captured stdout/stderr.
- Use a root-owned `/run` directory, `umask 077`, same-directory atomic rename,
  bounded refresh, and no shell tracing. Validate the response shape without
  echoing it. The Compose override may contain a read-only mount and config
  paths, but no credential values.
- The participant is expected to be able to read and exfiltrate the scoped
  Bedrock session; that is its intended identity. Security comes from exact
  permissions, per-range trust/lifecycle, and short expiry—not from pretending
  a root-capable Kali user cannot read its own credential.
- `a14-kali` must remain non-privileged, outside the host network namespace,
  without `CAP_NET_ADMIN`, and without the Docker/containerd socket or writable
  host mounts. Otherwise the participant can bypass the metadata firewall or
  take over the host, making credential separation meaningless.
- Apply the metadata drop to all forwarded Compose traffic in `DOCKER-USER`,
  not just a container IP that changes on recreate. Preserve access to the
  Amazon VPC DNS resolver at `169.254.169.253`; it is not IMDS.
- The firewall restoration unit must order against Docker startup/restart and
  fail closed. The range must not become ready if the rule, credential refresh,
  read-only mount, or target caller identity cannot be verified.

### Persistence, lifecycle, errors, and observability

- Terraform state owns only the role, trust, policy, tags, and non-secret ARN.
  No new database model, repository, secret reference field, or durable
  credential record is needed. Existing instance outputs may carry the role
  ARN transiently into bootstrap; `state_helpers` must not grow a plaintext
  credential field.
- Preserve `SetupError`, executor exceptions, `SetupResult`, range failure
  publication, and `_attempt_terraform_auto_cleanup`. Do not add an AWS-agent
  exception hierarchy or swallow a metadata/firewall/STS failure as a warning.
- Errors may name the step, range ID, role purpose, and sanitized provider error
  code. They must not contain STS output, access-key IDs, session tokens,
  credential-file contents, environment dumps, or full SSM scripts.
- Use deterministic role tags and an environment/range-scoped session name or
  source identity for CloudTrail correlation. Do not enable or expand Bedrock
  prompt/body logging as part of this credential fix; model content has a
  separate data-handling boundary.
- Destroy must be idempotent for failed/partial apply and missing IAM objects.
  It must revoke/delete the target role before publishing `destroyed`. A paused
  host stops refreshing, but an already exfiltrated session remains usable
  until its short expiry unless pause-time revocation is separately designed.

## Extensibility Seam

The seam is one validated AWS Polaris agent-credential profile containing:

- provider/region;
- approved main and small/fast model IDs;
- exact inference-profile and backing foundation-model ARNs;
- STS session duration and refresh window; and
- the per-range target role ARN supplied by Terraform at runtime.

That profile is internal provisioner configuration, not scenario content. It
lets the next reasonable change—model rotation, a different AWS Region,
geographic inference-profile changes, shorter refresh, or per-range cost
attribution—update one config/policy boundary without editing CTF, CMS, public
range schemas, the GCP credential lifecycle, or every embedded script.

## Whole-Repository Scope For The Future Implementation

- Stable AWS range IAM/networking:
  `platform/terraform/modules/range/vpc/{iam.tf,ssm-endpoints.tf,variables.tf,outputs.tf}`.
- Provisioner IAM/runtime binding:
  `platform/terraform/modules/engine-provisioner/{iam.tf,task_definition.tf}`
  and the environment roots that pass non-secret agent config.
- Per-range AWS Terraform:
  `shifter/engine/provisioner/terraform/modules/range/**`.
- Provisioner config and internal Terraform shape:
  `config.py`, `terraform_vars.py`, `terraform_ops.py`, and
  `instance_orchestrator.py`.
- Polaris setup and verification:
  `polaris_bootstrap.py`, `plans/polaris_range_bootstrap.py`,
  `plans/_polaris_scripts.py`, and their provisioner tests.
- Operator and end-to-end evidence:
  `scripts/polaris-aws-range/{range_health.py,check_range_health.py}`, the
  Polaris A14/isolation smoke tests, and relevant runbooks/drift notes.
- Architecture enforcement if a new static guard is added:
  repo-native `scripts/check_tf_*` tests, `.pre-commit-config.yaml`,
  `.github/workflows/_quality.yml`, `.github/quality-path-filters.yaml`, and
  ADR guard documentation.

`scripts/polaris-aws-range/ranges.tf` is the standalone bake/support path, not
the canonical participant range lifecycle. Its hop-limit-two configuration
must not be copied back into Engine. If that path is used for participant
ranges rather than disposable bake validation, it needs the same metadata and
agent-role boundary; do not create a second credential lifecycle there.

## Gotchas And Anti-Patterns

- Do not accept IMDS exposure on the theory that the current role is
  Bedrock-only; it is not.
- Do not treat IMDSv2 token enforcement as tenant isolation. A participant
  shell can make the token request when the response hop limit permits it.
- Do not use an IAM user, long-lived access key, static environment variables,
  EC2 user data, SSM SecureString, or Secrets Manager as a substitute for an
  STS session that the host can refresh.
- Do not pass credentials in `SetupOrchestrator` context. Masking is defense in
  depth, not authorization to put secrets in rendered SSM scripts.
- Do not make the credential refresh failure best-effort. The current
  hop-limit mutation warns and continues; the replacement security controls
  and Bedrock caller-identity check must fail provisioning.
- Do not rely on a one-time `iptables` command, a mutable container IP, or
  hop-limit one alone. Reboot, Docker restart, IPv6 IMDS, privileged mode,
  host networking, Linux capabilities, and socket mounts are bypass surfaces.
- Do not broaden the Bedrock policy to `foundation-model/*`,
  `inference-profile/*`, `bedrock:*`, or all Regions for convenience. Encode
  every Region/resource required by the selected inference profiles and no
  more.
- Do not mutate a shared role policy per range to revoke sessions; concurrent
  range teardown would create policy races. The revocation boundary is the
  per-range role.
- Do not create a network credential-broker API unless the standard refreshing
  file/provider mechanism is proven incompatible with the shipped Claude/AWS
  SDK. A broker adds authentication, request validation, logging, availability,
  and host-network attack surfaces that this issue does not otherwise need.
- Do not remove Bedrock from the shared range host role without checking
  `TechVaultRangeBootstrapPlan`, whose Claude seat intentionally runs on the
  host. Polaris container isolation and host-role minimization are related but
  distinct changes.
- Do not overlook IAM role quotas, permissions-boundary enforcement, IAM/STS
  propagation delay, refresh races, host/container reboot behavior, partial
  Terraform apply, or repeated destroy. Use bounded retries and fail with
  sanitized context.
- Do not treat Bedrock-only as no blast radius. Exfiltrated sessions can still
  create model cost and send data to the allowed models until expiry.

## Non-Goals And Boundaries

- This preflight does not implement #1377, mutate AWS resources, rotate live
  ranges, rebake an AMI, or change a workflow.
- No redesign of CTF participant access, Guacamole, range status, subnet/NGFW
  isolation, scenario schemas, GCP Vertex credentials, former TechVault
  scenario-pack credentials,
  CTFd, Claude retirement/cutoff, or the public ACES/LilRAE (formerly APTL)
  model is included.
- Preventing a participant from copying its deliberately supplied, scoped
  Bedrock session is not a goal. Preventing it from obtaining the host role,
  bounding what the supplied identity can do, and making that identity expire
  and revoke per range are the goals.
- Bedrock budget enforcement, per-participant token quotas, prompt retention,
  model invocation logging, and abuse detection are separate controls. The
  role/session seam should support later attribution, but this issue should not
  invent a billing or telemetry subsystem.
- Immediate pause-time session revocation is not included. Short expiry bounds
  the pause residual; destroy-time per-range revocation is required.
- Do not generalize this into a cloud-neutral credential framework. The shared
  contract is the security property; AWS STS and GCP service-account keys keep
  provider-native lifecycle implementations.

## Validation Expectations

At minimum, future implementation changes on this path must run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Targeted evidence must also cover:

- Terraform formatting/validation and a repo-native IAM regression check for
  exact target-role actions/resources, permissions boundary, tags, source
  instance trust, and absence of S3/SSM/IAM/KMS/Secrets permissions;
- provisioner tests for config validation, Terraform variable/output shape,
  AWS/GCP step selection, template tokens, fail-closed STS/firewall failures,
  and sanitized errors;
- a live A14 check showing `sts get-caller-identity` resolves to the per-range
  agent role, Bedrock streaming works, and S3/SSM access is denied;
- bounded IMDSv2 token attempts from every Compose network failing while the
  host still refreshes STS and remains SSM-manageable;
- host reboot, Docker restart, container recreate, credential expiry/refresh,
  failed apply cleanup, repeated destroy, role deletion/revocation, and
  cross-range assume-role denial; and
- the existing Polaris scenario and isolation smoke tests, plus historical
  TechVault scenario-pack regression if the shared host role changes.
