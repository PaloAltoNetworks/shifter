# Smoke-Test / QAT Design Architecture Preflight (#983)

Status: pre-design guidance

Date: 2026-07-18

Issue: GitHub #983, "Design a smoke-test / QA (QAT) system for common range
infra and a basic scenario".

This issue is requirement-free. Its title, body, and acceptance criteria are
the contract. This note records repository-wide boundaries that the design
must respect; it is not the QAT design, an implementation plan, a requirements
set, or a follow-up-issue breakdown.

## Scope Boundary

The design is for an on-demand product-readiness protocol against an explicit,
known-up deployment. It is not a deployment gate and must not make a live range
an implicit prerequisite of deployment success.

Keep the following proofs separate even if one operator run presents their
evidence together:

1. `scripts/stack-smoke/stack_smoke.sh` proves that the built production image
   boots locally with controlled doubles. It deliberately does not prove a live
   terminal or Guacamole session against a range.
2. `.github/workflows/_shifter-platform.yml` and
   `scripts/portal_deploy/portal_deploy.py verify-post-deploy` prove deployed
   service health. A healthy portal is not a usable range.
3. `scripts/smoke-test.sh` and `cms.post_deploy_smoke` prove that the platform
   can request a live range, observe `READY`, resolve an SSH/RDP connection, and
   reach a guest port. They do not currently prove the external participant
   journey, an authored-channel contract, or scenario behavior.
4. Mission Control's range, terminal, and Guacamole paths are the product
   boundaries that a participant-use proof must exercise. A TCP connection,
   WebSocket handshake, accepted bootstrap request, and completed interactive
   exchange are different evidence levels.
5. ADR-041 scenario verification proves scenario-specific behavior through an
   explicitly selected installed plugin. It is not range orchestration,
   deployment health, or a generic infrastructure-check framework.
6. `range_escape` validation proves participant-origin isolation. The event
   load harness proves capacity behavior. Neither is a substitute for the QAT
   happy path, and the QAT happy path is not a substitute for either one.

The eventual design must name which of these are prerequisites, which are QAT
phases, and which remain separate readiness evidence. It must not collapse them
into one undifferentiated `smoke passed` signal.

## Architecture Decisions and Guardrails

- Keep execution on demand. A future workflow or operator entry point must be
  separate from the deploy dependency graph and target a positively selected
  environment. Changing deploy-gating policy requires a separate architecture
  decision.
- Exercise the participant-facing product boundary for claims about product
  usability. Mission Control's versioned HTTP API owns external request shape,
  auth, scopes, permissions, throttling, and error envelopes; its WebSocket and
  Guacamole paths own interactive access. An in-process management command may
  remain useful for controlled setup or cleanup, but it cannot establish that
  the external product journey works.
- Reuse the existing range lifecycle. Create, query, and destroy through
  Mission Control/CMS services. Do not write `RangeInstance` or Engine state
  directly, invoke Terraform/provider SDKs as the range orchestrator, or create
  a QAT-private lifecycle model.
- Define the common-range proof in terms of provider-neutral platform
  postconditions from ADR-039: validated realization, `READY`, declared access
  bindings, usable brokered access, and completed cleanup. Direct cloud-resource
  inspection can be provider-specific diagnostic evidence, not the common
  contract.
- Resolve access through `engine.services._terminal` and the Mission Control
  brokers. They already enforce actor ownership, current membership, `READY`,
  declared participant channel, target resolution, and just-in-time secret
  access. Never accept or infer an arbitrary host, port, or protocol in order to
  bypass those checks.
- Preserve ADR-041 as the only scenario-behavior extension seam. Core owns the
  versioned verification contracts, deterministic discovery, bounded runner,
  closed result semantics, and redacted report. Scenario answers, topology,
  commands, and adapters stay in an explicitly selected, version-pinned
  out-of-tree distribution. Do not turn that framework into a range lifecycle
  controller or put generic infrastructure checks into its report model.
- Select and describe the acceptance scenario deliberately. The hidden
  `smoke_linux` and `smoke_windows` templates are infrastructure fixtures with
  no scenario content, so they cannot be relabelled as a basic-scenario proof.
  The catalog's `basic` template uses `from_agent`, so its agent asset and OS
  selection are real preconditions. The design must either account for those
  through existing agent services or explicitly select a different normal,
  schema-valid fixture; it must not silently fork the scenario schema.
- Define evidence at the semantic level claimed. For terminal use, a successful
  WebSocket upgrade alone is insufficient; evidence needs a harmless,
  nonce-correlated command/output exchange through the normal terminal path.
  For Guacamole, HTTP `202` only proves queue admission. Bootstrap completion,
  owner-scoped one-time URL consumption, and an actual Guacamole client session
  are distinct claims, and the design must state which one constitutes use.
  The URL/token is a credential and never becomes report evidence.
- Cleanup is a postcondition, not a best-effort afterthought. Teardown must use
  the canonical request-id ownership path and observe a terminal destroyed or
  absent outcome. A submitted destroy task is not completed cleanup. Preserve
  both the primary failure and any cleanup failure; cleanup failure makes the
  run non-successful and must not overwrite the primary cause.
- Results must fail closed. Required checks that are missing, skipped,
  `blocked`, `error`, timed out, or unknown cannot be counted as pass. Keep
  `ResourceStatus`, HTTP/WebSocket outcomes, scenario-verification status, and
  an overall QAT conclusion as distinct concepts rather than creating enum
  aliases between them.
- Evidence is operator-facing and ephemeral unless the design establishes a
  separate retention requirement. A run envelope may correlate existing
  results, but it must not duplicate ADR-041 declarations/results or become a
  new source of range truth. Include bounded identifiers and provenance such as
  run id, request id, environment, observed backend/provider, scenario/plugin
  identity and version, artifact revision, check code, duration, and cleanup
  conclusion. Exclude credentials, answers, internal addresses, raw provider
  payloads, unbounded process output, and raw exceptions.
- No new application runtime setting or persistence table is justified by this
  design by default. The runner's non-secret target profile and ephemeral
  evidence belong outside Django runtime configuration. If the later design
  truly requires a deployed setting or durable state, it must use the canonical
  env manifest or persistence/service boundary and justify the new ownership.

These guardrails are already supported by accepted architecture decisions and
existing service contracts. This preflight does not add another ADR. A later
ADR is warranted only if the design changes deploy-gating policy, introduces a
new credential or durable evidence model, changes public API contracts, or
creates a new repository-wide verification contract beyond ADR-041.

## Canonical Incumbents to Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Built-image verification | `scripts/stack-smoke/stack_smoke.sh`, `scripts/stack-smoke/README.md`, `_quality.yml` | Keep range-dependent QAT out of the hermetic image boot contract; reuse its bounded diagnostics and cleanup discipline. |
| Deployment health | `.github/workflows/_shifter-platform.yml`, `scripts/portal_deploy/portal_deploy.py verify-post-deploy` | Treat service health as a known-up precondition; do not duplicate it or weaken its fail-loud behavior. |
| Existing live-range smoke | `scripts/smoke-test.sh`, `scripts/post_deploy_smoke/`, `cms.management.commands.run_post_deploy_smoke`, `cms.post_deploy_smoke` | Reuse useful lifecycle, bounded-polling, variant, and cleanup behavior. Do not inherit its AWS/deploy coupling, raw TCP proof, internal Django execution, or raw exception reporting as the QAT contract. |
| Scenario parsing and validation | `cms.scenarios.loader`, `cms.scenarios.schema`, `cms.scenarios.hydrator`, `cms.scenarios.registry`, `shared.schemas` | Load an ordinary validated scenario and its existing agent/content references; no QAT YAML dialect, duplicate DTO, or OS/channel inference. |
| External lifecycle API | `mission_control.api._base`, `mission_control.api.ranges`, `mission_control.api.serializers`, `shared.api.errors` | Reuse DRF serializers, permissions, throttles, safe errors, and CMS services. Do not reproduce request validation in a client or expose an internal service DTO. |
| Domain lifecycle | `cms.services.create_range`, range query/lifecycle helpers, `destroy_range_by_request_id`, Engine dispatch/state | Preserve active-range admission, idempotency/correlation, ownership, audit, state transitions, backend admission, and terminal cleanup. |
| Backend realization | ADR-039 `provider-neutral-range-substrate.md` and root-selected backend bundles | Observe the selected deployment/backend and public postconditions; do not add provider switches or a third topology/resource schema to QAT. |
| Terminal access | `engine.services._terminal`, `mission_control.consumers.SSHConsumer`, `mission_control.status_consumers.RangeStatusConsumer`, `config.asgi` | Reuse member/channel/readiness/secret checks, origin validation, session auth, capacity limits, close codes, and the existing JSON message contract. |
| Guacamole access | `mission_control.api.guacamole`, `mission_control.guacamole_bootstrap`, `mission_control.guacamole`, Guacamole views | Reuse serializer/scope/ownership validation, bounded bootstrap state, one-time URL consumption, just-in-time secret resolution, and signed-token construction. Never persist or disclose the returned URL. |
| API authentication and authorization | `shared.api_tokens.authentication`, `shared.api_tokens.scopes`, `mission_control.api.permissions`, Django session/CSRF middleware | Use a dedicated active actor and exact existing scopes. Bearer auth covers HTTP but does not automatically authenticate Channels WebSockets; the design must use the real session/cookie boundary where required. |
| Scenario behavior verification | ADR-041 `scenario-verification-plugin-seam-adr.md`, `shared.scenario_verification`, `docs/technical/shifter_platform/scenario-verification.md` | Compose with the selected installed plugin and injected runner; do not ship answers/adapters in core or create a second plugin/result/runner contract. |
| Isolation validation | `shared.range_escape`, `cms.range_escape`, `run_range_escape_validation`, `docs/ops/range-escape-validation.md` | Keep adversarial participant-origin escape evidence as a separate security gate; do not infer isolation from successful happy-path access. |
| External-client safety | `uat/event-load-harness` | Reuse positive target acknowledgement, production refusal, origin/cookie discipline, actor-file permissions, redaction, and bounded execution patterns. Do not reuse load metrics as QAT status or treat its current handshake-only routes as functional proof. |
| Logging, safe errors, and audit | `config.logging.ECSFormatter`, `shared.log_sanitize`, `shared.errors.classify_user_message`, `shared.api.errors`, existing Mission Control/CMS audit events | Emit safe authored codes and bounded messages. Reuse existing mutation audit rather than creating QAT audit rows; correlate with request/run ids. |
| Runtime configuration | `config/_env_manifest.py`, generated `config/env-manifest.json`, installation runtime inventory/renderers, provisioner allowlists/admission | Keep runner profiles external and non-secret. Any genuinely new deployed key must traverse every canonical manifest/render/admission layer. |
| Workflow trust | ADR-003/ADR-004 workflow rules, `credentialed-workflow-dispatch-trust-preflight-1690.md`, current environment-bound OIDC/WIF workflows | Use a separate trusted manual entry, protected ref/environment, SHA-pinned actions, and job-local least privilege. Do not reuse a broad deploy role merely because the old smoke runs after deploy. |
| Repository enforcement | `scripts/adr_guard/adr_guard.py`, `.importlinter`, `actionlint`, TFLint, kube-linter, kubeconform | Preserve the native checks for every touched subsystem and update ADR enforcement docs if a guardrail itself changes. |

Paths under `cms`, `mission_control`, `engine`, `shared`, and `config` in this
table are rooted at `shifter/shifter_platform/`.

## Cross-Cutting Layers the Design Must Pass

### Authentication, authorization, and object policy

- HTTP automation passes `ApiTokenAuthentication` or the normal Django session
  stack, exact `mission_control:*` scope checks, active-actor checks, object
  ownership, participant lifecycle policy, throttling, and CSRF where session
  auth applies. A token scope is not object ownership, and neither one replaces
  range membership/readiness checks.
- WebSockets pass `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, consumer
  ownership and capacity checks, and canonical `WebSocketCloseCode` handling.
  An API token does not create a browser WebSocket session.
- Guacamole passes serializer shape validation, `guacamole:read`, active actor,
  instance membership/readiness, one-time owner binding, and expiry. A QAT-only
  bypass endpoint, CSRF exemption, superuser shortcut, or direct guacd token
  construction would invalidate the product claim.

### Shape, parser, and domain validation

- The target scenario passes YAML `safe_load`, the Pydantic discriminated
  models in `cms.scenarios.schema`, registry/hydration validation, strict ids,
  agent/content prerequisites, and participant-access declarations.
- External lifecycle and Guacamole payloads pass the existing DRF serializers;
  the client may validate its own input manifest but must not fork server DTOs
  or duplicate domain validation.
- The realized range passes CMS admission and the provider-neutral substrate.
  Backend identity comes from validated installation/root configuration and
  observed deployment metadata, not an untrusted request field or filename.
- ADR-041 discovery/declarations/results pass the core verification validators.
  Exact installed distribution, version, and entry point are the authorization
  boundary; scenario content cannot select arbitrary code.

### Secrets, environment binding, and process/OS exposure

- API tokens, passwords, session/CSRF cookies, SSH keys, Guacamole tokens/URLs,
  cloud credentials, secret references, and scenario answer material are all
  secret-bearing. Keep them out of argv, command strings, broad environment
  dumps, workflow annotations, logs, reports, issue bodies, screenshots, and
  artifacts.
- Use fixed argv, no `shell=True`, no operator-supplied shell fragments, bounded
  stdin/stdout/stderr, explicit deadlines, and cancellation. Command-line
  parameters may carry non-secret ids and permissioned file paths only.
- Any temporary actor/session material must be short lived, gitignored, and
  mode `0600`; host/origin changes and redirects must fail closed. Harmless
  guest probes must be idempotent, nonce-correlated, and bounded.
- A runner target profile should contain only explicit non-secret facts:
  environment/URL, observed backend/provider expectation, scenario and fixture
  references, actor reference, selected protocol/check profile, deadlines,
  cleanup policy, and evidence destination. Secrets are resolved through their
  existing owning boundary just in time.
- If any value must enter deployed process configuration, it passes
  `_env_manifest.py`, generated manifest parity, installation inventory,
  runtime rendering, and any Engine/GKE allowlist or admission shape. Adding an
  isolated workflow env var does not satisfy those cross-layer contracts.

### Network and host boundaries

- A runner's network vantage point is part of the evidence. Do not open a
  security group, firewall, `NetworkPolicy`, public IP, or arbitrary ingress
  merely to make runner-origin SSH/RDP pass. Browser terminal traffic remains
  browser -> portal WebSocket -> declared member; Guacamole remains browser ->
  portal bootstrap -> guacd -> declared member.
- Logical `{target_ref, channel}` resolves to a realized closed binding. Recheck
  authorization, `READY`, membership, and channel before secret resolution and
  dial. Never trust a scenario-supplied address or expose raw provider bindings
  in a product/report DTO.
- Successful happy-path access is not an isolation proof. Provider-specific
  isolation and escape validation remains independently required where event
  readiness calls for it.

### Errors, observability, and evidence envelopes

- HTTP errors remain the canonical `{error: {code, message, details?,
  request_id?}}` envelope. WebSocket close codes and Guacamole bootstrap states
  keep their own closed meanings. The QAT surface must map them to safe authored
  phase/check codes rather than copy raw bodies, exception strings, or
  tracebacks.
- Reuse structured ECS logging, safe log ids/fingerprints, and classified user
  messages. Existing lifecycle and access mutations already emit audit events;
  the QAT runner adds correlation, not a parallel audit hierarchy.
- Bound every stored field and process stream. Preserve precise local
  diagnostics without publishing credentials, scenario answers/hashes, private
  addresses, provider payloads, full environment maps, argv/stdin, or adapter
  exceptions.
- Distinguish primary operation failure, evidence/reporting failure, cleanup
  failure, and cancellation. Evidence publication or GitHub reporting must not
  be able to turn a failed or leaked cleanup into a pass.

### Persistence and lifecycle ownership

- `RangeInstance`, request id, Engine state/outbox, and provider-owned state are
  the canonical range truth. The QAT runner owns only its bounded run
  correlation and ephemeral evidence.
- Setup and teardown go through public service boundaries and existing
  idempotency/concurrency rules. Do not mutate Django tables, provisioner state,
  Terraform state, or provider resources directly.
- A durable QAT history, scheduler, lease/lock, or retention store is a separate
  product and operations decision. If later required, it needs explicit owner,
  access control, retention/deletion, schema version, and secret-redaction
  policy rather than an unreviewed JSON blob or new model beside range state.

### Workflow and cloud trust

- A credentialed automated run must be unreachable from pull requests and
  untrusted refs, bind the exact GitHub Environment, use protected-ref/event
  gates, and receive only job-local permissions. Cloud identity uses current
  OIDC/WIF subject constraints; actions remain SHA pinned.
- Product E2E should normally use the product identity and participant session.
  Provider/cloud credentials are justified only for an explicitly separate
  prerequisite, diagnostic, or provider runner, with a dedicated least-
  privilege QAT identity. The existing deploy role is not the default.
- If a workflow publishes an issue/comment/artifact, use the exact permission
  needed and a sanitized, bounded payload. No PAT is implied by this design.

## Extensibility Seam

The obvious next variations are another environment/backend, another
acceptance scenario, or another scenario-specific behavior check. They must
not require another workflow copy, lifecycle implementation, auth model,
scenario schema, or generic result hierarchy.

The parameter seam belongs in a validated, non-secret run profile: target
deployment, expected observed backend/provider, scenario/fixture reference,
actor reference, check/protocol profile, per-phase and whole-run deadlines,
cleanup policy, and evidence destination. Deployment/backend selection remains
a trusted deployment fact rather than a client-controlled provider switch.

The behavior-extension seam is ADR-041's exact installed plugin selection plus
its injected `Runner` and namespaced non-secret bindings. Provider variation is
ADR-039's backend-selected substrate behind the existing lifecycle/access APIs.
An overall operator result may reference or embed the canonical versioned
scenario-verification report, but it must not copy its declaration, status,
runner, discovery, or redaction contracts into a QAT-specific equivalent.

## Gotchas and Anti-Patterns

- Do not put the QAT in `deploy.yml`, add it as a deploy `needs` gate, or assume
  a READY range exists after deployment.
- Do not revive `docs/_deprecated/v1/qa` cloud-resource scripts or their stale
  AWS tags/direct VPC, security-group, and internet-gateway assertions.
- Do not rename or extend the image stack smoke until it depends on live cloud
  state; that would destroy its hermetic contract.
- Do not claim end-to-end success from CMS-internal lifecycle calls, a health
  endpoint, `ResourceStatus.READY`, an open TCP port, WebSocket handshake, or
  accepted Guacamole bootstrap alone.
- Do not call the hidden smoke fixtures a basic scenario, and do not assume
  `basic.yaml` is agent-free. Do not infer SSH/RDP from OS or role when
  `participant_access` is the authored contract.
- Do not add a QAT scenario schema, range DTO, endpoint-binding DTO, provider
  switch, lifecycle service, exception hierarchy, audit table, plugin registry,
  runner protocol, or verification-status enum that shadows an incumbent.
- Do not put scenario answers, adapter code, cloud clients, settings, broad env
  maps, provider objects, persistence handles, or realized scenario models into
  ADR-041 contracts.
- Do not treat an API scope as ownership, a session cookie as sufficient CSRF
  proof, an API bearer token as Channels auth, or a superuser/admin path as the
  participant journey.
- Do not pass secrets with shell `--env` strings, argv, echoed workflow output,
  command interpolation, or unpermissioned temp files. Do not record
  Guacamole URLs, terminal output containing secrets, raw response bodies, or
  exceptions in reports/issues.
- Do not loosen network policy or expose guest endpoints publicly for the test.
  Do not confuse runner-origin reachability with portal-mediated participant
  reachability.
- Do not confuse cleanup request acceptance with cleanup completion, ignore an
  orphaned range after cancellation, or let reporting failure suppress cleanup.
- Do not count skipped, unsupported, blocked, unknown, timed-out, or unselected
  scenario coverage as a pass.
- Do not turn capacity/load metrics or range-escape results into generic QAT
  checks; reference their independently governed evidence when needed.
- Do not add runtime environment keys, GitHub secrets, cloud roles, or durable
  storage speculatively. Each creates cross-repo ownership and validation work.

## Non-Goals and Implementation Boundaries

This preflight does not:

- choose the QAT tool, language, runner location, scheduler, UI, or report
  transport;
- author the design, formal requirements, acceptance criteria, follow-up
  issues, or implementation plan tracked by #983;
- implement, modify, or schedule a smoke/QAT run;
- change deploy, rollback, release, event-readiness, or merge gates;
- define provider substrate conformance, load/capacity, disaster recovery,
  penetration testing, or range-escape policy;
- make scenario-verification adapters or answer material part of core;
- guarantee full browser rendering from a bootstrap-state check unless the
  eventual design expressly chooses and implements a real browser/client proof;
  or
- create a durable QAT service, dashboard, historical database, credential
  model, or generic test framework.

The implementation boundary for the future system is orchestration and safe
evidence across existing public contracts. Changes inside lifecycle, access,
auth, substrate, scenario schema, or verification contracts require their own
contract justification and cannot be smuggled in as test convenience.
