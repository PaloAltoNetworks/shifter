# Delete-User Testing Utility Preflight (#83)

Status: pre-implementation guidance

Date: 2026-07-01

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/83>

This is a requirement-free preflight. GitHub issue #83 is the shipping
contract: provide an operator testing utility that removes one test user from
the AWS Cognito user pool and from the portal Django database. This note does
not implement the script, management command, or tests.

## Scope Boundary

This utility is a destructive operator/test reset path, not an application
feature. It should delete exactly one requested identity from the configured
AWS Cognito pool and exactly one matching Django auth user by email. It must not
introduce a public API, broaden auth rules, change normal login/logout behavior,
or redesign user lifecycle semantics.

## Architecture Decisions And Guardrails

- Keep identity-provider deletion and Django deletion separate. Cognito owns the
  external identity; Django owns portal-local authorization, profiles, ranges,
  credentials, notifications, and audit rows.
- Use a Django management command for database deletion. Do not scrape Django
  admin, add a temporary HTTP endpoint, or duplicate deletion logic in shell.
- Treat the Django operation as a hard-delete test reset. Do not conflate it
  with `management.services.mark_user_deleted()`, which only sets
  `UserProfile.deleted_at` and does not reset a future Cognito first-login flow.
- Resolve the Cognito pool from non-secret deployment metadata such as the
  Terraform `cognito_user_pool_id` output, or from an explicit operator
  override. Do not fetch or print the Cognito client-secret bundle just to find
  the pool id.
- Require an explicit credential selection surface: `--profile` or
  `AWS_PROFILE`, with the existing local `.env` profile names only as a
  convenience fallback. Never hardcode profile names, account ids, or secrets.
- Default to the non-production testing environment. Any production-capable
  path must require explicit environment/profile input and a deliberate
  confirmation; no implicit prod.
- Missing Cognito or Django users may be idempotent success. Actual provider,
  Terraform, SSM, or database failures must fail non-zero and not be swallowed.
- The management command should propagate Django `ProtectedError` or related
  database blockers instead of force-deleting unrelated domain objects.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #83 |
| --- | --- | --- |
| AWS env/profile conventions | `scripts/shifter-django-admin-tunnel.sh`, `scripts/bootstrap/deploy.py`, `.env` `PANW_SHIFTER_*_PROFILE` names | Reuse explicit `--profile` / `AWS_PROFILE` behavior and validated env selection; do not invent a second credential convention. |
| Portal remote management | `scripts/portal_deploy/portal_deploy.py` `resolve-topology` and `run-manage-on-portal` | Run `manage.py` inside the deployed portal container through the existing SSM/topology helper; do not duplicate ASG/instance selection. |
| Cognito infrastructure contract | `platform/terraform/modules/portal/cognito`, environment `outputs.tf` `cognito_user_pool_id` | Use the user pool id output as the non-secret pool contract; preserve Terraform as the source of deployed Cognito identity metadata. |
| Django user model/profile | `django.contrib.auth.get_user_model`, `management.models.UserProfile`, `management.apps` profile signals | Delete the auth user through Django ORM semantics and let existing FK behavior decide cascades/blockers. |
| User lifecycle services | `management.services.mark_user_deleted`, `update_cognito_sub`, `get_user_profile` | Reuse only where the semantics match; do not call soft-delete helpers for hard reset. |
| Audit/logging | `risk_register.services.audit_log`, `AuditEvent`, `shared.log_sanitize.safe_log_value` | If durable audit is added, use the existing audit store. Sanitize email/profile/pool output; do not use deprecated `ActivityLog` for new audit. |
| Command errors | Django `BaseCommand`, `CommandError` | Management failures should be bounded command errors, not custom exception hierarchies or raw tracebacks for expected input failures. |
| Script style | Existing Bash scripts under `scripts/` | Use `set -euo pipefail`, quoted variables, `mktemp` cleanup traps, no `eval`, no `set -x`, and no secret-bearing argv. |
| Tests | `tests/management/*`, `scripts/*/tests/*`, `scripts/portal_deploy/tests/test_portal_deploy.py` | Add focused command tests with the real test DB and script argument/topology tests with stubbed external commands. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: there is no browser/API auth change. The authority boundary is
  the operator's AWS IAM credentials for Cognito/SSM plus the deployed portal
  process running the management command. Do not make this reachable from
  unauthenticated HTTP, MCP general-purpose tools, or user sessions.
- Secret-handling surface: AWS profile names, pool ids, regions, ASG names, and
  emails are not secrets, but emails are PII. Do not print environment dumps,
  Cognito client secrets, SSM parameter values, Django `SECRET_KEY`, cookies,
  tokens, or provider credentials. Do not enable shell tracing.
- Env-binding shape: accepted operator inputs are email, environment, region,
  profile, optional pool id, and optional portal target override. Validate
  environment and region/profile strings before deriving Terraform paths or AWS
  commands. Keep new Django settings out of this unless the runtime image needs
  a real setting.
- Config validators: Terraform backend/root selection must use existing
  environment roots and fail loudly if the `cognito_user_pool_id` output or
  portal topology cannot be resolved. If platform Terraform or workflow files
  are changed, the normal ADR/TFLint/actionlint gates apply.
- OS/runtime exposure: the email argument will appear in local shell history,
  process argv, AWS CLI invocation metadata, SSM Run Command history, and
  Django command output. That is acceptable for this issue because email is the
  requested identifier; do not extend the pattern to passwords, tokens, one-time
  links, or secrets.
- Error-envelope surface: this is CLI/management-command output, not a DRF or
  HTML error envelope. Expected validation errors should be concise and
  sanitized. Provider/database exceptions may be logged server-side, but user
  output should not leak raw provider payloads or secret-bearing command text.
- Persistence surface: deleting a Django `User` can cascade CMS/engine ranges,
  credentials, notifications, API tokens, and experiments, while CTF events,
  awards, notifications, scenarios, or other `PROTECT` references may block the
  delete. The command must not bypass those domain constraints.
- Observability surface: log and stdout should identify the target email,
  environment, region, and high-level outcome only. Use `safe_log_value()` for
  user-controlled strings; use fingerprints or masks if future outputs include
  cloud identifiers that should not be readable.

## Extensibility Seam

The seam is the operator-facing target selection, not a new domain service:
`email + provider target + portal target`. Keep the Cognito deletion step
parameterized by `--profile`, `--region`, `--env`, and optionally
`--user-pool-id`. Keep the Django step parameterized by the existing portal
target helper (`instance_id` or `asg_name`) and the management command name.

The next likely variation is deleting from another identity provider such as
GCP Identity Platform. That should add a provider-specific identity deletion
adapter or sibling script while reusing the same Django management command,
rather than pushing provider-specific admin APIs into portal request code.

## Gotchas And Anti-Patterns

- Do not make `UserProfile.deleted_at` the reset mechanism. The auth user and
  username/email uniqueness remain, and Cognito login can recreate/update local
  state.
- Do not add a second email normalization policy. Use Django's user model lookup
  and, if stricter validation is needed, Django validators.
- Do not delete by Cognito `sub` unless the operator explicitly supplies that
  future mode. The issue contract is email, and `UserProfile.cognito_sub` is not
  guaranteed for non-Cognito/dev users.
- Do not silently proceed after an ambiguous Terraform output, missing portal
  target, multiple matching deployed targets, or failed SSM command.
- Do not hardcode `dev`, `prod`, account ids, pool ids, domains, or
  Palo Alto-specific addresses into source beyond documented local profile
  conventions.
- Do not force-delete CTF/scenario ownership blockers or active range state as a
  side effect of "delete user." That is a separate cleanup workflow.
- Do not add a duplicate audit table, duplicate command exception hierarchy, or
  app-local shell wrapper for `manage.py` when `portal_deploy.py` already owns
  remote command execution.

## Non-Goals

- No implementation in this preflight note.
- No public user-management API, admin UI, DRF serializer, controller, or
  repository layer.
- No change to OIDC login, Cognito Hosted UI, logout, MFA, pre-signup Lambda,
  Identity Platform, magic links, CTF roles, or bootstrap admin elevation.
- No bulk deletion, search UI, anonymization, GDPR/data-retention workflow, or
  force cleanup of protected domain records.
- No new root configuration schema or ADR is needed unless the implementation
  changes enforceable guardrails or operator policy.

## Validation Expectations

For implementation touching `shifter/shifter_platform`, run the repo-required
platform gates plus focused command tests, for example:

```bash
cd shifter/shifter_platform && uv run ruff check . && uv run ruff format --check .
cd shifter/shifter_platform && uv run pytest tests/management/test_delete_user_command.py
python3 -m unittest scripts.tests.test_delete_user_script
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

If Terraform, workflows, Kubernetes, or guardrail files are touched, also run
the stack-native checks required by `AGENTS.md` and `.gc/plan-rules.md`.
