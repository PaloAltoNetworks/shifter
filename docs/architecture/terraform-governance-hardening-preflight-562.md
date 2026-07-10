# Terraform Governance Hardening Preflight (#562)

Status: pre-implementation guidance

Date: 2026-06-27

Issue: GitHub #562, "Architecture review: remove dev-only IAM and placeholder
alert config from Terraform".

This is requirement-free guidance. The GitHub issue is the shipping contract.
This note records repository-wide boundaries and guardrails only; it is not an
implementation plan.

## Scope Boundary

Treat this as AWS Terraform governance hardening. The change belongs in the
existing Terraform roots, AWS deploy workflow wiring, and repo-native guardrail
surfaces. It must not redesign Django runtime settings, provider abstractions,
range provisioning behavior, secret stores, or logging frameworks.

The issue has two independent outcomes that must stay separate:

- GitHub Actions OIDC deploy permissions must no longer use blanket admin
  access or an admin-equivalent substitute.
- AWS Budget notification recipients must be deployment-owned configuration
  that is required for real environments and blocked when placeholder-shaped.

## Architecture Decisions

- `platform/terraform/global/iam/github-oidc.tf` remains the owner of the AWS
  GitHub Actions OIDC role and attached deploy policies. Do not add a second
  role module, policy generator, or long-lived AWS credential path.
- Removing `AdministratorAccess` is not sufficient if the replacement is a
  single broad inline policy with `Action="*"` or unrestricted IAM escalation.
  Scope permissions by the Terraform and workflow operations the repo actually
  performs, and use existing Checkov/ADR exception machinery for any residual
  wildcard risk that remains accepted.
- Budget alert recipients are deployment configuration, not source content.
  Real values belong in GitHub `TF_VARS_<ENV>_CORE` secrets or gitignored
  `local.auto.tfvars`, while committed examples stay synthetic.
- The protected deploy path must prove a real `budget_alert_email` is supplied
  for each AWS core environment it can deploy. A non-empty secret body is not
  enough if the HCL omits `budget_alert_email` and Terraform falls back to an
  empty default.
- Terraform variable validation should reject malformed, empty, and placeholder
  budget email values when a real deploy is planned. `adr_guard.py` should only
  backstop committed-source regressions such as hardcoded placeholders or a
  reintroduced managed `AdministratorAccess` attachment.
- The repository now routes AWS `proof` in addition to `dev` and `prod`. Either
  keep `proof` on the same core-secret, validation, and budget-recipient
  contract, or explicitly document why it is out of scope.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #562 |
| --- | --- | --- |
| GitHub OIDC role | `platform/terraform/global/iam/github-oidc.tf` | Narrow the existing deploy role policies here; do not create a parallel role or credential model. |
| OIDC role names and GitHub secret wiring | `scripts/bootstrap/deploy.py`, `scripts/bootstrap/README.md`, `docs/dev/deploy-secrets.md` | Keep `github-actions-shifter-<env>` and `AWS_ROLE_ARN*` behavior consistent. |
| IAM naming and scoping guidance | `docs/architecture/iam-role-naming-preflight-253.md`, `scripts/check_tf_iam_role_naming/` | Reuse the `shifter-*` role namespace, managed-policy allowlist, and IAM checker pattern before adding new IAM rules. |
| Terraform IaC policy | `platform/terraform/.checkov.yaml`, `docs/adr/exceptions.yaml`, ADR-004-R11 | Keep Checkov blocking; update exception text when residual IAM wildcard risk changes. |
| Core budget Terraform roots | `platform/terraform/environments/{dev,proof,prod}/{main.tf,variables.tf}` | Keep the budget contract at the core root; do not mix it with portal `alarm_email`, SES, or CTF notification settings. |
| Deploy-time config rendering | `.github/workflows/deploy.yml`, `.github/workflows/_core.yml`, ADR-011-R7 | Render gitignored `local.auto.tfvars` before validate/plan/apply and fail loud on missing active-environment config. |
| Operational-placeholder enforcement | ADR-004-R15 and `scripts/adr_guard/adr_guard.py` | Centralize repo-specific placeholder/admin-access regressions in ADR guard, with focused tests. |
| Secret and generated-artifact hygiene | `.gitignore`, `.gitleaks.toml`, ADR-004-R7/R8/R14 | Do not commit real recipient values, rendered tfvars, plan files, account IDs, or live cloud identifiers. |

## Cross-Cutting Layers

- GitHub auth surface: AWS deploys continue through OIDC and
  `aws-actions/configure-aws-credentials` with existing `id-token: write`
  workflow permissions. No PATs, static AWS keys, or broader trust subjects.
- IAM policy gate: the deploy role policy must constrain IAM role/profile
  management, `iam:PassRole`, inline policies, managed-policy attachments, and
  self-management risk. A permissions boundary on roles CI creates is useful
  defense-in-depth, not a substitute for scoping the deploy role itself.
- Secret-handling surface: GitHub secrets may contain the whole-file HCL payload
  for `local.auto.tfvars`. Workflows must write it without shell tracing and
  must not print or upload the body.
- Env-binding shape: environment-to-secret mapping stays in `deploy.yml` /
  `_core.yml` via `TF_VARS_DEV_CORE`, `TF_VARS_PROOF_CORE`, and
  `TF_VARS_PROD_CORE`; Terraform owns the `budget_alert_email` variable shape.
- Terraform validators: use Terraform variable validation for email syntax,
  non-empty deploy values, and placeholder rejection. `terraform fmt`,
  `terraform validate`, plan/apply saved-plan behavior, TFLint, and Checkov
  remain required gates.
- Repo guardrails: `adr_guard.py` owns repository-specific checks that external
  tools do not cover, especially committed operational placeholders and the
  managed `AdministratorAccess` attachment regression.
- OS/process exposure: policy JSON, role names, and secret names are acceptable
  diagnostics; rendered tfvars content, AWS credentials, account-specific live
  identifiers, and Terraform plan/state-derived values are not.
- Error envelope: workflow failures should use bounded `::error::` messages
  naming the missing secret, unsupported environment, invalid variable, or
  policy-shape violation. Do not dump HCL payloads, plans, state, or provider
  debug logs into GitHub comments.
- Persistence and drift: IAM policy attachments, role names, budget resources,
  and notification subscriptions are Terraform-managed state. Review forced
  replacement and subscription-confirmation behavior as infrastructure changes,
  not application changes.

## Extensibility

The required seams are:

- One environment-to-core-tfvars mapping for `TF_VARS_<ENV>_CORE`, so adding a
  future AWS environment is a mapped secret plus Terraform root, not copied shell
  logic.
- One `budget_alert_email` contract at the core Terraform root, so budget
  recipients stay distinct from portal alarm and SES/CTF email settings.
- One OIDC policy ownership surface grouped by deploy responsibility, so adding
  a future AWS service permission is a reviewed policy/test/exception update
  instead of a new admin attachment.

## Gotchas And Anti-Patterns

- Do not call the replacement "least privilege" if broad wildcard service
  actions or `Resource="*"` remain without a current ADR exception and expiry.
- Do not allow `budget_alert_email = ""` to pass on protected real-environment
  deploys. Empty may be useful only as a static baseline convention if CI blocks
  it before plan/apply.
- Do not validate the whole-file tfvars payload with shell greps. Let Terraform
  parse HCL, or use an existing repo-native checker only for source-controlled
  guardrails.
- Do not conflate `budget_alert_email`, portal `alarm_email`, SES sender
  domains, CTF user emails, and workflow notification addresses.
- Do not commit real operational email addresses just to satisfy "real
  recipients"; configure them out of band and keep committed examples synthetic.
- Do not widen workflow path filters, weaken Checkov, remove ADR exceptions, or
  skip `adr_guard` to get this through CI.
- Do not leave `proof` silently behind if it shares the same AWS deploy path.

## Non-Goals

- No Django, API, DTO, database, controller, service-layer, or logging-framework
  change.
- No new secret store abstraction, HCL schema registry, IAM policy generator, or
  deploy orchestration framework.
- No broad cleanup of unrelated global IAM users or workshop/demo infrastructure
  unless they are directly managed by the same GitHub Actions deploy role policy.
- No GCP/Kubernetes change except preserving existing validation and workflow
  boundaries.
