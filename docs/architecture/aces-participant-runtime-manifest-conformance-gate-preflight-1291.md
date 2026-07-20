# ACES Participant Runtime Manifest And Conformance Gate Preflight

Issue: GitHub #1291, "22 - ACES migration: add participant runtime manifest
and conformance gate."

Status: pre-implementation architecture guidance. This note does not implement
the manifest change, conformance runner, tests, API surface, runtime adapter,
cutover, rollback, or workflow replacement. This is a requirement-free run; the
GitHub issue is the shipping contract.

## Boundary

ADR-024 remains the controlling migration decision: current Shifter behavior is
authoritative until the parallel ACES path passes parity, manifest/conformance,
portal, engine, provisioner, CTF, Mission Control, artifact, status, and
validation gates. ADR-027 remains the exception for the removed legacy
experiments path.

#1291 is a guarded capability-widening issue. It may add an ACES
`participant_runtime` manifest claim and a conformance gate only after ACES
publishes the participant lifecycle, history, and evidence contracts that
Shifter can validate against. Until then, Shifter's published backend manifest
stays `provisioning-only`.

The issue must not turn current Mission Control terminal access, Guacamole
URLs, CTF participant range status, sidecar storage, or command dispatch into
an ACES participant-runtime protocol by naming them in the manifest. Those are
Shifter product/runtime access surfaces unless and until a published ACES
contract plus Shifter conformance evidence says otherwise.

## Architecture Decisions

- Keep `shared.aces.manifest` as the manifest source. Do not add a second
  manifest file, profile registry, local profile validator, or workflow-owned
  JSON template.
- Treat the manifest claim as an output of contract support plus conformance,
  not as a feature flag. `participant_runtime` remains null unless the ACES
  contract set and Shifter tests prove lifecycle/history/evidence compatibility.
- Keep participant-runtime sidecar storage and read projections separate from
  backend capability. `AcesParticipantRuntimeRecord` proves Shifter can persist
  bounded records; it does not, by itself, prove initialize/reset/restart/
  terminate lifecycle semantics or evidence-history protocol conformance.
- Add conformance coverage through ACES tooling and repo tests that assert the
  Shifter manifest, contract-version constants, sidecar validators, projection
  redaction, and diagnostics all agree. Do not duplicate ACES schemas in
  Mission Control, CTF, CMS, engine, or the provisioner.
- Failure diagnostics must be sanitized at the source. Conformance output may
  name profile ids, contract versions, record kinds, request ids, digests,
  bounded status classes, and report refs. It must not carry raw provider
  output, terminal streams, commands, prompts, scripts, tokens, CTF flags,
  credential values, Guacamole URLs, or presigned URLs.
- Rollback and cutover posture must be documented before replacing current
  workflows. Widening the manifest is not authorization to remove or redirect
  existing Mission Control, CTF, terminal, Guacamole, status, import, scope, or
  secret-scanning gates.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md`, ADR-024, `docs/architecture/aces-cutover-archive-plan-preflight-1238.md` | Keep ACES parallel and rollback-gated before workflow replacement. |
| Participant boundary | `docs/architecture/aces-participant-runtime-mission-control-preflight-1236.md` | Keep Mission Control/CTF access as Shifter-owned until ACES participant contracts and conformance exist. |
| Manifest source | `shared.aces.manifest`, `shared.aces.contracts`, `shifter/shifter_platform/shared/aces/backend-manifest.json` | Extend the existing builder/constants/artifact only after the contract gate is real. |
| Manifest tests | `tests/shared/aces/test_backend_manifest_publication.py` | Extend profile inference, required contracts, no-overclaim, no-realization-leakage, and artifact-sync tests. |
| Participant sidecars | `shared.models.AcesParticipantRuntimeRecord`, `shared.schemas.aces_participant_runtime`, `shared.aces.participant_runtime` | Reuse first-class sidecar validation, digest, idempotency, owner, retention, and redaction fields. |
| Read projections | `shared.aces.participant_runtime_projections`, `mission_control.api.aces_participant`, `mission_control.api.serializers` | Read through response allowlists and product authorization before sidecar lookup. |
| Operation evidence | `shared.models.AcesOperationRecord`, `shared.schemas.aces_operation`, `shared.aces.operations`, `shared.aces.projections` | Reuse the operation sidecar pattern for conformance evidence where records are operation/status/snapshot shaped. |
| Mission Control auth/errors | `MissionControlReadAPIView`, `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, `shared.api.errors` | Preserve exact scopes, actor resolution, legacy/canonical envelopes, and ownership-before-sidecar lookup. |
| API-token scopes | `shared.api_tokens.scopes`, `shared.api_tokens.permissions.require_scope`, `ApiTokenAuthentication` | Keep exact scopes. No wildcard, `aces:*`, or malformed-bearer session fallback. |
| Terminal access | `mission_control.consumers.SSHConsumer`, `terminal_sessions`, `terminal_executor`, `engine.services.connect_terminal`, `engine.ssh.SSHConnection` | Do not move authorization, key retrieval, capacity, close-code, or websocket behavior into ACES conformance code. |
| Guacamole access | `mission_control.guacamole`, `mission_control.guacamole_bootstrap`, `GuacamoleBootstrapRequest`, `docs/architecture/guacamole-token-lifecycle-preflight-939.md` | Preserve signing, TTL, consume-and-clear, owner-scoped polling, and token redaction. |
| CTF participant flows | `ctf.services.participant`, `ctf.services.range`, `ctf.bridges` | Keep CTF product identity, event access, scoring, and range lifecycle behind CTF services. |
| Logging and diagnostics | `shared.log_sanitize`, provisioner `log_redact`, `shared.schemas._aces_validation`, `shared.aces.status` | Use existing sanitizers, diagnostic-ref allowlists, size caps, single-line refs, and secret-pattern rejection. |
| Config/runtime env | `config/settings.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py`, deploy renderers | New conformance/cutover knobs need typed settings and inventory/render coverage; no handler-local env reads. |
| Enforcement | `docs/architecture/aces-migration-parity-inventory.yaml` row `validation.participant-runtime-conformance`, `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Keep repo gates blocking; do not weaken them to make the participant-runtime claim pass. |

## Cross-Cutting Layers The Design Must Pass

- ACES contract/profile validation: use the published ACES lifecycle/history/
  evidence models and conformance runner. Shifter tests may assert integration,
  expected contract coverage, and sanitized output shape, but they must not
  reimplement ACES profile semantics with local string checks.
- Manifest publication surface: `create_shifter_backend_manifest()`,
  `render_shifter_backend_manifest_payload()`, `SHIFTER_BACKEND_PROFILE`,
  `SHIFTER_SUPPORTED_CONTRACT_VERSIONS`, and
  `shifter/shifter_platform/shared/aces/backend-manifest.json` must move together. A mismatch between
  builder, constants, and checked-in artifact is a failure.
- Auth surface: any API that serves conformance status or participant-runtime
  projections keeps `ApiTokenAuthentication` fail-closed behavior, session auth,
  `HasMissionControlActor`, exact `mission_control:range:read`, CMS authoring
  scopes where CMS-owned, and product ownership checks before sidecar reads.
- Sidecar validation surface: participant lifecycle/history/evidence records
  reuse shared validators for supported profile/version pairs, field
  allowlists, bounded JSON, digest equality, idempotency keys, timezone-aware
  timestamps, retention/redaction fields, diagnostic refs, and secret-bearing
  key/value rejection.
- Error-envelope surface: canonical `/api/v1` failures use
  `shared.api.errors`; legacy Mission Control compatibility keeps
  `MissionControlAPIView` flat errors. Raw ACES parser, conformance, DB,
  provider, Terraform, SSM, SSH, Docker, storage, Guacamole, or CTF exceptions
  become curated messages plus sanitized diagnostic refs.
- Secret-handling surface: manifest, sidecars, conformance reports, logs, API
  responses, audit rows, events, DLQs, workflow summaries, docs examples,
  argv, and env literals must exclude private keys, RDP passwords, Guacamole
  token URLs, bearer/presigned URLs, upload tokens, prompts, scripts, command
  strings, terminal streams, transcripts, CTF flags, cloud credentials,
  provider dumps, and raw ACES package bodies.
- OS/process exposure: conformance commands use structured argv with bounded
  paths, profile ids, and report refs only. Do not pass contract payloads,
  tokens, credentials, provider diagnostics, Terraform variables, generated
  commands, or runtime configs through shell strings, Kubernetes Job env
  literals, SSM command text, or local subprocess argv.
- Config/env validators: conformance enablement, report paths, profile
  selectors, retention, cleanup, or cutover switches must flow through typed
  Django settings and the env-manifest/runtime-inventory/render-test path if
  runtime configurable. Do not add opportunistic `ACES_*` reads in views,
  validators, migrations, or workers.
- Event/projection surface: Shifter lifecycle and status remain
  `RangeEventOutbox`, drainers, CMS handlers, reconcilers, CTF bridges, and
  Mission Control status consumers. Participant-runtime conformance must not
  add a second event bus, websocket topic, lifecycle enum, or status pipeline.
- Logging/observability surface: log counts, durations, profile ids, contract
  versions, record kinds, sanitized request ids, redaction states, report refs,
  and digests. Use `safe_log_value`, `safe_log_id`, or
  `safe_log_fingerprint`; never payload dumps or raw diagnostics.
- Import-boundary surface: ACES imports stay behind `shared` and accepted
  service seams. Mission Control, CTF, CMS, engine, and provisioner code must
  not import ACES SDL/conformance internals directly unless an explicit shared
  facade is added and import-linter permits it.
- Workflow/security gates: ADR guard, import-linter, exact API-token scopes,
  Guacamole token lifecycle, terminal capacity/close-code controls, secret
  scanning, actionlint, Terraform, Kubernetes, and runtime-env validation
  remain enabled for touched surfaces.

## Extensibility Seam

The seam is the backend profile/capability discriminator plus participant
runtime profile at the shared ACES boundary:

- manifest profile/capability: `provisioning-only` today; a later
  participant-runtime value only when published ACES contracts and Shifter
  conformance exist;
- participant-runtime profile: currently `shifter-provisioning`; future values
  are added to `SHIFTER_SUPPORTED_PARTICIPANT_RUNTIME_PROFILES` and validators,
  not hardcoded in product views;
- record-kind/contract-version mapping: lifecycle, history, and evidence
  variants add explicit record kinds or contract-version branches behind shared
  validators and projection helpers;
- report/evidence output: conformance report refs and digests are parameters,
  not embedded provider output or workflow-specific paths.

The next reasonable variation is another ACES participant-runtime contract
version, access-channel profile, evidence profile, or backend capability. That
variation should add one shared profile/record/projection branch, not edits
across Mission Control templates, CTF services, engine models, provisioner
payloads, event JSON, and workflow scripts.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md`
- `docs/architecture/aces-participant-runtime-mission-control-preflight-1236.md`
- `docs/architecture/aces-participant-runtime-api-sidecars-preflight-1288.md`
- `docs/architecture/aces-operation-sidecar-persistence-preflight-1273.md`
- `docs/architecture/aces-operation-api-projections-preflight-1275.md`
- `docs/architecture/aces-snapshot-retention-redaction-audit-preflight-1277.md`
- `docs/architecture/aces-cutover-archive-plan-preflight-1238.md`
- `docs/architecture/aces-legacy-stability-guardrails-preflight-1239.md`
- `docs/architecture/aces-migration-parity-inventory.yaml` rows
  `validation.participant-runtime-conformance`,
  `validation.aces-manifest-conformance`,
  `aces.participant-runtime-sidecars`,
  `aces.participant-history-evidence`,
  `aces.participant-access-projection`,
  `mission-control.terminal-guacamole`, and `status.ctf-range`
- `shifter/shifter_platform/shared/aces/**`
- `shifter/shifter_platform/shared/schemas/**`
- `shifter/shifter_platform/shared/models.py`
- `shifter/shifter_platform/shared/api_tokens/**`
- `shifter/shifter_platform/mission_control/api/**`
- `shifter/shifter_platform/mission_control/consumers.py`
- `shifter/shifter_platform/mission_control/guacamole*.py`
- `shifter/shifter_platform/engine/services/**`
- `shifter/shifter_platform/cms/services/**`
- `shifter/shifter_platform/ctf/services/**` and `ctf.bridges`
- `shifter/shifter_platform/config/**`,
  `config/env-manifest.json`, and `shifter/installation/runtime_inventory.py`
  if settings are introduced
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, `.gc/plan-rules.md`, and stack-native validators for
  any touched workflow, Terraform, Kubernetes, or runtime-env surface

## Regression Evidence Expectations

- Manifest tests prove the manifest does not claim `participant_runtime` before
  the published ACES contracts and Shifter conformance gate exist.
- When the claim is enabled, tests prove supported contract versions cover the
  ACES lifecycle/history/evidence contract set and profile inference matches
  the widened claim.
- Conformance tests or workflow evidence prove failure diagnostics are
  sanitized and bounded, including negative cases with provider-shaped errors,
  token-shaped strings, raw command/prompt/script-shaped fields, and oversized
  diagnostic payloads.
- Sidecar/schema tests cover lifecycle/history/evidence record kinds,
  profile/version mismatches, digest mismatches, idempotency conflicts,
  retention/redaction fields, diagnostic refs, and secret rejection.
- Projection/API tests cover session users, API tokens with exact scopes,
  missing scopes, malformed bearer tokens, unknown/not-owned request ids,
  response allowlists, and non-ACES compatibility when no sidecar rows exist.
- Compatibility tests prove existing Mission Control range pages, terminal,
  Guacamole, CTF participant range access, ADR guard, import-linter, exact
  scopes, terminal caps, Guacamole lifecycle, and secret scanning remain
  enabled and behaviorally stable.
- Cutover/rollback documentation cites the selector, rollback posture,
  evidence bundle, and workflows that remain current before any replacement of
  existing Mission Control or CTF paths.

## Gotchas And Anti-Patterns

- Do not claim ACES `participant_runtime` because Shifter has terminals,
  Guacamole, CTF participants, sidecar rows, or command dispatch.
- Do not make `AcesParticipantRuntimeRecord` a substitute for lifecycle,
  history, or evidence conformance.
- Do not create local ACES lifecycle/history/evidence schemas, validators,
  exception hierarchies, token scopes, event buses, websocket topics, status
  enums, audit stores, or conformance checklist DSLs.
- Do not authorize by sidecar existence, catalog visibility, UI controls, or
  conformance pass state. Product auth and ownership checks run first.
- Do not return or log raw conformance failures, ACES payloads, diagnostics,
  snapshots, provider dictionaries, terminal streams, prompts, scripts,
  command strings, token URLs, private keys, CTF flags, or presigned URLs.
- Do not route conformance through shell fragments, broad env dumps,
  Kubernetes env literals, SSM command strings, or workflow summaries that can
  expose payloads or secrets.
- Do not weaken ADR guard, import-linter, exact API-token scope validation,
  Guacamole token lifecycle, terminal session controls, secret scanning,
  actionlint, Terraform, Kubernetes, or runtime-env inventory to make the
  participant-runtime claim pass.
- Do not replace current Mission Control, CTF, terminal, Guacamole, or status
  workflows without explicit cutover and rollback documentation.

## Non-Goals

- No implementation in this preflight note.
- No manifest capability widening until ACES publishes matching contracts and
  Shifter conformance evidence exists.
- No RuntimeTarget rewrite, command dispatcher, mutation API, new public
  `/api/v1/aces/` surface, websocket change, terminal/Guacamole behavior
  change, CTF workflow change, or provider/provisioner workflow replacement.
- No new Ground Control requirement UID for this requirement-free run.
- No ADR registry or exception update unless a later implementation changes an
  enforceable guardrail or needs a documented exception.
- No changelog fragment for this docs-only preflight note.

## Validation Expectations

For this architecture note, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future implementation under `shifter/shifter_platform` should also run the
manifest publication tests, shared ACES schema/sidecar/projection tests,
Mission Control API-token tests, relevant CTF/Mission Control compatibility
tests, import-linter, and stack-native checks for any touched workflow,
Terraform, Kubernetes, or runtime-env surface.
