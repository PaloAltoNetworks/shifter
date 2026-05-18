# Secrets Manager CMK Preflight

Issue: GitHub #52, "fix: dev provisioner destroys silently failing on KMS
Decrypt deny".

This note records the architecture boundary for AWS Secrets Manager secrets
encrypted with the portal-owned CMK. It is not an implementation plan.

## Decision Boundary

The portal Secrets Manager CMK is an environment-owned key for portal runtime
secrets and engine-provisioner runtime Secrets Manager objects. Every runtime
principal that reads one of those secrets must hold both:

- `secretsmanager:GetSecretValue` on the specific secret ARN or namespace it
  needs.
- `kms:Decrypt` on the portal Secrets Manager CMK, scoped to
  `kms:ViaService = secretsmanager.<region>.amazonaws.com`.

The key policy remains the outer account and encryption-context boundary. IAM
role policy is still required for each consuming role; do not treat
`Principal: root` in the key policy as a direct runtime grant.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Environment CMK | `aws_kms_key.secrets_manager` in `platform/terraform/environments/{dev,prod}/portal/main.tf` | Keep the key environment-owned and pass its ARN into modules. Do not create per-role duplicate CMKs or reuse the engine Pulumi-state CMK. |
| Secret namespace boundary | The key policy's `kms:ViaService`, `kms:CallerAccount`, and `kms:EncryptionContext:SecretARN` conditions | Preserve service-scoped, namespace-scoped use. IAM grants should align with this boundary rather than broadening the key policy. |
| Provisioner task role grant | `aws_iam_role_policy.kms` `SecretsManagerKMSAccess` in `platform/terraform/modules/engine-provisioner/iam.tf` | Mirror this pattern for other Secrets Manager readers, but prefer the concrete CMK ARN when the role only needs the portal CMK. |
| ECS execution secret injection | `aws_iam_role_policy.ecs_execution_secrets` and `task_definition.tf` `secrets = [...]` | ECS execution role needs KMS decrypt because ECS resolves task-definition secrets before the container starts. Do not move this to the task role only. |
| Portal EC2 runtime hydration | `platform/terraform/modules/portal/ec2`, portal SSM parameters, and `shifter/shifter_platform/entrypoint.sh` | The instance role needs KMS decrypt because the container fetches runtime secret values through the host instance profile. |
| Runtime secret parsing | `entrypoint.sh` `fetch_runtime_secret` and stdin-fed `python -c` JSON extraction | Keep secret values off argv and fail closed when a configured secret cannot be fetched or parsed. |
| Terraform policy assertions | Existing repo-native Python check style under `scripts/check_tf_*` | The repo does not currently use Terraform `*.tftest.hcl` or OPA for IAM policy assertions; prefer a focused Python static check unless a broader Terraform test convention is introduced deliberately. |

## Cross-Cutting Layers

Security layers the implementation must satisfy:

- IAM auth surface: `dev-portal-pulumi-ecs-execution` and
  `dev-portal-ec2-role` must receive least-privilege `kms:Decrypt` grants for
  the portal Secrets Manager CMK. The grant must not include direct KMS use
  outside Secrets Manager.
- KMS policy gate: preserve the CMK policy's `kms:CallerAccount`,
  `kms:ViaService`, and `kms:EncryptionContext:SecretARN` constraints. Do not
  add role ARNs directly to the key policy for this fix.
- Secret-handling surface: secret values stay in Secrets Manager and Terraform
  state only. Terraform variables, tfvars, workflow YAML, logs, generated env
  files, task-definition plaintext environment entries, and command lines may
  carry secret ARNs/IDs, not values.
- Env-binding shape: `DB_SECRET_ID`, `APP_SECRET_ID`, OIDC, Guacamole,
  `DC_DOMAIN_PASSWORD_SECRET_ID`, and `REDIS_SECRET_ID` remain secret
  references. The entrypoint may export resolved values into process
  environment after fetching, but must not silently export empty strings after a
  failed fetch.
- OS/runtime exposure: secret parsing should continue to pipe JSON through
  stdin. Do not pass secret JSON or passwords as Python `-c` arguments, shell
  arguments, Docker command arguments, ECS plaintext environment values, or log
  lines.
- Error/log envelope: startup errors may name the provider and secret reference
  that failed, but must not print the secret value or parsed payload. A
  configured-but-failing optional secret is fatal; an unset optional secret keeps
  existing skip behavior.
- Config and architecture validators: Terraform changes must pass `tflint`;
  architecture-affecting changes must pass `adr_guard`; Python changes in
  `shifter/shifter_platform` must pass the platform `ruff` checks. IAM policy
  regression coverage should use the existing `scripts/check_tf_*` checker
  style unless the repo adopts a single Terraform test framework.

Maintainability incumbents the implementation must build on:

- `platform/terraform/modules/engine-provisioner/iam.tf` for existing
  Secrets Manager KMS grant shape.
- `platform/terraform/modules/portal/ec2` for portal instance-role policy
  ownership and module variables.
- `platform/terraform/environments/{dev,prod}/portal/main.tf` for
  environment-owned CMK wiring.
- `shifter/shifter_platform/entrypoint.sh` for provider-dispatched runtime
  secret hydration.
- `shifter/shifter_platform/documentation/docs/technical/dev/secrets.md` for
  operator-facing secret lifecycle documentation.
- `scripts/check_tf_iam_ec2_scope` as the nearest IAM static-check precedent.

Extensibility seam:

Pass the portal Secrets Manager CMK ARN as a module input anywhere a module
creates or reads portal Secrets Manager secrets. The preferred input name is
`secrets_manager_kms_key_arn` (used by the engine-provisioner and portal/ec2
modules); the guacamole module pre-existed with the shorter `secrets_kms_key_arn`
and the `check-tf-kms-secrets-grant` checker accepts both. New modules should
prefer the verbose name for consistency, but either is recognized so future
environments, rotated CMKs, and new secret readers don't have to hardcode
aliases, key IDs, or region/account strings in leaf modules.

## Whole-Repo Scope

In scope for implementation of this class of change:

- `platform/terraform/modules/engine-provisioner/{iam.tf,task_definition.tf,secrets.tf,variables.tf}`
- `platform/terraform/modules/portal/ec2/{main.tf,variables.tf}`
- `platform/terraform/modules/guacamole/iam.tf` (Guacamole execution
  role + client task role both read portal-CMK-encrypted secrets via
  `secretsmanager:GetSecretValue`)
- `platform/terraform/environments/{dev,prod}/portal/main.tf`
- `shifter/shifter_platform/entrypoint.sh` + `entrypoint-lib.sh`
- tests under `scripts/check_tf_*` and/or `shifter/shifter_platform/tests`
- secret docs and changelog fragments when behavior or operator guidance
  changes
- repo validators: `adr_guard`, `tflint`, platform `ruff`, and targeted test
  commands for touched surfaces

## Gotchas And Anti-Patterns

- Do not grant `kms:*`, `kms:Decrypt` on `"*"`, or unconditioned KMS access to
  either runtime role.
- Do not broaden the CMK key policy to name runtime roles directly when the
  existing root-delegation plus service/encryption-context boundary covers the
  need.
- Do not confuse the ECS execution role with the ECS task role. Task-definition
  `secrets = [...]` resolution happens before container start and uses the
  execution role.
- Do not confuse the portal Secrets Manager CMK with the engine Pulumi-state
  secrets CMK. They protect different boundaries and rotate/revoke
  independently.
- Do not make `fetch_runtime_secret` tolerate provider or JSON failures by
  returning success, an empty string, or a fallback default.
- Do not change optional-secret semantics from "unset means skip" to "unset
  means fail" as part of this bug fix.
- Do not re-encrypt older default-key secrets as part of this repair; that
  changes the blast radius and requires every reader to be ready at once.

## Non-Goals

- No redesign of the secret store, provider abstraction, portal bootstrap, range
  lifecycle service, Guacamole auth, or DC promotion model.
- No new KMS abstraction layer or duplicate IAM policy schema.
- No cleanup of currently stranded EC2 instances inside the code change; that
  remains an operational follow-up after Terraform applies.
- No rotation or rewrapping of pre-CMK secrets.

## Validation

At minimum, changes on this path should run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
cd platform/terraform && tflint --recursive --config ../../.tflint.hcl
```

Add targeted checks for touched surfaces:

- Platform shell/Python entrypoint behavior: a focused test under
  `shifter/shifter_platform/tests` or the repo's closest shell-test convention.
- IAM policy regression: a focused Python static assertion following
  `scripts/check_tf_iam_ec2_scope` unless a Terraform test framework is adopted
  for all similar IAM assertions.
- `cd shifter/shifter_platform && uv run ruff check . && uv run ruff format --check .`
  when platform Python tests or helpers are touched.
