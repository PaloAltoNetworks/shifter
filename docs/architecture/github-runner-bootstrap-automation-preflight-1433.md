# GitHub Runner Bootstrap Automation Preflight (#1433)

Status: pre-implementation guidance

Date: 2026-07-11

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1433>

This is a requirement-free preflight. The GitHub issue is the shipping
contract: fresh AWS bootstrap must provision self-hosted runner infrastructure
and register runners automatically, without exposing GitHub registration tokens
through Terraform, user data, SSM history, process listings, or logs.

## Scope Boundary

This is bootstrap orchestration and one-time runner registration work. It is
not a CI routing redesign, runner autoscaler, new GitHub App, portal runtime
change, range-network change, or secret-store redesign.

Keep these concepts separate:

1. Runner infrastructure: the EC2 fleet, IAM role, health alarms, and network
   placement owned by `platform/terraform/global/github-runner/**`.
2. Runner placement: ADR-004-R20's non-default runner network contract from
   issue #1222.
3. Runner registration: a GitHub one-time registration token exchanged over SSM
   for on-host `.runner` / `.credentials` files.
4. Bootstrap orchestration: `scripts/bootstrap` deciding when to apply the
   runner root and when to invoke registration.

Conflating those layers is the main risk. Terraform should create hosts, not
carry GitHub registration tokens. Bootstrap can orchestrate Terraform and SSM,
but should not become a second runner IaC root.

## Architecture Decisions

- Build on the existing runner root:
  `platform/terraform/global/github-runner/**`. Do not create another runner
  Terraform stack or resurrect the deleted autoscaler module.
- Make runner provisioning reachable from the bootstrap path, either as
  `bootstrap --with-runners` or a dedicated `runners` subcommand. The default
  behavior may stay conservative, but the automatable path must be first-class
  and documented from the fresh-account runbooks.
- Reuse the per-instance backend config renderer in
  `scripts/bootstrap/terraform_backend.py`; it already includes
  `global/github-runner`. Do not rewrite tracked `*.s3.tfbackend` files as the
  bootstrap automation path.
- Registration tokens must be minted by the bootstrap process through GitHub's
  repo registration-token API, one token per runner. The token must stay in
  Python memory only long enough to send the registration command.
- Do not pass the registration token to Terraform, Terraform variables, user
  data, SSM Parameter Store, Secrets Manager, GitHub Actions secrets, tfvars,
  or generated backend files. The token is single-use and short-lived; storing
  it increases exposure without improving restartability.
- Do not embed the token in a shell command line visible to process listings on
  the runner host (this rules out `config.sh --unattended --token <TOKEN>`,
  which would place the token on `config.sh`'s argv). Feed it to the remote
  registration script through a root-owned temporary file, then delete it before
  `svc.sh` starts. The remote script must run with shell tracing disabled around
  token handling, and a trap must remove the temp file on any exit so it never
  lingers.
- `config.sh` reads its registration-token prompt through a console-only masked
  reader, so it must run under a PTY (via `expect`) rather than over redirected
  stdin, which fails with "Cannot read keys ... console input has been
  redirected" on current runner releases. `expect` waits for the token prompt,
  then sends the token read from the root-owned file, keeping the token off
  both `config.sh`'s and `expect`'s argv. The runner host therefore needs
  `expect` installed at boot (runner root user_data).
- Build SSM `--parameters` as JSON in one argv element, matching the
  `scripts/portal_deploy/portal_deploy.py` precedent and ADR-010's remote SSM
  boundary guidance. Do not use shorthand `commands=[...]` or shell-escaped
  strings.
- Keep the #1222 network guard intact. The automated path must provision into a
  dedicated runner VPC or another ADR-004-R20-compliant non-default network, or
  require the existing explicit `allow_default_vpc` opt-in. Automation must not
  silently choose the account default VPC.
- Registration verification should use GitHub's runners API and runner names
  derived from Terraform output, not manual web-console instructions.
- Runner health remains the #292 CloudWatch/systemd path. Registration
  automation may use the existing service signal as a post-check, but must not
  replace health monitoring or introduce a GitHub-token poller in AWS.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1433 |
| --- | --- | --- |
| Bootstrap CLI | `scripts/bootstrap/cli.py`, `deploy.py` facade | Add command/flag wiring here; preserve `bootstrap`, `terraform`, and `full` behavior for existing users. |
| Runner orchestration | `scripts/bootstrap/runner.py` | Evolve the manual walkthrough into apply/register helpers. Keep runner-specific code here instead of spreading it through `aws_bootstrap.py`. |
| Command execution and log redaction | `scripts/bootstrap/bootstrap_core.py` `run_cmd`, `_validate_argv`, `_redact_argv_for_log` | All subprocess calls use argv lists and redacted operator logs. Add token-specific coverage if the generic heuristic is not enough. |
| Backend config | `scripts/bootstrap/terraform_backend.py` | Use `backend_config_for_stack(..., "global/github-runner", env)` and the existing instance dir shape. |
| Runner IaC owner | `platform/terraform/global/github-runner/{main.tf,variables.tf,outputs.tf,alarms.tf,README.md}` | Terraform owns hosts, IAM, alarms, and outputs. It must not consume registration tokens. |
| Network guard | ADR-004-R20, `scripts/check_tf_runner_network/check_tf_runner_network.py`, `docs/architecture/github-runner-network-isolation-preflight-1222.md` | Keep default-VPC fail-closed behavior and subnet/VPC membership validation. |
| SSM JSON precedent | `scripts/portal_deploy/portal_deploy.py` and tests for #1413 | Render `{"commands": [...]}` with `json.dumps` and pass it as one argv element. |
| GitHub repository target | `.ground-control.yaml` `github_repo`, `BootstrapConfig.github_org/github_repo` | Default to `Brad-Edwards/shifter`; do not follow stray remotes or user-level repo defaults. |
| Fresh-account docs | `scripts/bootstrap/README.md`, `docs/dev/aws-runner-provisioning-runbook.md`, `docs/dev/deploy-secrets.md`, `docs/dev/aws-terraform-apply-order.md` | Update after implementation so the docs describe the automated path, not the old manual gap. |
| Runner teardown | `docs/dev/aws-teardown-runbook.md`, runner README removal section | Preserve removal-token handling as a separate lifecycle path. Do not mix registration and deregistration tokens. |

## Cross-Cutting Layers

Security layers the intended design must pass:

- GitHub auth surface: use the repo registration-token endpoint for
  `Brad-Edwards/shifter` through `gh api` or a narrowly scoped GitHub API
  helper. A token is minted per runner, used once, and never persisted. Errors
  may name the endpoint and runner name, but must not echo response bodies that
  include token material.
- GitHub Actions trust surface: ADR-003 still keeps pull_request jobs off
  self-hosted deploy runners. This issue must not widen workflow access,
  labels, environments, or OIDC trust.
- Bootstrap command surface: use `run_cmd` / `_validate_argv` style argv lists.
  If a helper needs to capture command output, redact before logging and avoid
  printing stderr/stdout that may contain token-bearing JSON.
- SSM control-plane surface: send `AWS-RunShellScript` through JSON
  `--parameters` as one argv element. Command comments, command names, and
  CloudWatch output config must not include tokens. Disable command output to
  S3/CloudWatch unless a future design proves it is token-free.
- Remote SSM shell surface: token handling is a separate secret handoff inside
  the script. Do not put `--token <value>` directly in the visible remote
  command line, use `set +x` around the secret, delete temporary files, and
  leave only `.runner` / `.credentials` as the intended long-lived result.
- Terraform state surface: runner Terraform inputs and outputs remain
  non-secret infrastructure data. Registration tokens, GitHub PATs, and
  removal tokens must never become variables, locals, outputs, user data, or
  generated tfvars.
- Network validation surface: the automated apply must still satisfy
  `allow_default_vpc`, `vpc_id`, `subnet_id`, and the Terraform lifecycle
  preconditions in the runner root. If the implementation creates a dedicated
  runner VPC, that creation must also preserve ADR-004-R14 identifier hygiene
  and the #1222 DNS-scope invariant.
- OS/runtime exposure: IMDSv2, SSM Session Manager, no inbound SSH, Docker, the
  Actions runner service, and `shifter-runner-health.timer` remain in force.
  Do not add SSH ingress, `/etc/hosts` DNS hacks, process-env token exports, or
  persistent token files.
- Error/log envelope: bootstrap output should report stage, runner name,
  instance id, command id, and GitHub online/offline state only. Never print the
  registration token, API response JSON, SSM command body, environment dump,
  Terraform state, or `.credentials` content.
- Static enforcement surface: changes touching Terraform or guardrail files
  must pass ADR guard, TFLint, Checkov policy, and the runner-network checker.
  New Checkov skips require ADR-004-R11 exception metadata.

Maintainability incumbents the implementation must build on:

- `scripts/bootstrap/runner.py` for runner-specific orchestration.
- `scripts/bootstrap/bootstrap_core.py` for subprocess validation and redacted
  logs.
- `scripts/bootstrap/terraform_backend.py` for backend paths.
- `platform/terraform/global/github-runner/**` for runner infrastructure.
- `scripts/portal_deploy/portal_deploy.py`'s JSON SSM parameter precedent.
- ADR-003, ADR-004-R14, ADR-004-R20, ADR-010, and the #1222/#292 preflight
  notes for workflow, identifier, network, SSM, and health boundaries.

Extensibility seam:

Keep the registration operation parameterized by a runner target object:
`instance_id`, `runner_name`, `labels`, `work_folder`, `repo_url`, and
`region`. Today Terraform outputs `runner_instance_ids` and `runner_names`; the
next likely change is multiple subnet/AZ placement, different label sets, or a
separate proof/prod runner fleet. Those variations should change the target
mapping and labels, not the secret-handling path or Terraform root.

## Whole-Repo Scope

Likely in scope for implementation:

- `scripts/bootstrap/{cli.py,runner.py,bootstrap_core.py,terraform_backend.py,README.md}`
- `scripts/bootstrap/tests/**`
- `platform/terraform/global/github-runner/**`
- `docs/dev/aws-runner-provisioning-runbook.md`
- `docs/dev/deploy-secrets.md`
- `docs/dev/aws-terraform-apply-order.md`
- `docs/dev/aws-teardown-runbook.md` if removal/replacement instructions change
- `docs/ops/github-runner-health-alerts.md` if registration changes the service
  health interpretation
- `changelog.d/1433.changed.md` or `1433.fixed.md` for the runtime/operator
  behavior change

Usually out of scope:

- `.github/workflows/**`, unless docs links or validation wiring need a narrow
  update.
- Portal application code, Django settings, API schemas, controllers, services,
  repositories, exception hierarchies, and shared DTOs.
- Range provisioning, range private-DNS endpoint behavior, scenario content,
  and `settings.range_egress`.
- GCP/GDC/Kubernetes deployment paths.
- New MCP tools or Ground Control traceability for this requirement-free issue.

## Gotchas And Anti-Patterns

- Do not pass the GitHub registration token as a Terraform variable, user-data
  value, SSM Parameter, GitHub secret, workflow secret, or command-line argument
  that appears in logs/process listings.
- Do not use SSM shorthand `commands=[...]`; multi-line commands and secret
  handling need JSON `--parameters`.
- Do not use `set -x`, `printenv`, `env`, `journalctl` dumps, or unfiltered
  stderr/stdout around registration.
- Do not reuse one token for multiple runners. Tokens are short-lived and
  single-use; mint per target.
- Do not introduce a long-lived PAT on AWS hosts or in Terraform to verify
  runners. Verification belongs in the bootstrap operator process.
- Do not let automation silently fall back to the default VPC. Either provide
  an ADR-004-R20-compliant network or make the existing opt-in explicit.
- Do not make bootstrap depend on manual web-console copy/paste after claiming
  the path is automated.
- Do not collapse registration, removal, health checks, and network placement
  into one generic "runner manager" abstraction. Those lifecycles have different
  tokens and failure modes.
- Do not broaden the runner instance role with GitHub API credentials,
  `ssm:SendCommand`, `secretsmanager:*`, or broad KMS grants. The operator
  process drives SSM; the runner host should not be able to register itself
  with a stored GitHub credential.
- Do not weaken ADR guard, TFLint, Checkov, runner-network enforcement,
  actionlint, or self-hosted runner exposure checks to make bootstrap smoother.

## Non-Goals

- No implementation in this preflight note.
- No autoscaling runner fleet, webhook controller, GitHub App, or persistent
  token broker.
- No workflow scheduling redesign and no expansion of PR access to self-hosted
  runners.
- No new shared schema, parser, DTO, service, repository, exception hierarchy,
  or logging framework.
- No portal, range, GCP, GDC, Kubernetes, or application runtime changes unless
  a narrow documentation link needs updating.
- No promise that existing already-registered runners are migrated; replacement
  and re-registration remain separate lifecycle operations.

## Validation Expectations

For this preflight documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --files docs/architecture/github-runner-bootstrap-automation-preflight-1433.md --level fast
```

For the eventual implementation, run the repo-mandated checks for all touched
surfaces. At minimum:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
cd scripts/bootstrap && uv run pytest
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Add focused tests that prove:

- registration-token values are never printed in bootstrap logs;
- SSM `--parameters` is JSON and passed as one argv element;
- Terraform commands never receive a token-bearing variable or env binding;
- dry-run describes runner provisioning/registration without minting a token or
  sending SSM commands;
- registration verifies runner names/status through the GitHub API without
  requiring web-console steps.
