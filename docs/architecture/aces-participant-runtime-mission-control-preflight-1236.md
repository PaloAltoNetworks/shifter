# ACES Participant Runtime And Mission Control Alignment Preflight

Issue: GitHub #1236, "07 - ACES migration: design participant runtime and
Mission Control alignment."

Status: pre-implementation architecture guidance. This note does not implement
models, migrations, APIs, UI, command execution, access flows, or a cutover.

ADR-027 note: legacy `cms.experiments` references in this preflight describe the
pre-removal state. Future experiment or participant command execution must use
a new ACES-backed design rather than restoring the deleted app.

## Boundary

ADR-024 remains the controlling migration decision: current Shifter behavior is
authoritative until a parallel ACES path passes the parity inventory,
manifest/conformance, portal/engine/provisioner, CTF, Mission Control, artifact,
status, audit, and validation gates. Legacy experiments are the ADR-027
exception.

The participant-runtime boundary for #1236 is four separate concerns:

- Participant semantics: ACES may define participant implementation records,
  participant identities/roles, runtime capabilities, behavior-history
  vocabulary, evidence expectations, and contract/profile versions.
- Runtime control: Shifter owns today's backend execution mechanisms for
  scripts, Claude prompts, SSM/ECS dispatch, status transitions, and artifact
  collection until ACES participant-runtime contracts and conformance exist.
- Access projection: Mission Control terminal, SSH, RDP/Guacamole, CTF
  participant range pages, and connection URL projections are Shifter runtime
  access behavior. They are not authored ACES scenario semantics.
- Product UI: Mission Control remains the product surface. ACES payloads can be
  projected into current UI/API views, but ACES does not own dashboard
  navigation, templates, websocket behavior, or user-facing lifecycle actions.

Per #1233, Shifter's first ACES backend claim is still `provisioning-only`.
The current stack must not claim ACES `participant_runtime` capability merely
because Shifter can open terminals, mint Guacamole URLs, run scripts, or cache
CTF participant range status.

## Architecture Decisions

- Keep current Mission Control access working during migration. Browser
  terminal, Guacamole RDP/SSH, range lifecycle actions, CTF participant range
  views, and experiment artifacts remain compatible until a later cutover issue
  deliberately replaces them.
- Add ACES participant implementation records as a first-class sidecar only
  after the matching ACES contract/profile exists. Do not hide canonical ACES
  participant/runtime/history records in `RangeInstance.range_spec`,
  `Range.provisioned_instances`, `ExperimentRun.metadata`, event payloads, or
  `AuditLog` JSON.
- Treat Python scripts and Claude prompts as execution inputs/capture intent,
  not durable ACES evidence by themselves. Rendered commands, raw prompt
  bodies, uploaded script bodies, transcript bodies, and private runtime values
  stay behind `ScriptExecutionContext`, experiment artifacts, and redaction
  policy.
- Command dispatch remains backend realization. Current automated execution
  goes through `cms.experiments.orchestrator.execution_plan`,
  `run_dispatch`, `run_artifacts`, `start_experiment_task`, and the
  provider/task-runner path. Do not introduce an ACES-only dispatcher, shell
  client, event bus, or workflow state machine.
- Behavior history and evidence must be append/reference oriented: sanitized
  participant/runtime ids, operation ids, artifact refs, digests, evidence
  type/profile, capture profile, redaction status, timestamps, and provenance.
  Do not store presigned URLs, upload tokens, Guacamole token URLs, SSH private
  keys, RDP passwords, command strings, prompt bodies, raw terminal streams,
  CTF flags, or raw provider diagnostics in ACES records.
- Guacamole, SSH, and browser terminal access are access channels. They may be
  referenced by an ACES-backed runtime projection as "available access," but
  their authorization, token lifecycle, capacity, audit, and secret handling
  remain Mission Control/engine responsibilities.
- CTF participants remain Shifter product actors with event/scoring/access
  semantics. Do not equate `CTFParticipant` with an ACES participant
  implementation record without an explicit mapping, profile, and evidence
  rule.

## Concept Mapping

| Shifter surface | ACES-aligned interpretation | Guardrail |
| --- | --- | --- |
| `CTFParticipant`, team, bracket, event registration | Shifter product participant actor | Not an ACES participant implementation record by default. |
| `RangeInstance` and `engine.Range` runtime state | Shifter runtime realization and projection | Mutable live state stays Shifter-owned. |
| Python `ScriptAsset` and `ExperimentScript` | Execution input / capture intent reference | Upload, inspection, size, S3 key, and ownership gates stay in experiment services. |
| Claude prompt assignment | AI execution input under policy | Preserve `ai-experiment-execution-v1`; no raw prompt in shell syntax, logs, audit, or ACES sidecars. |
| `ScriptCommand.command` | Backend dispatch realization | May be referenced by operation identity only; do not copy rendered command strings into ACES records. |
| `RunArtifact`, `ExperimentArtifact`, Claude transcripts | Evidence references | Store refs, digest, redaction state, provenance, and capture profile; no presigned URLs or raw secrets. |
| Browser terminal websocket | Interactive access projection | Reuse `SSHConsumer`, session caps, close codes, audit, and engine terminal services. |
| Guacamole RDP/SSH | Signed access projection | Reuse bootstrap TTL, consume-and-clear token lifecycle, affinity/topology decisions, and owner-scoped status. |
| Mission Control range APIs/UI | Product projection | Add read-only ACES-backed fields through existing serializers/auth/error envelopes only. |

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md`, ADR-024 | Keep ACES parallel and parity-gated. |
| Backend capability claim | `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md` | Do not claim participant runtime until contracts and conformance exist. |
| Operation/status projection | `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md` | Use `request_id`, sidecars, range projection, outbox, and reconciler seams. |
| Experiment-core boundary | `docs/architecture/aces-experiment-core-preflight-1235.md` | Keep participant runtime separate from study/run/evidence archival records. |
| AI execution policy | `docs/architecture/ai-experiment-execution-boundary.md` | Preserve `ScriptExecutionContext` and policy-versioned dispatch payloads. |
| Script upload/security | `cms.experiments.services._scripts`, `cms.experiments.s3`, `shared.uploads.inspection` | Reuse HMAC upload tokens, size equality, full-body UTF-8/binary inspection, S3 key normalization, and ownership. |
| Experiment dispatch | `cms.experiments.orchestrator.execution_plan`, `run_dispatch`, `run_artifacts`, `schemas` | Reuse transitions, idempotency keys in metadata, and AWS-only execution guard until widened deliberately. |
| Mission Control APIs | `MissionControlAPIView`, `MissionControlReadAPIView`, `mission_control.api.permissions`, `shared.api_tokens.scopes` | Use session/API-token auth, exact scopes, actor resolution, serializers, and legacy/canonical error handling. |
| HTML and lifecycle auth | `shared.auth`, `block_ctf_participant_only`, `threat_research_required`, `validate_cms_authoring_user` | UI hiding is not authorization; service-layer validation remains canonical. |
| Terminal access | `mission_control.consumers.SSHConsumer`, `terminal_sessions`, `terminal_executor`, `engine.services.connect_terminal`, `engine.ssh.SSHConnection` | Keep ownership/range/instance/key checks in engine services and transport/capacity in Mission Control. |
| Guacamole access | `mission_control.guacamole`, `guacamole_bootstrap`, `views/_guacamole*`, `GuacamoleBootstrapRequest` | Reuse JSON auth signing, bounded workers, token retry, TTL, consume-and-clear, and owner-scoped polling. |
| CTF participant access | `ctf.services.participant`, `ctf.services.range`, `ctf.bridges` | CTF crosses into CMS through bridges/services only; no Mission Control or engine direct imports. |
| Range projection events | `RangeEventOutbox`, `cms.handlers.range_events.apply_range_status`, `reconcile_range_events`, `mission_control.status_consumers` | No ACES-only event bus, websocket topic, or lifecycle enum. |
| Audit/logging | `risk_register.services.audit_log*`, `audit_session_event`, `shared.log_sanitize`, provisioner `log_redact` | Audit rows/logs carry sanitized ids/status/classes only. |
| Errors | `shared.errors`, `shared.api.errors`, `shared.exceptions.CMSError`, CTF/experiment exceptions | Translate at domain boundaries; do not add a duplicate ACES exception hierarchy. |
| Config/runtime env | `config/settings.py`, `config/env-manifest.json`, `config/_guacamole_settings.py`, `config/_capacity_settings.py`, `entrypoint.sh`, runtime inventory | New knobs need explicit settings and runtime binding, not handler-local env reads. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | ACES imports stay behind `shared` and service seams. |

## Cross-Cutting Layers

- Auth surface: Mission Control projections must use
  `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, exact
  `mission_control:*` scopes, and participant lifecycle blockers. CMS
  authoring/conformance work uses `CMS_READ_PERMISSIONS` /
  `CMS_WRITE_PERMISSIONS`, `HasCMSAuthoringActor`, and
  `validate_cms_authoring_user`. CTF participant/organizer flows keep their
  decorators and ownership checks.
- Validation and shape surface: script uploads use `ScriptUploadInput`, signed
  upload-token payloads, object-size equality, full-body text inspection, and
  normalized S3 keys. Prompt templates use `TemplateString` /
  `shared.template_vars`. Execution plans use `ScriptExecutionContext` and
  `ExperimentRun` / `RunStatus` transitions. Range state uses
  `ResourceStatus` and `engine.Range.Status`. ACES participant records need
  ACES contract/profile validation, not app-local string checks.
- Secret-handling surface: SSH private keys, RDP passwords, Guacamole JSON auth
  secrets, generated Guacamole URLs, presigned S3 URLs, upload tokens, prompt
  bodies, script bodies, transcript bodies, CTF flags, cloud credentials, and
  provider outputs stay out of logs, audit JSON, event payloads, DLQs, API
  responses, docs examples, issue comments, argv, env literals, and workflow
  summaries.
- OS/process exposure: browser terminal access consumes websocket FDs, SSH
  sockets, `asyncssh` process state, bounded terminal-executor slots, and audit
  writes. Automated command execution must continue through structured
  task-runner arguments keyed by ids. Do not move commands, ACES payloads,
  tokens, credentials, or provider diagnostics into shell strings, local SSH
  subprocess argv, Kubernetes Job env literals, or SSM command logs.
- Error-envelope surface: Mission Control legacy routes keep flat authored
  errors; canonical DRF routes use `shared.api.errors`; terminal websocket
  failures use `WebSocketCloseCode`; Guacamole bootstrap uses bounded
  `BootstrapFailure` messages. Raw ACES parser, SSM, SSH, Docker, Guacamole,
  storage, Terraform, or provider exceptions stay in sanitized logs.
- Persistence surface: live Shifter runtime state remains in existing CMS,
  engine, CTF, experiment, and Mission Control tables. ACES participant
  implementation/history/evidence records belong in version/profile-keyed
  sidecars with ownership, idempotency, retention, and redaction fields. Do not
  make JSON metadata columns the canonical ACES store.
- Event/projection surface: correctness-critical status propagation must reuse
  `RangeEventOutbox`, `drain_range_event_outbox`, `apply_range_status`,
  bridge hooks, and `reconcile_range_events`. Websocket fanout remains
  advisory and recoverable, not the only ACES projection path.
- Logging/observability surface: use `safe_log_value`, `safe_log_id`, and
  `safe_log_fingerprint`; log counts, durations, ids, status classes, protocol
  labels, and redaction classes. Do not log terminal streams, prompt/script
  content, generated commands, signed URLs, private keys, or raw artifact
  contents.
- Config/env validators: new participant-runtime profile, retention,
  projection, cleanup, or access-channel knobs must be explicit settings with
  env-manifest/runtime inventory coverage and provider render tests. Do not add
  opportunistic `ACES_*` reads inside views, handlers, migrations, or workers.
- Import-boundary surface: Mission Control may use `shared`,
  `management.services`, `cms.services`, and `engine.services`; CTF may use
  `shared`, `cms.services`, and `management.services`; CMS may use `shared`,
  `management.services`, and `engine.services`. Do not bypass these contracts
  to reach ACES sidecars or runtime details.

## Extensibility Seam

The required seam is an explicit participant-runtime profile/capability
discriminator at the sidecar and adapter boundary. The first value should be
read-only/compatibility mapping for Shifter participant implementation records;
it must not imply initialize/reset/restart/terminate participant-runtime
capability until ACES publishes those contracts and Shifter passes conformance.

Access variation needs a separate access-channel discriminator, for example
browser terminal, Guacamole RDP, Guacamole SSH, NGFW SSH, and backend command
dispatch. Access-channel records are projections over Shifter authorization and
runtime services, not authored scenario semantics.

Evidence variation belongs behind capture/evidence profile fields:
artifact type/profile, storage ref, digest, redaction state, provenance source,
and retention class. Future Python, Claude, transcript, pcap, terminal-session,
or manual-evidence variants should add profile branches behind the sidecar, not
edits across Mission Control views, CTF participant flows, experiment metadata,
engine models, and task payloads.

## Follow-Up Issues To File Or Confirm

- #1288: add ACES participant implementation sidecars and read-only runtime API
  projections with profile/version discriminators, ownership, idempotency,
  retention, and redaction fields. Implementation-slice guardrails live in
  `docs/architecture/aces-participant-runtime-api-sidecars-preflight-1288.md`.
- #1289: map scripts, prompts, command dispatch receipts, behavior-history
  events, transcripts, and artifacts to evidence records without copying
  rendered commands, raw prompts, raw scripts, token URLs, or terminal streams.
- #1290: surface ACES-backed participant/runtime/access projection fields
  through existing Mission Control APIs and UI while keeping current workflows
  and websocket behavior compatible. Implementation-slice guardrails live in
  `docs/architecture/aces-participant-runtime-mission-control-projections-preflight-1290.md`.
- #1291: update the backend manifest only when ACES participant-runtime
  lifecycle/history contracts exist and Shifter can prove conformance.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-migration-parity-inventory.yaml` rows
  `cyberscript.script-context`, `experiment.execution-plan`,
  `experiment.artifacts`, `mission-control.range-ui`,
  `aces.operation-api-projection`, `aces.range-ui-projection`,
  `mission-control.terminal-guacamole`, and `status.ctf-range`
- `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md`
- `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md`
- `docs/architecture/aces-experiment-core-preflight-1235.md`
- `docs/architecture/ai-experiment-execution-boundary.md`
- `docs/architecture/terminal-websocket-capacity-preflight-847.md`
- `docs/architecture/guacamole-token-affinity-preflight-928.md`
- `docs/architecture/guacamole-token-lifecycle-preflight-939.md`
- `shifter/shifter_platform/cms/experiments/**`
- `shifter/shifter_platform/mission_control/**`
- `shifter/shifter_platform/engine/services/_terminal.py` and
  `shifter/shifter_platform/engine/ssh.py`
- `shifter/shifter_platform/ctf/services/**`, `ctf/bridges.py`, and
  participant/range views only through existing seams
- `shifter/shifter_platform/cms/handlers/**`,
  `cms/management/commands/reconcile_range_events.py`, and
  `engine/management/commands/drain_range_event_outbox.py`
- `shifter/shifter_platform/shared/**`
- `shifter/shifter_platform/risk_register/services.py`
- `shifter/shifter_platform/config/**`, `entrypoint.sh`, and
  `config/env-manifest.json` for new settings
- provider/task-runner/deployment surfaces under `platform/terraform/**`,
  `platform/k8s/**`, `platform/charts/**`, and `scripts/gcp/**` only if
  runtime deployment contracts change
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, `docs/adr/index.yaml`, and
  `docs/adr/exceptions.yaml` if guardrails or exceptions change

## Gotchas And Anti-Patterns

- Do not claim ACES participant runtime because Mission Control can open SSH,
  RDP, Guacamole, or terminal sessions.
- Do not conflate CTF participants, Mission Control users, range instances,
  experiment runs, ACES participant implementation records, and backend
  execution targets.
- Do not add duplicate participant schemas, validation helpers, exception
  hierarchies, status taxonomies, event buses, websocket topics, artifact
  stores, upload-token formats, terminal session stores, or audit tables.
- Do not bypass `ScriptExecutionContext`, experiment services, Mission Control
  API permissions, engine terminal services, Guacamole bootstrap, CTF bridges,
  `RangeEventOutbox`, or shared API/error/logging helpers for ACES work.
- Do not store canonical ACES participant/history/evidence records in existing
  JSON fields just because they are convenient.
- Do not copy rendered command strings, prompt bodies, script contents,
  transcript bodies, terminal streams, provider dumps, presigned URLs,
  Guacamole token URLs, SSH private keys, RDP passwords, CTF flags, or cloud
  credentials into ACES sidecars, logs, audit, docs, API examples, or events.
- Do not make Mission Control templates or JavaScript responsible for
  participant-runtime authorization, status truth, or evidence redaction.
- Do not weaken `EXPERIMENTS_ENABLED`, import-linter, ADR guard, API-token
  exact scopes, Guacamole token lifecycle controls, terminal session caps, or
  secret-scanning policy during migration.

## Non-Goals

- No implementation of ACES participant-runtime models, migrations, APIs,
  handlers, execution services, UI, evidence collectors, or conformance checks
  in this preflight.
- No replacement of current Mission Control access workflows, Guacamole JSON
  auth, browser terminal websockets, CTF participant range pages, or experiment
  execution.
- No ACES participant-runtime capability claim in the backend manifest.
- No migration of CTF scoring, challenge semantics, participant invitations,
  or event lifecycle into ACES.
- No new Ground Control requirement UID for this requirement-free run.
- No GitHub issue creation by this preflight; #1236 implementation should file
  or confirm the focused follow-ups above before closure.

## Validation Expectations

For this design-doc change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation under `shifter/shifter_platform` also needs the
stack-native checks required by `AGENTS.md` and `.gc/plan-rules.md` for the
files it touches.
