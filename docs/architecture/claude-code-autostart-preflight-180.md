# Claude Code Autostart Preflight (#180)

Status: pre-implementation guidance

Date: 2026-07-01

Issue: GitHub #180, "Add Claude Code autostart on range boxes"

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Treat this as range-guest interactive shell startup behavior, not a new terminal
runtime, experiment executor, agent orchestration framework, auth model, cloud
credential delivery path, or range schema.

The intended design is a guest-image or guest-bootstrap autostart hook that
launches the already installed Claude Code binary for interactive range-box
sessions. Keep the browser terminal transport as transport-only:
`mission_control.consumers.SSHConsumer` opens a terminal and streams bytes;
`engine.services.connect_terminal()` resolves the authorized target; the guest
shell decides what appears first.

Do not conflate this with experiment execution. The experiment path is a
non-interactive command-dispatch system governed by
`docs/architecture/ai-experiment-execution-boundary.md`,
`ScriptExecutionContext`, stream-json transcript capture, and policy payloads.
Range terminal autostart is user-interactive and must not inherit experiment
audit, artifact, or prompt-template assumptions.

## Architecture Decisions

- Put the primary autostart behavior in the existing range image/bootstrap
  surfaces that already install and configure Claude Code:
  `shifter/packer/scripts/kali/claude-code.sh`,
  `shifter/packer/scripts/ubuntu/claude-code.sh`, and, if Windows victims are
  in scope, `shifter/packer/scripts/windows/claude-code.ps1`.
- Use one canonical invocation string for this issue:
  `claude --dangerously-skip-permissions`. Do not add prompt flags,
  transcript flags, output-format flags, or additional privilege flags from the
  experiment executor unless the issue is deliberately expanded.
- Guard autostart behind interactive-session checks. A hook must require an
  interactive TTY, the expected guest user, `claude` on `PATH`, and a per-shell
  sentinel so subshells do not repeatedly launch Claude. Non-interactive SSH,
  SSM/Run Command, cloud-init, setup-runner commands, SFTP, and provisioning
  scripts must continue to work without entering Claude.
- Do not run Claude as root or elevate beyond the current terminal user. Linux
  sessions should remain `kali` or `ubuntu`; Windows terminal behavior, if
  included, inherits the existing `Administrator` SSH user and must be treated
  as an explicit victim-OS risk, not silently broadened.
- Preserve exit/restart ergonomics. Do not `exec` Claude from shell startup if
  that would close the shell when Claude exits. The user must be able to exit
  Claude back to a normal shell and restart it manually with the same canonical
  command.
- Keep model-provider credentials out of the hook. Claude should use the
  existing guest environment and cloud runtime credentials already established
  by the image/provisioner path. Do not bake AWS access keys, Bedrock tokens,
  Anthropic API keys, or provider secrets into AMIs, profile files, argv, logs,
  Terraform variables, or Kubernetes values.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #180 |
| --- | --- | --- |
| Claude Code install and Bedrock env | `shifter/packer/scripts/{kali,ubuntu,windows}/claude-code.*` | Extend the existing install/config scripts; do not create a second installer or model-env contract. |
| Range instance cloud access | `platform/terraform/modules/range/vpc/iam.tf`, `ssm-endpoints.tf` | Reuse the range instance profile and Bedrock VPC endpoint posture. Do not broaden IAM or add static credentials. |
| Browser terminal auth and origin gate | `config/asgi.py`, `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, `mission_control/routing.py` | Preserve websocket host/origin/session behavior; no token-in-URL shortcut. |
| Terminal capacity and lifecycle | `mission_control.consumers.SSHConsumer`, `mission_control.terminal_sessions`, `terminal_executor`, `TERMINAL_*` settings | Autostart must not add new sessions, bypass caps, or move terminal stream bytes into Redis/shared notifications. |
| Range/instance authorization | `engine.services.get_ssh_connection_info()` and `connect_terminal()` | Keep ownership, readiness, instance UUID, host, username, and secret-reference checks in engine services. |
| SSH client mechanics | `engine.ssh.SSHConnection` | Keep private keys in `asyncssh` process memory. Do not shell out to `ssh` or write temp key files to trigger Claude. |
| Guest setup/provisioning | Packer scripts, `shifter/engine/provisioner/templates/*`, `SetupOrchestrator`, `GuestSSHExecutor`, `SSMExecutor` | Autostart hooks must not break non-interactive setup commands or first-boot SSH readiness. |
| Shared contracts | `shared.schemas.InstanceContext`, `RangeContext`, `cyberscript.schemas.range.InstanceSpec` | Reuse existing `role` and `os_type` taxonomy; no duplicate range-box schema. |
| Errors and logging | `shared.errors`, websocket `WebSocketCloseCode`, `shared.log_sanitize` | Browser/API failures stay generic and authored. Do not log terminal streams, prompts, private keys, passwords, or provider tokens. |
| Polaris special case | `PolarisRangeBootstrapPlan`, `KALI_BEDROCK_SHARD_SCRIPT`, `scripts/polaris-aws-range/*` | Do not co-own Polaris container Bedrock sharding or end-of-game Claude retirement unless the issue explicitly includes Polaris container behavior. |
| GCP/GDC images | `shifter/packer/gcp/README.md` guest-specialization note | Do not claim GCP/GDC runtime Claude success unless model-provider credentials and egress are handled by the existing provider-specific path. |

## Cross-Cutting Layers

- Auth surface: the product browser path passes `@login_required` on the
  terminal page, `AllowedHostsOriginValidator`, `AuthMiddlewareStack`,
  `SSHConsumer._resolve_request()`, and engine ownership/readiness checks. A
  guest profile hook must not add its own auth decision or bypass these gates.
  Direct interactive SSH may also trigger a pure guest hook; if portal-only
  behavior is required, add an explicit terminal-owned marker from the existing
  `SSHConnection` path and keep the engine authorization seam authoritative.
- Secret-handling surface: portal SSH private keys are fetched through
  `engine.secrets` and never leave process memory. Guest model access uses the
  range instance profile, Bedrock endpoint, and `/etc/profile.d` env already
  owned by Packer/provisioner code. Do not put secret values in shell profile
  files, command arguments, logs, issue comments, or artifacts.
- Env-binding shape: reuse existing Claude env names
  `CLAUDE_CODE_USE_BEDROCK`, `AWS_REGION`, `ANTHROPIC_MODEL`, and
  `ANTHROPIC_SMALL_FAST_MODEL`. If a new toggle is required, make it a
  guest-local autostart toggle such as an `/etc/default` value or profile-script
  variable, not a Django setting, Terraform global, or new schema field unless
  runtime provisioning truly owns it.
- Config validators: Packer shell changes should satisfy the existing Packer
  tests and script checks. Python app changes, if any, must satisfy ruff and
  import-linter. Terraform/IAM changes must satisfy TFLint and existing IAM
  guard scripts. Architecture-affecting changes must pass ADR guard.
- OS/process exposure: `--dangerously-skip-permissions` is visible in the
  guest process list but is not secret-bearing. Credentials must come from
  instance metadata/provider runtime, not argv. The hook must start only in a
  PTY-backed interactive shell and must not intercept command-mode SSH,
  cloud-init, setup-runner, SSM, SFTP, or service startup.
- Error-envelope surface: failure to find or start Claude should degrade to a
  normal shell with a short local message, not close the websocket or surface a
  raw exception through the portal. Server logs should continue to record only
  connect/disconnect/close-code events and sanitized identifiers.
- Observability surface: use existing terminal connect/disconnect audit if the
  portal path is touched. A guest hook may emit bounded local shell text, but
  it should not create a new central audit store or log Claude input/output.
- Persistence surface: no database model, migration, durable range state,
  Redis key, or new repository is needed for this issue. The autostart state is
  per interactive shell through an environment sentinel or guest-local toggle.

## Extensibility Seam

The seam is a small guest autostart policy:

- enabled/disabled toggle;
- target users or roles (`kali`, `ubuntu`, and any explicit Windows victim
  decision);
- canonical Claude command argv;
- optional portal-only marker if pure direct-SSH autostart is rejected;
- provider/model environment source;
- local failure behavior.

The next likely changes are disabling autostart for an event, changing the
model IDs, adding a provider-native GCP model path, or narrowing the hook to
portal-launched browser terminals only. Those should be config/profile changes
around the hook, not rewrites of terminal authorization, range schemas,
experiment command generation, or cloud credential delivery.

## Whole-Repo Scope

Likely in scope for future implementation:

- `shifter/packer/scripts/kali/claude-code.sh`
- `shifter/packer/scripts/ubuntu/claude-code.sh`
- `shifter/packer/scripts/windows/claude-code.ps1` if Windows victim terminal
  acceptance remains in scope
- `shifter/packer/tests/test_packer.py` and `shifter/packer/tests/test_scripts.sh`
- `shifter/packer/gcp/README.md` or provider docs if GCP/GDC behavior is claimed
- `docs/architecture/ai-experiment-execution-boundary.md` only for boundary
  clarification, not to reuse the experiment policy

Usually out of scope:

- `mission_control.consumers`, `engine.services`, `engine.ssh`,
  `static/js/terminal.js`, and `terminal.html`, unless portal-only autostart
  requires an explicit marker or a real bug is found.
- Terraform IAM, VPC endpoints, security groups, NetworkPolicies, or range
  egress unless current Bedrock access is demonstrably insufficient.
- Experiment models, `ScriptExecutionContext`, artifact collection, transcript
  capture, queue workers, or run state machines.

## Gotchas And Anti-Patterns

- Do not put an unconditional `claude --dangerously-skip-permissions` at the
  end of `.bashrc`, `.profile`, or a PowerShell profile. It will break
  provisioning, command-mode SSH, SFTP, nested shells, or troubleshooting.
- Do not use `exec claude ...` if it prevents returning to a shell after exit.
- Do not autostart for root, service accounts, Packer builder users, setup
  runners, or non-interactive sessions.
- Do not add `-p`, shell-interpolated prompts, stream-json transcript handling,
  or artifact collection from the experiment executor. That is a different
  execution boundary.
- Do not duplicate `InstanceSpec.role` or `os_type` validation with local
  string taxonomies.
- Do not broaden the range instance IAM policy, open public egress, or add
  static AWS credentials to make Claude start successfully.
- Do not log terminal output, Claude prompts, provider errors with secret
  material, SSH keys, RDP passwords, Guacamole URLs, or environment dumps.
- Do not assume "Victim" means only Ubuntu. Current scenario contracts can
  resolve victims to Ubuntu or Windows via `from_agent`; either prove both or
  explicitly narrow acceptance before closing the issue.
- Do not silently claim Polaris container support. Polaris has separate
  container-level Bedrock sharding and Claude retirement behavior.

## Non-Goals

- No implementation is performed by this preflight.
- No implementation plan is encoded here.
- No formal Ground Control requirement or traceability work is attached.
- No redesign of browser terminal websockets, Guacamole, range provisioning,
  experiment execution, model-provider credential delivery, IAM, VPC endpoints,
  CTF participant filtering, or Polaris-specific Claude lifecycle.

## Validation Expectations

At minimum, a future implementation should run the repo architecture gate:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Run the stack-native checks for the touched surfaces: Packer tests/script
checks for image scripts, ruff and import-linter for Python app changes,
TFLint for Terraform/IAM changes, and Kubernetes validators for manifest
changes.
