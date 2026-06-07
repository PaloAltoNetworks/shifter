# Polaris Support Decomposition Preflight

Issue: GitHub #691, "Refactor Polaris scenario support scripts and large
scenario assets".

This note records the architecture boundary for the future refactor. It is
intentionally not an implementation plan.

## Boundary

This issue is a concrete decomposition issue, not the scenario expressiveness
parent. Long-term declarative scenario behavior remains owned by #620 and the
aces-sdl path documented in
`scenario-dev/polaris/design/aces-sdl-validation-path.md`.

The refactor must preserve the existing ownership split:

- Runtime per-range mutation belongs in
  `shifter/engine/provisioner/plans/polaris_range_bootstrap.py`, executed
  through `SetupOrchestrator` and `SSMExecutor`.
- Operator fleet scripts under `scripts/polaris-aws-range/` may orchestrate,
  inspect, or remediate already-provisioned ranges, but they must not become a
  second source of truth for behavior that new ranges need.
- Standalone CTFd board/page/user sync stays under `scripts/ctfd-workshop/`
  and uses the existing CTFd client and manifest validation paths.
- Polaris scenario content remains under `scenario-dev/polaris/`; the deployed
  live-event path is still `build/`, while `sdl/` plus `containers/` is the
  aces-sdl/APTL validation path.

Two historical hotfix sources named in the migrated issue,
`apply_kali_bedrock_shard.py` and `apply_splice_watcher.py`, are not present
as source in this checkout. Treat their source-removal as intentional unless
Git history proves otherwise. Do not resurrect them as top-level one-off
scripts; portable logic for new ranges belongs in `PolarisRangeBootstrapPlan`.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Range bootstrap behavior | `PolarisRangeBootstrapPlan`, `SetupStep`, `SetupOrchestrator`, `SSMExecutor` | Keep splice watcher, Bedrock shard, DNS override, Kali key, and tests fetch on the provisioner path for new ranges. |
| Provisioner template validation | `tests/test_plan_template_tokens.py`, `SetupOrchestrator._render_script` | Any moved setup script still passes the existing `{{word}}` placeholder lint. Do not introduce a parallel renderer. |
| SSM execution and output masking | `SSMExecutor`, `SetupOrchestrator._mask_sensitive_output` | New provisioner-owned execution should use the executor/orchestrator instead of ad hoc `send_command` loops. |
| Polaris AWS operator scripts | existing `orchestrate_provisioning.py`, `check_range_health.py`, `cleanup_non_keepers.py`, `sync_range_flags.py` conventions | Shared helpers should cover AWS session/client construction, instance discovery, SSM send/poll, JSON/event parsing, and sanitized reporting only. |
| CTFd API access | `scripts/ctfd-workshop/common.py::CtfdClient`, `sync_polaris_ctfd.py::get_all_items` | Reuse token auth, JSON requests, timeout handling, and pagination. Do not add `curl`, `requests`, or another CTFd client. |
| CTFd source manifests | `ctfd-challenges.json`, `ctfd-onboarding.json`, `ctfd-pages/` | Do not duplicate challenge names, flags, hints, prerequisites, pages, or tags into another schema. Validate and normalize the existing manifests. |
| Scenario smoke/UAT | `scenario-dev/polaris/tests/run-all-smoketests.sh`, `scenario_smoketest`, per-asset smoketests, `check_range_health.py` | Keep smoke tests exercising participant topology. Do not widen networks or bypass pivots to make tests pass. |
| Bake drift checks | `verify_flags_baked.py`, `test_verify_flags_baked.py`, `polaris-repo-to-ami-drift-audit.md` | Keep generated artifact verification separate from CTFd row sync and range-time smoke checks. |
| Scenario source order | `scenario-dev/polaris/README.md` | Reconcile against `build/`, CTFd JSON, and walkthroughs before older design prose. |
| Shared contracts | `shared.schemas` re-exporting `cyberscript.schemas`, `cms.scenarios.schema`, `cms.scenarios.hydrator` | Do not add a third range/scenario DTO stack inside Polaris support scripts. |

## Cross-Cutting Layers

Security layers the future design must satisfy:

- Auth surface: scripts remain operator-run CLIs or provisioner-internal setup
  steps. Do not add participant-facing Django routes, CTFd plugins, or browser
  controls for this refactor.
- CTFd token handling: preserve `CTFD_TOKEN` and token-file patterns. Do not
  expand process-argv token usage, print admin tokens, or copy tokens into
  participant containers.
- AWS credential selection: use boto3's credential chain or explicit
  `--profile` / `AWS_PROFILE` for operator scripts. Provisioner path should use
  instance profiles. Do not commit static AWS keys or pass them through argv,
  SSM parameters, or tracked reports.
- SSM command boundary: when code is provisioner-owned, run through
  `SetupStep`/`SSMExecutor`; when it remains an operator script, centralize
  send/poll behavior and keep command payloads JSON/base64-delimited rather
  than assembled from untrusted free-form text. Command failures may name
  command ids, instance ids, range ids, and step names, but not secrets.
- OS/process exposure: new subprocess calls must use argv arrays. Do not pass
  CTFd admin tokens, raw static flags, AWS secrets, participant credentials, or
  generated command bodies in process argv. Shell text sent to SSM must be
  generated from validated fields or fixed reviewed script bodies.
- Config/schema gates: CMS scenario YAML continues through
  `cms.scenarios.schema` and hydration into `shared.schemas.RangeSpec`.
  Aces-SDL files remain source-controlled scenario artifacts, not a replacement
  schema for live provisioning in this issue.
- Secret handling: CTFd admin tokens, AWS credentials, participant credentials,
  static flags, private keys, and Bedrock credentials must not be logged,
  committed as generated state, written to workflow artifacts, or echoed in
  error messages. Scenario-intent credentials that are deliberately part of the
  CTF content must stay documented as scenario content, not operational secrets.
- Error envelopes and logs: CLI errors should identify sanitized actor-neutral
  context such as range id, participant id, instance id, challenge id/name, row
  count, and action. Do not dump full API responses, shell scripts, traceback
  payloads containing generated scripts, authorization headers, or flag bodies.
- Repository validators: architecture/doc changes pass
  `python3 scripts/adr_guard/adr_guard.py --all --level ci`. Workflow edits
  also pass `actionlint`; Terraform edits pass the relevant TFLint gate; changes
  touching `shifter/shifter_platform` Python or imports pass the existing Ruff
  and import-linter gates.

Maintainability incumbents the implementation must build on:

- `PolarisRangeBootstrapPlan` for new-range runtime behavior.
- `scripts/ctfd-workshop/common.py`, `sync_polaris_ctfd.py`, and
  `sync_polaris_ctfd_onboarding.py` for CTFd transport and row reconciliation.
- `scenario_smoketest` and per-asset smoketests for range validation.
- `verify_flags_baked.py` for bake-time generated-artifact checks.
- `scenario-dev/polaris/README.md`, `design/shared-constants.md`, and
  `design/architecture.md` for scenario intent and cross-asset constants.

Extensibility seams:

- Put shared Polaris AWS helpers at the transport/target boundary: AWS session,
  EC2 target discovery, SSM send/poll, portal-container Django-shell transport,
  markdown/JSON status persistence, and sanitized event parsing. Do not make the
  helper a scenario orchestration framework.
- Keep script entrypoints as thin argparse subcommands or focused wrappers over
  those helpers: provision/batch control, health, cleanup, CTFd sync, and flag
  sync remain distinct lifecycles.
- Parameterize event id, region, profile, portal tag, AMI SSM parameter,
  batch/failure thresholds, output paths, and selected ranges. Do not hardcode
  the next event's constants into shared helper code.
- For large assets, split around stable review units: asset, mission, page, or
  generated-input package. If an artifact is generated/static and intentionally
  large, document its generator/source and verification gate rather than hiding
  it in an opaque blob.

Whole-repo surfaces in scope for the future implementation:

- `scripts/polaris-aws-range/**`
- `scripts/ctfd-workshop/**`
- `scenario-dev/polaris/build/**`
- `scenario-dev/polaris/sdl/**`
- `scenario-dev/polaris/briefing-deck/**`
- `scenario-dev/polaris/content-packages/**`
- `scenario-dev/polaris/containers/**`
- `scenario-dev/polaris/tests/**`
- `scenario-dev/polaris/design/**`
- `shifter/engine/provisioner/plans/polaris_range_bootstrap.py`
- `shifter/engine/provisioner/orchestrators/setup_orchestrator.py`
- `shifter/engine/provisioner/executors/ssm_executor.py`
- `shifter/shifter_platform/cms/scenarios/**`
- `shifter/shifter_platform/ctf/services/range.py`
- `.github/workflows/polaris-scenario-bake.yml` and related workflow checks if
  validation wiring changes
- ADR guardrails and `.gc/plan-rules.md` if enforcement policy changes

## Gotchas And Anti-Patterns

- Do not measure success by LOC alone. The refactor must remove duplicate
  lifecycle logic and improve review boundaries without hiding behavior behind a
  broad generic framework.
- Do not dual-own Bedrock shard, splice watcher, DNS override, Kali SSH key, or
  tests-fetch logic between operator scripts and `PolarisRangeBootstrapPlan`.
- Do not create duplicate CTFd schemas, range DTOs, challenge metadata models,
  exception hierarchies, logging wrappers, or validation layers.
- Do not make standalone CTFd scripts import Django settings, native CTF models,
  or database state. Semantic comparisons to native CTF services are fine;
  runtime coupling is not.
- Do not make Polaris operator scripts a new public API. They are event/support
  tooling around existing service/provisioner boundaries.
- Do not parse walkthrough Markdown and execute code fences. Walkthroughs are
  human-readable reference material; executable contracts live in scripts or
  adapters.
- Do not solve reviewability of SDL or briefing assets by moving scenario
  intent out of source control. Split or generate only when the source,
  generator, and verification path stay reviewable.
- Do not commit local Terraform state, provider caches, `.terraform/`, pyc
  files, generated reports, or provisioning state as part of this refactor.
- Do not weaken CI, ADR guardrails, TFLint, actionlint, import-linter, Ruff,
  gitleaks, or Kubernetes validators to make the decomposition land.

## Non-Goals

- Implementing the decomposition in this preflight.
- Delivering #620's scenario expressiveness work, replacing cyberscript with
  aces-sdl, or extracting generic APTL image templates.
- Replacing the range provisioner, `SetupOrchestrator`, `SSMExecutor`, CTFd
  sync scripts, smoke-test harnesses, or bake workflow architecture.
- Changing participant-facing challenge content, flags, hints, scoring,
  prerequisites, invite flows, auth, or event lifecycle except where a later
  implementation must preserve behavior during refactor.
- Rebaking AMIs, mutating live CTFd state, destroying ranges, creating new
  tracking issues, or running live AWS/CTFd operations.
