# Nested CTF Participant Readiness Preflight (#1910)

Status: pre-implementation architecture guidance

Date: 2026-09-13

Issue #1910 is an umbrella for independent fixes. This note defines when those
fixes compose into participant readiness; it does not implement them or make the
current `ready` status stronger by documentation alone.

## Decision boundary

`ready` means that a fresh range generation has passed the participant path,
not merely that its cloud resources exist. For a selected
`preconfigured-machine-host`, the same provision operation must complete all of
these gates before the existing terminal `READY` transition:

1. the deterministic range resources and required profile-scoped egress exist;
2. every required generation-bound shared-service capability is installed and
   usable from the allocated range, with no broader guest authority;
3. declared source-backed content has passed its incumbent digest delivery and
   in-guest readback;
4. the participant credential has been installed through the existing secret
   path; and
5. an image-owned, read-only canary has exercised the actual participant
   launcher and proved the declared start state.

The current volatile marker, running-container check, and host RDP listener in
`PreconfiguredMachineHostPlan` are useful boot-liveness prerequisites. They are
not participant-readiness evidence. A marker written by the same startup path
cannot prove Chromium sandbox usability, browser trust, a start-page binding,
clean participant state, or material projection.

Keep `terraform_ops._run_terraform_provision` and the RAES apply/result path as
the lifecycle owners. A failed gate remains a normal failed provision and uses
their existing compensation/destroy path. Do not add a second readiness status,
background workflow, controller, or database truth.

## Canonical incumbents

| Concern | Incumbent and required reuse |
| --- | --- |
| Machine selection and immutable-state policy | `config.GCERangeImageProfile`, strict `GCP_RANGE_IMAGE_KEY_PROFILES_JSON` parsing, `gce_image_profile_fingerprint`, and the exact machine-image reference. Extend this closed backend profile; do not add scenario IDs, URLs, certificates, or commands to a legacy `RangeSpec`. |
| Legacy scenario boundary | `shared.range_cells` validation and `gcp_range_cell_scenario`. It remains the sole legacy role/image/access compatibility adapter; provider planners must not inspect scenario names or content. |
| RAES intent and content | `shared.raes`, the serialized ProvisioningPlan, `DeliveryBinding`, `raes_content_delivery`, and `raes_composition_verification`. Source-backed mission/start material uses their content-addressed delivery and fresh guest readback. Do not create a nested-CTF artifact DTO, copy RAES fields, or treat native CTF content hydration as guest material delivery. |
| Guest execution | `build_guest_execution_context`, pinned host-key `GuestSSHExecutor`, `SetupOrchestrator`, `SetupStep`, and `PreconfiguredMachineHostPlan`. The final canary is another bounded verification at this seam, not generic Linux bootstrap or package-supplied execution. |
| Range lifecycle and persistence | The existing Engine operation generation, `gcp_range_cells` / RAES apply and reconstructive destroy, operation result/inbox, `write_provisioned_state`, and terminal status transition. Evidence is attached to that generation; authored range configuration is not runtime scratch state. |
| Public web egress | `GCERangeImageProfile.allow_public_web_egress`, `GceEgressPolicy`, `gcp_range_cell_firewall.build_firewall_plan`, the denied-network inventory, and range-owned regional Cloud NAT. The #1914 baseline already feeds profile opt-in through both legacy and RAES plan builders. Preserve it as a regression surface. |
| Model access | ADR-056 plus the proposed ADR-059 through ADR-061 model-access boundary: `shared.model_access`, Engine-owned grants/accounting, explicit `GceEgressPolicy.model_broker`, `gcp_range_cell_model_broker`, and the broker-only GCP identity. M06 packaging is present but does not constitute guest enrollment, invocation, revocation, or qualification. |
| Flag truth and scoring | `CTFFlag`, `ctf.services.challenge.verify_flag` / `verify_single_flag`, `ctf.validators.validate_http`, and `ctf.services.submission.submit_flag`. Preserve any-of flag semantics, participant/challenge availability gates, attempt/cooldown policy, scoring, row locking, and the partial unique correct-submission constraint. |
| HTTP validator security | `ctf.validators._http` and `_ssrf`: HTTPS-only, all-address validation, pinned connection with original SNI/Host, no redirects, bounded timeout/body, reserved-header ownership, and fail-closed Boolean results. |
| Errors and observability | `RangeCellContractError`, existing provisioner `RuntimeError` / `CloudError` / `SetupError` mapping, CTF's `CTFValidationError`, `shared.api.errors`, `shared.log_sanitize`, provisioner `log_redact`, and existing request/range/operation correlation. Add bounded reason codes, not another exception hierarchy or raw provider/guest failures. |

## Baseline hazards that remain open

Focused parts of this umbrella already exist and must not be mistaken for the
composed acceptance boundary. The legacy Terraform path runs the fixed
participant canary before its `READY` write. The RAES GCE path can resolve the
same `GCERangeImageProfile`, but currently returns after content/composition
verification and publishes terminal readiness without invoking that canary. A
preconfigured-machine-host profile must therefore either be rejected on that
route or pass the same fixed, image-owned participant contract at the RAES
realization boundary. Composition verification is not an equivalent proof.

HTTP flag configuration also has one current three-way drift: interactive flag
writes validate only URL/timeout, native content bundles separately enforce a
closed/bounded method and header shape, and runtime silently coerces invalid
methods/timeouts while dropping reserved headers. The shared strict
validator/normalizer below must replace that divergence; a value rejected on one
write surface must not become a different request on another.

The submission input and persistence boundary is part of receipt correctness.
`CTFSubmission.submitted_flag` is limited to 500 characters, while the current
participant serializer does not impose that limit and HTTP verification runs
before insert. A receipt that cannot be stored must be rejected before any
external call. The published receipt size must fit the incumbent submission
contract unless a separately reviewed persistence migration changes it. The
normal submission row remains the only receipt audit persistence; do not copy
receipt bytes into a second table, lifecycle evidence, or logs. If the provider
classifies a signed receipt as a replayable credential, its plaintext retention
in that incumbent field requires an explicit data-handling decision before
enablement.

Existing deployed test surfaces cover opposite halves of the proof. The
post-deploy range smoke performs a fresh CMS/Engine allocation and teardown but
only probes base-image TCP connectivity; `uat/range-functional-smoke` exercises
participant terminal/Guacamole behavior against a retained range and never owns
its lifecycle. Neither alone is #1910 fresh participant-readiness evidence, and
their safety/ownership conventions must be preserved when collecting the
composed proof.

## Participant start-state contract

The extensibility seam is the existing machine profile, selected by
`GCERangeImageProfile.bootstrap_capability`. A preconfigured-machine-host
profile declares `participant_readiness_contract`, the closed
`participant-readiness/v1` canary contract, and
`participant_readiness_manifest_sha256`, a lowercase SHA-256 digest
of the image-owned readiness manifest. Both are non-secret backend
configuration, are required only for that capability, and therefore join the
existing profile fingerprint and reconciliation check automatically. Unknown
versions, malformed digests, or partially configured profiles fail at config
load, before a cloud client or range mutation.

The trusted machine-image build owns the fixed canary executable and manifest.
Shifter invokes that fixed entry point over the authenticated management
transport and supplies only the expected contract version/digest. It must not
carry a shell fragment, executable path, URL, certificate body, browser flags,
or scenario payload in the profile. A new image implementation is added by a
new canary contract version or immutable image/profile entry, not a scenario
branch in provisioner code.

The canary runs in the configured participant container as the configured
participant user and exercises the launcher used by the real desktop. It must
prove, rather than infer:

- the browser process starts with a functioning Chromium sandbox;
- the configured trust store accepts the intended lab TLS chain in the browser
  context;
- launcher/default-page state resolves to the manifest-declared start state;
- the participant home has the declared clean baseline before handoff; and
- required mission/start material exists at its declared projection with the
  expected digest or other source-contract evidence.

The check must be repeatable and must not dirty the handed-off home. Use an
image-defined disposable browser profile or a canary mode in the real launcher,
then independently recheck the participant baseline. File existence, process
existence, an HTTP request outside the browser, certificate installation alone,
or echoing the manifest digest is not sufficient.

For a legacy preconfigured image, the selected immutable machine image and
profile manifest own baked start material. For a RAES launch, dynamic material
continues to use `DeliveryBinding` / feature-binding delivery and independent
readback before the final canary; the canary does not replace those proofs or
merge them into a second content schema. Native CTF content hydration populates
the CTF challenge graph and remains a separate concern.

The canary wrapper emits only a closed pass code or bounded failure category.
Suppress browser, TLS, and command output before it reaches
`SetupOrchestrator`, which logs step stdout/stderr. URLs, certificate content,
home contents, receipts, tokens, rendered commands, and provider exception text
must not reach logs, lifecycle error text, operation results, or public errors.

## Egress and shared-service bindings

Public web egress is profile capability, never a property inferred from a start
URL. `allow_public_web_egress=true` admits TCP 80/443 only to the public IPv4
complement already produced from the canonical denied-network inventory. A
profile without the opt-in gets no web rule. Effective `none`/deny-all posture
continues to win, and a firewall allow without the range's regional NAT is not
readiness. Apply, same-name reconciliation, failed-apply cleanup, and destroy
must keep the rule lifecycle symmetric.

Do not grant direct shared-model invoke IAM to a preconfigured host-pool service
account. Those pool members are selected modulo a bounded pool and are not
exclusive range identities; two live ranges can share one member. Adding and
removing a service-level IAM binding for one range would authorize the other and
teardown could revoke a still-live peer. It also conflicts with
`gcp_range_cell_model_broker`, which correctly rejects broker clients carrying
an attached service account or another egress bypass.

The current repository direction satisfies the issue's least-privilege intent
through a generation-bound broker grant: scenario/event admission selects a
logical model profile, Engine owns the grant and accounting, the provisioner
installs only the opaque range capability, the guest reaches only the exact
private broker VIP, and only the broker workload may impersonate an exact
invocation-only target. Destroy, replacement, expiry, failed provisioning, and
reconciliation revoke the original grant epoch without editing shared guest
IAM. A narrow positive call from the fresh guest plus negative effective-IAM
and cross-range probes is the readiness evidence.

That full lifecycle is not present on this baseline: the repository explicitly
tracks guest enrollment/revocation and selected-scenario qualification in the
model-access delivery ledger. The model-binding acceptance criterion therefore
remains open until that path, or an expressly adopted replacement architecture,
lands and is qualified. M06's disabled package and firewall vocabulary must not
be relabeled as a working participant service. A direct Cloud Run or Vertex
grant to the pooled host identity is not an acceptable stopgap.

## Signed receipt validation

The [#1906 binding preflight](ctf-signed-receipt-binding-preflight-1906.md)
and ADR-063 specialize this section: they distinguish command generation from
materialization and assignment identity, define signer/key enrollment, and require
transactional freshness and durable one-shot replay evidence. The paragraphs
below describe the existing transport and scoring incumbents, not sufficient
generation/replay enforcement by themselves.

A signed receipt remains submitted through the normal CTF flag path. Shifter
does not parse its signature, duplicate proof-service cryptography, create a new
flag type, or award points from a proof route. The external verifier owns
signature and claim verification (an installed asymmetric adapter may instead
verify using registered public keys); `submit_flag` remains the sole score and
submission transaction.

The existing HTTP validator wire contract sends only the submitted flag and
challenge UUID. That is insufficient when the signed receipt is bound to a
participant and range generation. The narrow extensibility seam is a closed,
versioned `validator_config.protocol` selector, defaulting to the existing wire
contract, plus a keyword-only `server_context` passed down from `submit_flag`.
A receipt-capable protocol may add only server-resolved participant and current
range-generation identities from that context to the outbound request. Those
values come from the loaded `CTFParticipant` and the existing CTF-to-CMS
bridge/service boundary; they are never trusted from receipt claims, organizer
headers, query parameters, or scenario content. Its exact wire fields must be
the published proof-provider contract rather than names guessed in Shifter.

Keep one strict HTTP-config validator/normalizer shared by interactive flag
writes and `ctf.content_bundle` hydration. Preserve `url`, closed GET/POST,
bounded integer timeout, bounded string headers, and transport-reserved header
rejection. Unknown protocol versions or members fail at write/hydration time;
runtime still revalidates and fails closed for old or damaged rows. Do not add
arbitrary request templates, JSONPath/verdict expressions, callback code, or a
parallel receipt schema.

GET remains a compatibility option only for the default legacy protocol. A
receipt-bearing protocol must require POST so the signed receipt never enters a
query string, access log, proxy cache key, or referrer surface. Do not put an
authentication secret in the validator URL. If the proof service needs service
authentication, use the separately authenticated service seam rather than an
organizer-authored URL credential or participant-visible lab CA.

The proof callback is pure verification. A consuming or one-shot remote redeem
performed before Shifter's database transaction would create an unrecoverable
split-brain when the callback succeeds and the submission transaction fails.
For a correctly subject-bound receipt, the existing participant row lock,
already-solved check, and database uniqueness constraint are the scoring
incumbents. They do not fence a verdict against concurrent lifecycle changes
or preserve one-shot consumption after solve soft deletion. #1906 requires
revalidation under the lifecycle/assignment fence and durable receipt consumption
in that same transaction. Cross-participant/range rejection additionally requires
the verifier to compare the server-supplied binding.

Accept a callback only for HTTP 200 and the literal JSON Boolean `true` in the
canonical verdict member. Do not use Python truthiness: strings such as
`"false"`, numbers, null, missing members, extra/ambiguous verdicts, malformed
JSON, transport errors, or an unbound/expired receipt fail closed. The
participant continues to receive the incumbent `correct`/incorrect result or
canonical CTF service-error envelope; cryptographic claims, callback bodies,
DNS answers, URLs, headers, and internal rejection reasons are not disclosed.
The legacy HTTP response remains exactly `{"valid": true}` for success. Any
receipt-specific verified identity/deadline evidence requires a separately
versioned closed provider response, not extra fields silently accepted by the
legacy parser.

The current SSRF and TLS boundary remains intact. Never allow a private range
CIDR merely because a proof page is participant-visible, and never install the
lab browser CA into the platform-wide validator trust store. If the proof
provider is not reachable through the existing safe HTTPS callback boundary,
it needs a separately authenticated service seam; weakening `_ssrf` is not
receipt integration.

## Evidence and operator handoff

A release claim requires one fresh allocation through the ordinary CTF/CMS /
Engine/provisioner path. A retained range, warm handoff, manually patched
firewall/IAM policy, seeded database solve, direct canary invocation, or unit
mock is not end-to-end evidence. The proof run must include cleanup and a second
fresh allocation so retained state cannot mask missing reconciliation.

Operator evidence should be bounded and bind:

- request/range/operation generation, selected profile key and fingerprint,
  exact machine-image resource, canary contract version and manifest digest;
- successful boot-liveness, participant credential, content-readback, and final
  participant-canary reason codes;
- presence of the exact opt-in web rule and matching regional NAT, plus absence
  on a non-opt-in profile;
- model grant/profile/epoch, exact broker destination and broker-only invocation
  identity, with no guest GSA or provider credential; and
- post-destroy absence of range-owned rules/capabilities and denial of stale,
  foreign-range, invalid, and replayed credentials/receipts.

Evidence contains references, digests, fixed categories, and timestamps only.
It does not contain URLs with secrets, CA material, browser profiles, mission
content, model prompts/responses, signed receipt bytes, guest output, IAM policy
dumps, or provider response bodies.

## Gotchas and anti-patterns

- Do not equate infrastructure-created, marker-ready, RDP-listening,
  content-delivered, model-enrolled, CTF-hydrated, and participant-ready states.
- Do not move browser defaults, CA certificates, mission URLs, scenario names,
  or shell scripts into provisioner conditionals or `RangeSpec`.
- Do not let the canary repair the image. A missing sandbox, trust anchor,
  launcher setting, clean-home baseline, or material projection fails the
  immutable artifact; readiness is not a configuration-management pass.
- Do not print raw canary output through `SetupOrchestrator` or let
  `_safe_failure_message` persist an unbounded guest/provider exception.
- Do not derive public egress from a URL, add `0.0.0.0/0`, bypass the denied
  inventory, or forget regional NAT and the no-opt-in negative case.
- Do not treat a modulo-selected host-pool account as an exclusive lease or
  range security principal, and do not attach provider/model identity to a
  root-compromisable host.
- Do not duplicate `shared.model_access`, RAES delivery, CTF content, HTTP
  validator, submission, scoring, error, or reconciliation contracts.
- Do not make external receipt verification consume state before the CTF
  transaction, trust a participant/range claim from the receipt without the
  server-side expected binding, or broaden SSRF/TLS policy for convenience.
- Do not close the umbrella from focused unit tests. Use `Refs` until every
  gate and its fresh-allocation negative/cleanup evidence are complete.

## Non-goals

- No machine-image bake implementation, browser configuration, CA issuance, or
  scenario-specific mission content in Shifter.
- No new public participant endpoint, access channel, range status, workflow,
  readiness database, or general guest-command/plugin framework.
- No replacement for RAES contracts, source delivery, CTF content hydration,
  the model-access program, or the existing CTF submission/scoring transaction.
- No broad internet, Google API, model-provider, storage, Secret Manager,
  Compute, IAM, Kubernetes, or control-plane permission for a participant host.
- No AWS/GDC parity claim, retained-range certification, or model-provider
  qualification inherited from a different scenario or backend.

This note specializes ADR-008-R7/R9, ADR-030-R5, ADR-032-R3/R6/R9,
ADR-039, ADR-043-R5/R7, and ADR-056. It introduces no exception and does not
adopt the still-proposed ADR-059 through ADR-061 runtime claims.
