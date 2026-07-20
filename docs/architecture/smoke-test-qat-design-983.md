# Smoke-Test / QAT System Design (#983)

Status: design

Date: 2026-07-18

Issue: GitHub [#983](https://github.com/Brad-Edwards/shifter/issues/983),
"Design a smoke-test / QA (QAT) system for common range infra and a basic
scenario".

Binding guardrails: [smoke-test-qat-design-preflight-983.md](smoke-test-qat-design-preflight-983.md).

This document is the design deliverable for #983. It defines a smoke-test /
QA-test (QAT) protocol, its proofs and evidence contracts, the fixtures it
needs, the requirements it must satisfy, and the follow-up issues required to
build it. It deliberately does not choose tooling, language, runner location,
or a scheduler; those belong to the implementing issues.

## 1. Purpose and scope

Shifter has no repeatable, automated proof that a participant can actually use
a range. The QAT system closes that gap: an on-demand protocol that validates
two things against a positively selected, known-up deployment.

1. The **common range infrastructure**, the shared range baseline every range
   rides on, can carry a real range through its full lifecycle.
2. A **basic scenario's participant journey**, the path a real user takes to
   reach a range host, works end to end: reach the product, open an
   interactive terminal, and open a Guacamole session.

The system is operator-invoked (pre-event readiness, post-change confidence),
runs against an explicitly named environment, and reports a verdict. It is not
wired into deployment and does not gate deploys.

### In scope

- The QAT protocol: phases, ordering, and the evidence level required for each
  claim.
- The fixtures the protocol needs (a common-range check target and an
  agent-free acceptance scenario).
- The ephemeral test-participant lifecycle, including cleanup guarantees.
- Requirements, acceptance criteria, and a follow-up issue breakdown to build
  the system.

### Out of scope

- Any implementation, and any choice of tool, language, runner host, scheduler,
  UI, or report transport.
- Scenario-content verification (flags, answers, adversary behavior). That
  remains the ADR-041 plugin seam and is not part of the QAT happy path.
- Changing deploy, release, rollback, or merge gating.
- Removing or refactoring any Palo Alto (PANW) specific code. The design notes
  where vendor specifics belong (Section 5.3) but changes none; that is
  separate planning.
- A durable QAT history, dashboard, scheduler, or credential model.

## 2. Why this is needed, and how it differs from existing checks

Four checks exist today. None proves the live participant journey, and the one
that does exist is manual.

| Check | Proves | Live range | Terminal + Guacamole |
| --- | --- | --- | --- |
| Built-image stack smoke (`scripts/stack-smoke/`, #922) | the built portal image boots under its real entrypoint with local doubles; login, health, WS handshake, page render | no | no, explicitly excluded |
| Deploy-health verify (`scripts/portal_deploy/portal_deploy.py verify-post-deploy`) | the deployed portal service is healthy | no | no |
| Post-deploy range smoke (`scripts/smoke-test.sh`, `cms.post_deploy_smoke`, #218) | the platform can request a range, observe `READY`, resolve an SSH/RDP endpoint, and reach a guest port; then tear down | yes | no, TCP reachability only |
| `aws-tenant-standup` runbook, Phase 5 to 7 | health, base-range smoke, and a full POLARIS walkthrough including terminal and interactive use | yes | yes, by hand |

The gap: the only automated live-range check (#218) stops at a TCP connection
to ports 22 and 3389. Whether a participant can open a working terminal or a
Guacamole session is verified only by the manual runbook. The June 2026
incidents that reached users (broken terminal source maps, terminal SSH to
ephemeral hosts, Guacamole bootstrap) were exactly this class of failure; a TCP
probe does not catch them.

The QAT system systematizes the manual `aws-tenant-standup` Phase 5 to 7
sequence into a repeatable protocol that reuses the existing platform services
rather than inventing a parallel path.

### Why it is not a deploy gate

The predecessor, #923, tried to add functional verification as a post-deploy
gate and was closed as not-planned. The range-dependent checks need a live,
`READY` range with instances, and a deploy does not guarantee one exists;
ranges are ephemeral and user or event driven. Gating every deploy on "a
terminal and Guacamole session must succeed against a live range" ties deploy
success to a precondition the deploy does not control. QAT therefore runs on
demand against known-up infrastructure, observes, and reports; it never blocks
a deploy.

## 3. Proof taxonomy

The QAT run presents its evidence together, but the underlying proofs are
distinct and must never collapse into one undifferentiated "smoke passed"
signal.

- **Preconditions (assumed already green, not QAT phases).** The built-image
  stack smoke proves the image boots. Deploy-health verify proves the service
  is up. QAT assumes both and targets an environment the operator asserts is
  deployed and healthy. QAT does not re-run or duplicate them.
- **QAT phase 1: common range infrastructure.** The shared baseline can carry a
  range through its lifecycle (Section 6.2).
- **QAT phase 2: basic-scenario participant journey.** A participant reaches a
  range host through the product boundary (Section 6.3).
- **Separately governed readiness evidence (referenced, not absorbed).**
  Participant-origin isolation is proven by `range_escape` validation
  (`docs/ops/range-escape-validation.md`); capacity is proven by the event-load
  harness (`uat/event-load-harness`). A successful QAT happy path is not an
  isolation proof, and isolation or load evidence is not a QAT pass. When an
  operator wants a full readiness picture, the QAT verdict references these; it
  does not reimplement them.

## 4. Design principles

These follow directly from the preflight guardrails and the existing service
contracts. They constrain every phase below.

1. **Reuse the range lifecycle.** Create, query, and destroy ranges through the
   CMS and Engine services. Never write `RangeInstance` or Engine state
   directly, drive Terraform or a provider SDK as the orchestrator, or create a
   QAT-private lifecycle model.
2. **Exercise the product boundary for product claims.** Usability claims go
   through Mission Control's HTTP API, WebSocket, and Guacamole paths, with the
   real actor, scopes, session, and ownership checks. An in-process management
   command may set up or clean up, but it cannot establish that the external
   journey works.
3. **Prove evidence at the level claimed.** `READY`, an open TCP port, a
   WebSocket upgrade, or a Guacamole `202` are not, on their own, end-to-end
   proof. Section 6 states the required evidence for each claim.
4. **Fail closed.** A required check that is missing, skipped, `blocked`,
   `error`, timed out, or unknown is not a pass.
5. **Cleanup is a postcondition, not best effort.** Teardown uses the canonical
   ownership path and observes a terminal destroyed or absent outcome. A
   submitted destroy is not completed cleanup. A cleanup failure makes the run
   non-successful and never overwrites the primary failure.
6. **Evidence is safe and bounded.** Reports carry non-secret identifiers and
   provenance only (Section 7).
7. **Provider neutrality via ADR-039; scenario behavior via ADR-041.** The
   common-range proof is stated in provider-neutral postconditions.
   Scenario-specific behavior, if ever added, is an ADR-041 plugin, not a QAT
   extension.

## 5. Fixtures

### 5.1 Common-range check target

Phase 1 provisions a minimal range to exercise the shared baseline
(`platform/terraform/modules/range/vpc/` and the per-range ephemeral module).
It needs a schema-valid scenario with at least one reachable host and a
declared participant channel. The agent-free QAT scenario in Section 5.2 serves
both phases; a single provision carries both proofs.

### 5.2 The agent-free QAT scenario

The catalog `basic` scenario (`cms/scenarios/templates/basic.yaml`) is
`enabled` and declares the participant journey, but its `Workstation` victim
uses `os_type: from_agent`, so provisioning it requires an uploaded agent
asset. The hidden `smoke_linux` and `smoke_windows` templates are agent-free
but declare no `participant_access`, so they prove infrastructure only and are
not user-facing.

The design adds a **new agent-free QAT scenario** rather than depending on the
agent asset. The key observation: `basic`'s `participant_access` targets the
**Attacker** (`os_type: kali`), which is agent-free; the agent requirement is
only on the victim. Dropping the `from_agent` victim yields a schema-valid
fixture that proves the same participant journey without the agent.

Intended shape (illustrative, using the existing scenario schema; no schema
fork):

```yaml
id: qat_basic
name: QAT Basic (agent-free)
description: >-
  On-demand QAT fixture. A Kali attacker with a declared SSH/RDP participant
  channel and no agent dependency, used to prove the common range baseline and
  the basic participant journey. Not a user catalog scenario.
enabled: false
ngfw: false

instances:
  - name: Attacker
    role: attacker
    os_type: kali
    xdr_agent: false

participant_access:
  - target: Attacker
    channel: ssh
  - target: Attacker
    channel: rdp

subnets:
  - name: core
    instances: [Attacker]
```

The implementing issue finalizes visibility (a QAT-selectable flag versus the
existing `enabled` field) and whether a second, non-agent victim host is worth
adding for topology realism. The fixture must remain a normal, schema-valid
scenario loaded through `cms.scenarios.loader`; it must not introduce a QAT
YAML dialect.

### 5.3 Vendor specifics belong in a future plugin (noted, not acted on)

The reason the QAT fixture is agent-free is architectural, not incidental. The
agent (XDR) is a vendor-specific concern. Keeping it out of the QAT core proof
follows the same direction as ADR-041: vendor and scenario specifics belong in
an explicitly selected, out-of-tree plugin, not in core paths. This design
records that direction and honors it for the new fixture. It removes and
refactors no existing PANW-specific code; that is separate planning and out of
scope for #983.

## 6. The QAT protocol

A run targets one environment, provisions one range from the agent-free QAT
scenario owned by an ephemeral participant, proves the two phases, and tears
everything down. Every phase has explicit, bounded deadlines.

### 6.1 Ephemeral test-participant lifecycle

Product claims require a real participant identity, not a superuser shortcut.
The run creates one, uses it, and removes it. Nothing is left standing.

- **Create.** A dedicated, least-privilege QAT setup identity provisions an
  ephemeral participant. Creating and removing the participant is a
  prerequisite step and uses a purpose-scoped identity, not the broad deploy
  role.
- **Authenticate (the Cognito/MFA wrinkle).** Interactive Cognito login with
  MFA cannot be driven headlessly. The design resolves this by giving the
  ephemeral participant an MFA-free identity and obtaining a session through the
  existing authentication boundary, so the resulting session is a genuine
  product session, not a bypass. Concretely, the implementing issue selects one
  of:
  1. programmatic authentication of the MFA-free ephemeral user through the
     existing OIDC and session-establishment path, yielding the normal session
     cookie the WebSocket and Guacamole paths require; or
  2. an equivalent existing session-establishment seam that the product already
     trusts.

  A bearer API token is acceptable for HTTP API calls, but it does not
  authenticate a Channels WebSocket; the WebSocket and Guacamole steps use the
  real session boundary. No QAT-only bypass endpoint, CSRF exemption, or
  superuser path is permitted.
- **Own the range.** The range is provisioned for this participant, so
  ownership, membership, and readiness checks in the terminal and Guacamole
  brokers apply unchanged.
- **Remove.** At teardown the participant and its credential material are
  deleted, and the removal is observed (Section 6.4). Any temporary session or
  credential file is short lived, gitignored, and mode `0600`.

### 6.2 Phase 1: common range infrastructure

Goal: prove the shared baseline carries a range through its lifecycle, in
provider-neutral terms (ADR-039 postconditions).

Steps and evidence:

1. **Provision.** Call `cms.services.create_range(participant, "qat_basic", {},
   ngfw_enabled=False)` and capture the `request_id`. Evidence: an accepted
   request with a correlation id, not a success claim.
2. **Reach `READY`.** Poll `cms.services.get_range_status_by_id` /
   `get_range_by_request_id` with a bounded deadline until the range reports
   `READY`. Evidence: `ResourceStatus.READY` observed within the deadline; a
   timeout is a failure, not a skip.
3. **Validated realization and declared bindings.** Confirm the realized range
   exposes the declared access binding for the `Attacker` host (the authored
   `participant_access`, not an inferred host, port, or protocol). Evidence: the
   platform resolves the logical `{target, channel}` to a realized closed
   binding.
4. **Brokered access is resolvable.** Confirm `engine.services._terminal`
   resolves connection info for the owner without exposing the raw binding.
   Evidence: the broker returns a usable, owner-scoped resolution; the URL or
   secret itself never becomes report evidence.

Direct cloud-resource inspection (security groups, subnets, firewall rules) may
be attached as provider-specific diagnostic evidence, but it is not the common
contract; the common contract is the provider-neutral postcondition set above.

### 6.3 Phase 2: basic-scenario participant journey

Goal: prove a participant reaches a range host through the product boundary.
Each claim states its evidence level explicitly.

1. **Reach the product.** Authenticated calls to Mission Control's versioned
   HTTP API list the participant's range and its instances, passing the real
   scope, active-actor, ownership, and readiness checks. Evidence: the API
   returns the owned, `READY` range through the normal permission path. An
   unauthenticated or over-scoped call must be refused.
2. **Interactive terminal use.** Open the terminal WebSocket for the `Attacker`
   instance through the product path (`AllowedHostsOriginValidator`,
   `AuthMiddlewareStack`, the `SSHConsumer` ownership and capacity checks), then
   perform a **nonce-correlated command and output exchange**: send
   `{"type": "input", "data": "echo <nonce>\n"}` and require a
   `{"type": "output", "data": "...<nonce>..."}` response within a bounded
   deadline. Evidence levels, from weakest to sufficient:
   - WebSocket upgrade accepted (insufficient alone);
   - a terminal session established;
   - the nonce round-trips through the normal terminal path (sufficient).

   The command is harmless, idempotent, and nonce-correlated. Terminal output
   is never published verbatim in the report; only the pass or fail of the
   nonce match, and bounded metadata, are recorded.
3. **Guacamole session.** Request a Guacamole bootstrap for the instance
   through `mission_control.api.guacamole`, then follow it to completion. The
   four distinct claims, which the design must not conflate:
   - request accepted, HTTP `202`, `GuacamoleBootstrapRequest.Status.PENDING`
     (queue admission only);
   - `Status.SUCCEEDED` (the one-time URL is ready to deliver);
   - `delivered_at` set (the owner-scoped one-time URL was consumed; the status
     endpoint then returns `410` on re-poll);
   - a rendered interactive guacd client session (a browser or client-level
     claim).

   The design's required evidence level for "Guacamole works" is a **bounded
   client-level connection signal**: the one-time URL is consumed and a guacd
   tunnel to the target reaches a connection-level success (the Guacamole
   protocol handshake completes and the remote session opens) within a bounded
   deadline. Bootstrap `SUCCEEDED` and one-time URL delivery (`delivered_at`)
   are necessary intermediate evidence but are **not sufficient** on their own;
   they prove only that the server minted a credential, which is the exact gap
   this QAT exists to close relative to the TCP-only post-deploy smoke.
   Requiring only delivery would leave the guacd tunnel, the downstream
   RDP/SSH connection, and the interactive session unexercised, contradicting
   the participant-journey claim. Full pixel-level rendering is not required; a
   bounded protocol-level connection success is. The implementing issue chooses
   how to obtain that signal (a headless guacd protocol client, or a headless
   browser driving the Guacamole client). The bootstrap URL and token are
   credentials and never appear in the report.

### 6.4 Teardown and result model

- **Observed teardown.** Call `cms.services.destroy_range_by_request_id(
   request_id)` and then poll until the range reaches a terminal destroyed or
   absent state within a bounded deadline. A submitted destroy is not completed
   cleanup. Then remove the ephemeral participant and its credential and confirm
   removal.
- **Failure separation.** The run distinguishes primary-operation failure,
  evidence or reporting failure, cleanup failure, and cancellation. Evidence
  publication or issue filing must never turn a failed or leaked cleanup into a
  pass. A cleanup failure is preserved alongside, and never overwrites, the
  primary cause.
- **Fail closed.** The overall verdict is a pass only if every required check
  passed and cleanup was observed complete. Keep `ResourceStatus`, HTTP and
  WebSocket outcomes, Guacamole bootstrap status, and the overall QAT conclusion
  as distinct concepts; do not alias one enum onto another.

## 7. Evidence envelope

Evidence is operator-facing and ephemeral unless a separate retention
requirement is later established. A run envelope correlates existing results; it
does not become a new source of range truth or duplicate ADR-041 results.

- **Include:** run id, request id, environment name, observed backend or
  provider, scenario and fixture identity and version, artifact revision, check
  code, per-check duration, phase and overall verdict, and the cleanup
  conclusion.
- **Exclude:** API tokens, passwords, session or CSRF cookies, SSH keys,
  Guacamole tokens or URLs, cloud credentials, secret references, scenario
  answer material, internal or private addresses, raw provider payloads, full
  environment maps, argv or stdin, unbounded process or terminal output, and raw
  exceptions or tracebacks.

Reports map HTTP error envelopes, WebSocket close codes, and Guacamole
bootstrap states to safe, authored phase and check codes rather than copying raw
bodies. Structured ECS logging (`config.logging.ECSFormatter`) and
`shared.log_sanitize` apply. Existing lifecycle and access mutations already
emit audit events; the runner adds correlation, not a parallel audit hierarchy.

## 8. Extensibility seam

The obvious next variations are another environment or backend, another
acceptance scenario, and eventually a scenario-behavior check. None may require
a workflow copy, a lifecycle fork, a new auth model, a scenario-schema fork, or
a generic result hierarchy.

- **Run profile (the parameter seam).** A validated, non-secret run profile
  carries: target environment or URL, expected observed backend or provider,
  scenario and fixture reference, actor reference, selected check or protocol
  profile, per-phase and whole-run deadlines, cleanup policy, and evidence
  destination. Deployment and backend selection is a trusted deployment fact,
  not a client-controlled provider switch. Secrets are resolved just in time
  through their existing owning boundary, never carried in the profile.
- **Scenario behavior.** New behavior checks are an ADR-041 installed plugin
  plus its injected runner, selected by exact version, with namespaced
  non-secret bindings. An overall QAT result may reference or embed the
  canonical scenario-verification report; it must not copy that report's
  declaration, status, discovery, or redaction contracts.
- **Provider.** New providers ride ADR-039's backend-selected substrate behind
  the existing lifecycle and access APIs.

## 9. Security and cross-cutting design

The design was considered against every cross-cutting layer the protocol passes
through.

- **Authentication and authorization.** HTTP passes `ApiTokenAuthentication` or
  the Django session stack, exact `mission_control:*` scopes, active-actor and
  object-ownership checks, and range membership and readiness. WebSockets pass
  origin validation, the auth middleware stack, and consumer ownership and
  capacity checks. Guacamole passes serializer validation, `guacamole:read`,
  instance membership and readiness, one-time owner binding, and expiry. A token
  scope is not ownership, and a bearer token is not a WebSocket session.
- **Secrets and process or OS exposure.** No secret enters argv, a command
  string, a broad environment dump, workflow annotations, logs, the report, or
  a filed issue. The runner uses fixed argv, no `shell=True`, bounded streams,
  explicit deadlines, and cancellation. Temporary credential or session
  material is short lived, gitignored, and mode `0600`.
- **Schema and validation.** The target scenario passes YAML `safe_load`, the
  `cms.scenarios.schema` models, registry and hydration validation, and its
  participant-access declarations. Lifecycle and Guacamole payloads pass the
  existing DRF serializers; the runner may validate its own input profile but
  does not fork server DTOs.
- **Network and host boundaries.** The runner opens no security group,
  firewall, `NetworkPolicy`, public IP, or ingress to make a runner-origin
  probe pass. Terminal traffic stays browser to portal WebSocket to declared
  member; Guacamole stays browser to portal bootstrap to guacd to declared
  member. Runner-origin reachability is never confused with portal-mediated
  participant reachability, and a successful happy path is never treated as an
  isolation proof.
- **Persistence and lifecycle ownership.** `RangeInstance`, request id, Engine
  state and outbox, and provider state remain the canonical range truth. The
  runner owns only its bounded run correlation and ephemeral evidence, and
  mutates nothing directly.
- **Workflow and cloud trust (for any future automation).** A credentialed
  automated run must be unreachable from pull requests and untrusted refs, bind
  the exact GitHub Environment, use protected-ref and event gates, receive
  job-local permissions only, and use current OIDC or WIF subject constraints
  with SHA-pinned actions. The product journey uses the participant session; a
  cloud identity is justified only for the separate setup or teardown
  prerequisite, with a dedicated least-privilege QAT identity, never the deploy
  role by default.

### Maintainability: canonical incumbents reused

| Concern | Incumbent reused |
| --- | --- |
| Range lifecycle | `cms.services.create_range`, `get_range_status_by_id`, `get_range_by_request_id`, `destroy_range_by_request_id`; Engine dispatch and state |
| Scenario parsing | `cms.scenarios.loader`, `schema`, `hydrator`, `registry` |
| External API | `mission_control.api` DRF serializers, permissions, throttles, `shared.api.errors` |
| Terminal access | `engine.services._terminal`, `mission_control.consumers.SSHConsumer`, `config.asgi` |
| Guacamole access | `mission_control.api.guacamole`, `mission_control.guacamole_bootstrap`, `mission_control.guacamole` |
| Auth | `shared.api_tokens`, `mission_control.api.permissions`, Django session and CSRF |
| Logging and audit | `config.logging.ECSFormatter`, `shared.log_sanitize`, existing lifecycle and access audit events |
| Runtime config | `config/_env_manifest.py` and the generated manifest, only if a deployed key is ever genuinely required |

No QAT-private lifecycle service, range or endpoint DTO, exception hierarchy,
audit table, plugin registry, runner protocol, or verification-status enum is
introduced.

## 10. Requirements

These are the requirements the built QAT system must satisfy. They are stated
here as the design's requirement set (per the issue's "Done when"); whether they
become formal Ground Control requirement UIDs is a follow-up decision
(Section 12, F6).

- **QAT-R1 On-demand posture.** The system runs on demand against an explicitly
  named, positively selected environment. It is not present in `deploy.yml` and
  is not a deploy dependency.
- **QAT-R2 Distinct proofs.** The system keeps deployment health, common-range
  infrastructure, participant journey, and any scenario behavior as distinct
  proofs, and never emits a single undifferentiated pass signal.
- **QAT-R3 Common-range proof.** The system proves the shared baseline carries a
  range to `READY` with declared, resolvable brokered access, in provider-neutral
  ADR-039 postconditions, using CMS and Engine services only.
- **QAT-R4 Participant-journey proof.** The system proves the product boundary:
  authenticated API access, an interactive terminal with a nonce-correlated
  command and output exchange, and a Guacamole session established through a
  bounded client-level connection to the target (one-time URL delivery alone is
  not sufficient).
- **QAT-R5 Agent-free fixture.** The system uses a schema-valid, agent-free QAT
  scenario and introduces no scenario-schema fork.
- **QAT-R6 Ephemeral participant.** The system creates a real, ephemeral
  participant through a least-privilege identity and authenticates it through the
  existing product boundary, with no bypass endpoint or superuser path.
- **QAT-R7 Observed cleanup.** The system tears down the range, participant, and
  credential, and observes terminal removal. Incomplete cleanup fails the run and
  never overwrites the primary failure.
- **QAT-R8 Fail closed.** Missing, skipped, blocked, errored, timed-out, or
  unknown required checks are not passes.
- **QAT-R9 Safe evidence.** The report carries only the non-secret identifiers
  and provenance in Section 7 and excludes all listed secret-bearing material.
- **QAT-R10 Extensibility seam.** A new environment, scenario, or provider is
  added through the run profile, ADR-041, or ADR-039 without editing the core
  workflow, lifecycle, auth, or result model.

## 11. Acceptance criteria for the built system

- A QAT run against a healthy environment with a working range path reports an
  overall pass, with a per-phase breakdown for common-range and participant
  journey.
- A run where the terminal nonce exchange fails, or the Guacamole session does
  not reach a client-level connection to the target (bootstrap delivery without
  a connected session included), reports a fail with the specific phase and
  check, and does not report an overall pass.
- A run where teardown does not reach an observed destroyed or absent state, or
  where the ephemeral participant is not confirmed removed, reports a fail even
  if phases 1 and 2 passed.
- No report, log, or filed issue contains a secret, a Guacamole URL or token, a
  scenario answer, a private address, or unbounded terminal output.
- The run targets an environment only when positively selected; it cannot be
  triggered as part of a deploy.
- The QAT scenario provisions with no agent asset.

## 12. Follow-up issues

The build breaks into the following issues. Each is self-contained and
references this design.

- **F1: Agent-free QAT scenario fixture.** Add the `qat_basic` scenario template
  (Section 5.2) through `cms.scenarios.loader`, with tests that it loads,
  validates, and declares participant access. Decide visibility and whether to
  add a non-agent victim host. Satisfies QAT-R5.
- **F2: Ephemeral participant lifecycle.** Implement create, authenticate, and
  observed-remove for an ephemeral participant using a least-privilege identity,
  resolving the Cognito/MFA authentication path (Section 6.1). Satisfies QAT-R6
  and the participant half of QAT-R7.
- **F3: Common-range QAT phase.** Implement phase 1 (Section 6.2) over CMS and
  Engine services with bounded polling and provider-neutral postconditions.
  Satisfies QAT-R3.
- **F4: Participant-journey QAT phase.** Implement phase 2 (Section 6.3):
  authenticated API, terminal nonce exchange, and Guacamole through a bounded
  client-level connection signal (one-time URL delivery is necessary but not
  sufficient), with the evidence levels named. Satisfies QAT-R4.
- **F5: Run orchestration, run profile, evidence envelope, and result model.**
  Implement the run profile seam (Section 8), the safe evidence envelope
  (Section 7), observed teardown and failure separation (Section 6.4), and the
  fail-closed verdict. Satisfies QAT-R1, QAT-R2, QAT-R7, QAT-R8, QAT-R9,
  QAT-R10.
- **F6: Ground Control requirements (optional).** If the requirement set in
  Section 10 should be tracked formally, create the corresponding Ground Control
  requirement UIDs and link F1 to F5 as their implementing artifacts.
- **F7: Operator entry point and runbook (optional, later).** A trusted manual
  entry point (a protected, environment-bound workflow or a documented operator
  command) plus a runbook that supersedes the manual `aws-tenant-standup`
  Phase 5 to 7 steps. Any credentialed automation follows the workflow-trust
  constraints in Section 9.

Sequencing: F1 unblocks F3 and F4; F2 is needed by F4; F5 composes F2 to F4.
F1 to F5 deliver the minimum system for #983's scope. F6 and F7 are optional
follow-ups.

## 13. Open questions and risks

- **Cognito/MFA authentication.** The ephemeral-participant authentication path
  (Section 6.1) is the highest-risk unknown. F2 must confirm a real
  session can be established for an MFA-free ephemeral user through the existing
  boundary without a bypass. If it cannot, the participant-journey phase needs a
  different, still-real session mechanism before F4 can proceed.
- **Guacamole client-level proof (implementation cost).** The design requires a
  bounded client-level connection signal through guacd (Section 6.3), not merely
  one-time URL delivery, so F4 must drive a headless guacd protocol client or a
  headless browser. This is the highest-cost check to build; the cheaper
  alternative (accepting server-side delivery only) is deliberately rejected
  because it preserves the exact gap the QAT exists to close. Full pixel-level
  rendering remains out of scope; a bounded connection-level success is
  sufficient.
- **Runner network vantage.** The runner's network position is part of the
  evidence. The design forbids loosening any network policy for runner-origin
  probes; F4 must run from a vantage that reaches the product boundary the way a
  participant does, without new ingress.
- **Environment selection safety.** F5 must ensure an environment is targeted
  only by positive selection, so a QAT run can never be pointed at production or
  a live event tenant by default.
