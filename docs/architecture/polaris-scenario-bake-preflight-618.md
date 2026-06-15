# Polaris Scenario Bake Preflight

Issue: GitHub #618, "Eliminate post-bake hotfix pattern: audit scenario
drift and reduce repo->AMI content gap".

This note records the architecture boundary for the future implementation. It
is intentionally not an implementation plan.

## Decision

Polaris has two legitimate delivery paths, and the implementation must keep
them separate:

- Runtime range customization belongs in
  `shifter/engine/provisioner/plans/polaris_range_bootstrap.py`, executed
  through `SetupOrchestrator` and `SSMExecutor`.
- Immutable scenario content belongs in the Polaris build tarball under
  `scenario-dev/polaris/build/`, then in the manually baked `polaris-vm` AMI
  referenced by `/shifter/ami/polaris-vm`.

The new bake workflow should only automate the deliberate operator path that
already exists manually: produce the Polaris build tarball, build and verify a
golden range, create the AMI, and update the SSM parameter. It must follow the
manual `workflow_dispatch` shape of `.github/workflows/packer.yml`; it must not
run on push or pull request events.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Runtime SSM setup | `PolarisRangeBootstrapPlan`, `SetupStep`, `SetupOrchestrator`, `SSMExecutor` | Add portable per-range logic here. Do not create another hotfix runner as the long-term source of truth. |
| Polaris bake range | `scripts/polaris-aws-range/*.tf`, `user_data.sh.tpl`, `reset.sh`, `check_range_health.py` | Reuse the existing Terraform, S3 tarball, bootstrap, reset, and health-check conventions instead of inventing a parallel bake stack. |
| Existing AMI workflow shape | `.github/workflows/packer.yml`, `.github/workflows/packer-promote.yml` | Keep operator-triggered OIDC AWS auth, least-privilege workflow permissions, step summaries, manifest/artifact upload, and SSM parameter updates. |
| Scenario source of truth | `scenario-dev/polaris/README.md`, `build/docker-compose.yml`, `build/ctfd-challenges.json`, `build/ctfd-onboarding.json`, `build/ctfd-pages/`, `tests/walkthroughs/` | Reconcile against build artifacts and walkthroughs before design prose. CTFd admin edits must be backported to these files. |
| Content validation | `scenario-dev/polaris/tests/run-all-smoketests.sh`, `isolation-smoketest.sh`, per-asset smoketests, `check_range_health.py` | Extend these harnesses for baked artifact drift; do not bury validation in a one-off workflow shell block. |
| CTFd sync | `scripts/ctfd-workshop/sync_polaris_ctfd.py`, `sync_polaris_ctfd_onboarding.py`, `sync_range_flags.py`, `common.CtfdClient` | Keep board/page/flag sync through these scripts. Bake automation should not duplicate CTFd API clients or schemas. |
| Security group guardrail | `scripts/check_tf_sg_cidrs/*` | Preserve per-range `/28` security-group scoping. Do not reintroduce shared wide-CIDR Polaris SGs. |
| ADR and workflow enforcement | `scripts/adr_guard/adr_guard.py`, `.gc/plan-rules.md`, `_quality.yml`, `actionlint` | Any workflow change must pass ADR guard and actionlint; guardrail weakening needs ADR documentation or a dated exception. |

## Baked Content Contract

On a clean checkout rebake, the only scenario runtime content that appears on a
fresh participant `polaris-vm` without an additional range-launch fetch is the
content packaged into `scenario-dev/polaris/build/` and copied by that tree's
Dockerfiles. The high-risk copied/generated surfaces are:

- A0 website and PDFs: `A0-boreas-website/site/` and
  `A0-boreas-website/build_pdfs.py` via `build/a0/Dockerfile`.
- A1 mail seed: `A1-mail-server/build_mail.py` via `build/a1/Dockerfile`.
- A3, A5, A10-A13 service code: their `server.py` files copied into images.
- A4 document seed: `A4-file-share/build_documents.py` via
  `build/a4/Dockerfile`.
- A6/A7/A8 lab material: generator scripts, GPG material, bare repos, SQL, and
  research keys copied by `build/a6`, `build/a7`, and `build/a8`.
- A9 splice content: README, scan results, and Modbus helper copied by
  `build/a9/Dockerfile`.
- A14 Kali overlay: `A14-kali/welcome.txt`, `claude_system_prompt.txt`, and the
  copied Modbus helper in `build/a14/Dockerfile`.
- A15/A16 pivot workstation content and credentials intentionally embedded for
  the CTF challenge path.
- DNS zone files and compose topology: `build/dns/*` and
  `build/docker-compose.yml`.

`scenario-dev/polaris/tests/` is the exception: current bootstrap fetches that
tree from S3 at range launch. CTFd board/page content is also separate from the
AMI path and remains owned by the CTFd sync scripts.

## Cross-Cutting Layers

Security layers the design must satisfy:

- Workflow trigger: `polaris-scenario-bake.yml` must be `workflow_dispatch`
  only. Do not add `push`, `pull_request`, schedules, or implicit deploy hooks.
- GitHub permissions and AWS auth: use `permissions: id-token: write,
  contents: read` and `aws-actions/configure-aws-credentials@v4` with the same
  dev/prod role secret pattern as the Packer workflows. Do not commit AWS keys
  or put them in workflow inputs.
- S3 artifact boundary: build tarballs are non-secret scenario artifacts, but
  the workflow must treat the S3 URI, bucket, and key as explicit operator
  inputs or checked-in constants. Do not derive shell commands from unvalidated
  free-form values.
- SSM parameter boundary: update only `/shifter/ami/polaris-vm`, and only after
  AMI creation and verification succeed. Preserve step-summary evidence.
- Runtime secret handling: Bedrock and guest credentials must remain runtime
  references or instance-profile access. Do not bake `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, CTFd admin tokens, or participant-specific SSH
  private keys into images, tarballs, workflow logs, argv, or SSM parameters.
- OS/process exposure: SSM and workflow shell commands must avoid printing
  secrets. Where temporary files are needed, use restrictive permissions and
  clean them up; do not pass secret values in process argv.
- Config validators: workflow edits pass `actionlint`; Terraform edits under
  `scripts/polaris-aws-range/` or `platform/terraform/` pass `tflint` where
  relevant; architecture work passes ADR guard.
- Error envelopes and logs: reuse `SetupOrchestrator` masking for provisioner
  setup output. Workflow and SSM failures may include instance IDs, AMI IDs,
  bucket/key names, step names, and validation names; they must not include raw
  secret values, CTFd tokens, or static Account B Bedrock keys from the legacy
  hotfix path.

Maintainability incumbents the implementation must build on:

- `PolarisRangeBootstrapPlan` for range-start mutation and verification.
- `scripts/polaris-aws-range/check_range_health.py` for range fleet health
  checks.
- `scenario-dev/polaris/tests/*` for participant-topology validation.
- `scripts/ctfd-workshop/*` for CTFd board and page synchronization.
- `scripts/check_tf_sg_cidrs/*` for Polaris cross-range network isolation.
- `.github/workflows/packer.yml` for manual AMI build workflow structure.

Extensibility seam:

Keep the bake workflow parameterized around the tarball source, bake ref, AWS
region/account target, AMI name/version metadata, and SSM parameter name. Keep
Bedrock model IDs and any future shard/account selection as explicit
provisioner context or release-managed config, not duplicated literals inside a
workflow shell block.

Whole-repo surfaces in scope for the future implementation:

- `.github/workflows/polaris-scenario-bake.yml` and any shared workflow docs.
- `scripts/polaris-aws-range/**` bake Terraform, bootstrap, reset, health, and
  operator scripts.
- `scenario-dev/polaris/build/**`, `tests/**`, `content-packages/**`, and
  `sdl/**` where the artifact audit touches source content.
- `shifter/engine/provisioner/plans/polaris_range_bootstrap.py`,
  `main.py`, `orchestrators/setup_orchestrator.py`, and
  `executors/ssm_executor.py` where runtime bootstrap changes are needed.
- `shifter/packer/scripts/*/claude-code.sh` when model defaults or standard
  AMI Claude behavior must stay aligned with Polaris.
- `scripts/ctfd-workshop/**` when CTFd board/page sync verification is part of
  drift detection.
- ADR guardrails, `.importlinter`, `.tflint.hcl`, `.gitleaks.toml`, and
  `.github/workflows/_quality.yml` if enforcement changes.

## Gotchas And Anti-Patterns

- Do not dual-own logic between `scripts/polaris-aws-range/apply_*.py` hotfixes
  and `PolarisRangeBootstrapPlan`. The bootstrap plan is canonical for new
  ranges; hotfix scripts are historical fleet remediation.
- Do not treat `content-packages/` as deployed just because it changed in the
  repo. The deployed artifact is whatever the clean checkout build generates
  into `build/` and then bakes into the AMI.
- Do not mask AMI staleness by always repairing image content at runtime. If
  the content is truly immutable participant content, fix the Dockerfile or
  generator and rebake.
- Do not put `welcome.txt` or other participant content in SSM hotfixes as the
  durable path. A14 image content belongs in `build/a14/Dockerfile`.
- Do not copy the Account B static-key branch from
  `apply_kali_bedrock_shard.py` into bootstrap or workflows without a separate
  secret-reference design. Prefer instance-profile access with the IMDS hop
  limit and VPCE/DNS fixes already documented in the provisioner path.
- Do not add another CTFd schema or client for board verification.
- Do not rely on old smoketest assumptions without reconciling them against the
  current compose topology; some historical tests and notes describe a
  pre-wired splice-link that the newer bootstrap explicitly removes at range
  start.
- Do not weaken per-range SGs, metadata tokens, encrypted root volumes, or
  CI/ADR enforcement to make the bake faster.

## Non-Goals

- Tying Polaris AMI bakes into push, pull request, or main deploy flows.
- Replacing the existing range provisioner, SSM executor, setup orchestrator,
  or CTFd sync scripts.
- Generalizing Polaris into a new scenario packaging framework.
- Migrating Polaris to aces-sdl or extracting generic container bases.
- Fixing the separately tracked flag 6 PDF content bug.
- Reworking Guacamole, participant invite flows, or CTFd account lifecycle.
- Keeping the live-event hotfix scripts as first-class deployment mechanisms
  after their portable logic has moved to canonical build or bootstrap paths.
