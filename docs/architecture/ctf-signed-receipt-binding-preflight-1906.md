# Signed-receipt participant/range binding (#1906)

Status: source implementation and design policy, 2026-09-13. ADR-062 records
these decisions and the #1906 implementation supplies the Shifter contracts,
provider-facing seam, lifecycle fences, and automated evidence. Fresh deployed
two-generation qualification remains owned by umbrella #1910.

## Reconciliation and ownership

Repository requirement snapshots establish lineage, not new scope or live
Ground Control status: CTF-118/#509 owns programmable/HTTP validation;
CTF-104/105/106 own static/regex/case behavior; CTF-014/#627 and
CTF-1401/#638 constrain extensions to installed Django apps. CTF-1401 is marked
DRAFT locally despite existing extension code. Do not activate it, attach it to
#1906, or manufacture requirement links for this requirement-free run.
CTF-1305/#539 preserves authorized submission history. CTF-1405/#1907 owns
digest-pinned event content; #1971 owns its refresh. Neither a hydration receipt
nor a content digest proves a participant's range assignment.

This specializes #1910's receipt guidance, #1188's DNS-pinning boundary,
#1183's bounded regex policy, #532's sole `CTFFlag` truth, #1135/#1137's
submission concurrency, #1018's recovery, #307/#450's range admission, and
#28's warm handoff. CTF-909/#623's supporting-asset orchestration is separate:
an operator-deployed verifier is sufficient; this issue does not build that
orchestrator. These relationships were reconciled from the current repository;
no live issue/requirement status or delivery completion is asserted.

Apply ADR-001 (service boundaries), ADR-011 (installation configuration),
ADR-019 (real internal test paths), ADR-025/043 (lifecycle delivery/persistence),
ADR-028 (history privacy), ADR-032/039 (RAES/substrate ownership), ADR-040
(public API), ADR-045 (shared audit), ADR-046/054 (authority), and ADR-056
(guest-root threat model). Proposed ADR-059–061 are adjacent model-access
designs, not receipt registries or authorization tokens to repurpose.

CTF owns participant/challenge authority, validation dispatch and scoring. CMS
owns the participant's range projection, owner, provenance and lease. Engine
owns materialization identity, operation fencing and range-bound verifier
registration lifecycle. A trusted provisioning/activation integration enrolls
against the exact current Engine operation ID; stale callers fail closed. A deployed verifier or installed
validator adapter owns proof-format interpretation and cryptographic checking.
Only portable platform context/result projections shared across those boundaries
belong in `shared`; the signed proof format remains the provider's contract.

## Trusted context and extension seam

Extend `submit_flag` → `verify_flag` → `verify_single_flag`, not the participant
request body. A keyword-only immutable `server_context` carries the expected
binding. Resolve the authenticated participant through the incumbent API/legacy
view helpers, then enforce `assert_participant_can_compete` and
`assert_challenge_available_for_participant` in the service. The expected facts
are event UUID, CTF participant UUID, challenge UUID, the explicitly assigned CMS
range-instance identity, immutable materialization identity, and current
assignment/registration epoch. Bind deployment/audience and trusted key/profile
selection as well. Published adapters may map these facts to their wire names;
this list is not a second signed-receipt schema.

Resolve the exact `CTFParticipant.range_instance_id` through `ctf.bridges` →
`cms.services` → `engine.services`. Confirm CTF provenance, participant user
ownership, scope consistency, authoritative lifecycle state, lease and active
registration. Missing, ambiguous, soft-deleted, recovering, expired or
unregistered bindings fail closed for receipt validators. Do not look up any
ready range by user, infer identity from IP/DNS/instance name, use the denormalized
participant `range_status` as authority, or substitute a CMS integer PK for an
Engine UUID, request UUID or guest-instance UUID. Event workspace and participant
range workspace have different owners; current participant/spare provisioning
does not establish that they are equal. Validate their actual authorized mapping
through existing services, not a newly assumed equality or workspace membership
as CTF authority. Teams are scoring groups, not receipt subjects.

The seam is a closed versioned `validator_config.protocol`, defaulting to the
legacy contract, plus explicit context capability on the incumbent
`ctf.extensions` and `ctf.validators._registry` registrations. Preserve existing
two-argument extension and programmable callables, legacy HTTP GET/POST payloads,
static/regex behavior, installed-app initialization, and any-of `CTFFlag`
semantics. Do not detect signatures by catching `TypeError` and calling twice,
inject trusted values into mutable organizer `params`, require a range for
legacy flags, or silently downgrade an unsupported receipt protocol. Receipt
errors must not become truthy objects. Use a strict verdict for the new protocol;
legacy adapters retain their documented signatures. Exceptions at the installed
extension boundary must fail closed without leaking exception text.
Because flags retain any-of semantics, a challenge with an additional legacy
flag can still be solved through that flag. A challenge advertised as requiring
bound proof must contain only approved receipt-capable acceptance paths; do not
silently change any-of into all-of or treat a legacy success as receipt evidence.

A deployment-owned verifier profile fixes endpoint, audience, request-auth
reference, permitted key modes, contract version, replay policy and bounds.
Organizer configuration selects an authorized logical profile, never an
arbitrary destination for a platform credential. Scope profile use to the event's
authority. Trust only context in the authenticated request, never authored query
parameters, headers, bundle fields or embedded receipt claims. Reserve context,
authorization, content-type and framing header ownership case-insensitively;
reject duplicates/control characters. The receipt profile uses POST, no secret
or binding query parameters, no userinfo or fragments, no cookies, and no
redirects. Legacy HTTP routing queries remain compatible without acquiring any
trusted-context meaning or platform credential.

The selected provider publishes `PENR1` with exactly `version`, `flag_id`,
`outcome`, `evidence`, `range_instance`, `participant`, `reset_generation`,
`verdict`, `issued_at`, and `expires_at`. Its independent platform callback and
conformance fixtures are maintained in the scenario source. Other profiles must
publish their exact versioned request, response, registration, and claim
contracts before enablement. One future
issuer or algorithm should require an approved profile/adapter, not edits to
submission/scoring, range schemas or a generic request-template language.

## Signer, key registration and deployment boundary

The adversary includes root on a participant VM/container host, as documented in
the [containment threat model](gcp-range-cell-containment-threat-model.md).
A file mode, container, obscured environment variable or attached service account
cannot hide a signing secret from that adversary. The range-associated signer
must be outside participant control (an isolated issuer workload or protected
signing service). It fixes the enrolled binding and allowed challenge claims;
it must not sign participant-selected subjects or arbitrary success claims.
Scenario-specific evidence evaluation stays with the proof provider. A signature
authenticates that provider's assertion; it does not independently prove that an
exploit occurred.

Support two key modes through the same registration lifecycle:

| Mode | Material and authority |
| --- | --- |
| Per-range symmetric | A distinct cryptographically generated secret per materialization/assignment epoch is available only to the protected signer and isolated verifier. Portal-process plugins cannot receive it; they invoke the authenticated verifier. |
| Asymmetric | Private key stays with the protected signer. Verifiers, including an installed local adapter, receive only registered public verification material. Allowlisted algorithm/key use and bounded key ID are registered together; a receipt cannot select a new issuer, algorithm family, URL or key. |

Separate signer authority, enrollment/revocation authority and portal-to-verifier
request authentication. A user session, user API token, model grant, VPN key,
Django signing key or `FIELD_ENCRYPTION_KEY` is not a receipt signing key.
Use existing workload identity and secret-store adapters for an exact verifier
audience/endpoint (audience-bound workload authentication or a profile-owned
service credential). TLS authenticates the server but alone does not authenticate
the platform caller. Registration authenticates the provisioner/Engine operation
and expected range binding; possession of an unregistered public key or `kid`
does not confer enrollment authority. Exact replay of registration is idempotent;
same identity with different key/binding is a conflict. Never fetch `jku`, `x5u`
or an equivalent destination supplied by the receipt.

Store only bounded registration metadata, immutable secret-version references
and public keys in Engine-owned state. Reuse provider `SecretsStore`,
`gcp_dynamic_secrets` / AWS secret helpers and their reconciliation/deletion
patterns. New GCP signing-secret classes must remain outside the portal's finite
participant-access name classes (ADR-008-R7); shared host-pool accounts are not
exclusive range identities. No project-wide secret access, new portal payload
grant, generic guest credential download, or HMAC key in `validator_config`.
Secret deletion is cleanup, not the admission fence.

## Generation, invalidation and transaction semantics

`Range.provisioner_operation_id` is the current command generation:
`engine.launch_intents._operation_identity` changes it when operation kind changes.
It is not inherently a stable materialization identity across pause/resume.
Anchor registration to the existing provision/activation operation that produced
the materialization and preserve that identity in Engine-owned registration
metadata. A separate assignment/registration epoch fences reuse of the same
range by a new participant, including warm/spare handoff and A→B→A reassignment.
Do not invent a parallel range lifecycle or derive either epoch from timestamps,
range name, package digest, retry count or CMS request ID alone.

Reset/rebuild, reassignment, teardown admission, lease expiry and failed
provisioning make the previous registration unusable before new ownership or
readiness is exposed. Recovery starts by fencing the old assignment; a later
failure must not reactivate it accidentally. Enroll the replacement only after
the authoritative handoff and required signer/verification readiness. Warm/spare
resources have no participant receipt authority before assignment. If safe
in-place key/epoch rotation is unavailable, deny that handoff and use existing
rebuild recovery, as the VPN ownership-transfer guard already does. Suspend
receipt admission during pause; resume may retain the same materialization if
no reset occurred. Key rotation within one assignment may have bounded overlap;
reset/reassignment never has an old-binding grace period.

The callback remains non-consuming and runs outside database locks. Carry its
verified binding, validity deadline and (when required) receipt identifier into
the incumbent submission transaction. Before recording a correct submission,
reload and reauthorize the participant/challenge and compare the exact binding,
registration revision and deadline under a fence shared with lifecycle writers.
The existing participant lock currently discards the freshly loaded row, and
recovery repointing does not consistently use that lock: merely adding another
pre-call read does not close the race. CTF assignment writers and CMS/Engine
revocation/ownership paths must serialize with the acceptance check through
public services, with one documented lock order compatible with dynamic scoring
and recovery. No remote I/O under these locks. A solve committed before revocation
is historical truth; one racing after revocation cannot commit from an old verdict.

Use `transaction.atomic`, the existing participant/challenge locks, named
`ctf_unique_correct_submission` constraint, scoring strategies and materialized
leaderboard transaction. The default receipt replay policy is one successful
redemption per receipt identity, alongside the incumbent already-solved gate.
That partial constraint alone is insufficient: soft deletion of a solve permits
re-solving. A protocol requiring one-shot use therefore returns a stable,
verified issuer-scoped receipt identifier; persist bounded consumption evidence
with DB uniqueness in the same CTF transaction and retain it through the receipt's
expiry/skew horizon even if the solve is soft-deleted. This is narrowly necessary
receipt evidence, not another scoring ledger or remote redemption workflow.
Do not use raw signature bytes as identity (alternate encodings/signatures may
represent the same receipt), process-local caches, or Redis as replay truth.
Rollback leaves the receipt retryable. Ordinary event history and points survive
range reset; resetting a range is not resetting scores.

Engine registration and revocation are durable, transactional admission state;
CTF recovery remains its checkpointed workflow. Provider reset and teardown use
the provider's lifecycle and must not be treated as the database admission
fence. Retries and stale operation generations cannot resurrect revoked epochs.
Across multiple verifier replicas, reset/revocation and cache expiry must
converge within documented bounds, and final platform admission always checks
authoritative registration rather than trusting cached success.

## Cross-cutting gates and canonical incumbents

Paths below are relative to `shifter/shifter_platform` unless qualified.

| Layer | Required incumbent and obligation |
| --- | --- |
| Authentication/authorization | `ctf.api._base`, `ctf.api.organizer._base`, `ctf.views._access`, `shared.api.principals.active_actor_user`, bearer-first API authentication, exact play scopes, session CSRF and CTF account middleware. Neither body participant IDs nor organizer/root status substitute for the submitting participant. Recheck service authority at commit. |
| Input and authored configuration | `ctf.api.serializers.participant`, flag CRUD/`validate_http_flag_config`, `ctf.content_bundle`, hydration/refresh services and model validation. One protocol-aware pure validator/normalizer must serve writes, hydration and runtime; today's bundle closed field set rejects `protocol`, while runtime coercers tolerate shapes the bundle refuses. Version any incompatible bundle expansion explicitly. Reject Boolean/non-finite timeouts, unknown members and conflicting duplicate JSON keys before mapping conversion; unknown-key serializers do not detect duplicate JSON. |
| Size and storage | `CTFSubmission.submitted_flag` is currently 500 characters; the request serializer has no matching maximum. Fix the receipt budget coherently across service, API, database, UI and HTTP transport before claiming support; never truncate a signed value. Preserve case and define whitespace framing explicitly. Validate before expensive work even for internal callers. |
| Transport and resource exhaustion | `ctf.validators._http`/`_ssrf`: all DNS answers must pass, connect to a checked IP, preserve original SNI/Host and certificate verification, TLS floor, no redirects, bounded bodies, HTTP 200 and strict verdict. Current socket timeout is per address and read; impose a finite total deadline covering DNS, address count/fallback, TLS, reads, secret lookup and all any-of validators. Bound request bytes, headers, parse depth and remote concurrency; prevent slow-read and duplicate-key verdict bypasses. Reuse `shared.rate_limit` and submission pacing gates, including pre-verification admission against callback flooding. A thread timeout does not stop arbitrary plugin code: installed apps are trusted code, with bounded local work or isolated HTTP execution. |
| Network deployment | ADR-008/017/020/030/056, denied-network inventory, Terraform firewall/IAM and Helm/Kubernetes NetworkPolicy. Preserve safe public HTTPS callback policy; a private verifier needs an explicit authenticated service boundary and exact egress policy, not a private-CIDR exception in `_ssrf`. Lab browser trust roots must not enter global platform TLS trust. Qualify each advertised cloud backend independently. |
| Configuration/env shapes | `.shifter.yaml`, `shifter/installation` validators/renderers, `config/settings.py`, `_runtime_env.py`, generated `config/env-manifest.json`, `scripts/gcp/render_runtime_env.py`, `entrypoint.sh`, provisioner config, task env inventories and Helm values/schema. Any added profile/auth reference must pass these actual closed shapes and renderer parity checks; missing capability configuration fails closed only for opt-in receipt use. Do not add an unvalidated JSON env escape hatch. |
| Secrets and OS/runtime | `shared.cloud.sensitive_env.split_env`, Kubernetes per-Job `secretKeyRef` creation/cleanup, cloud secret adapters, operation input/result parsers, guest secret delivery and provisioner logging. Signing material never enters the portal, participant host, argv, env literals, Terraform state/userdata, rendered manifests, command output or operation results. Even a variable ending `_REF` must actually contain a reference, not secret bytes. Service auth secrets use existing secure hydration; argv carries only canonical operation/identity correlation. |
| Persistence and lifecycle | `ctf.services.submission`, `ctf.services.range.{provision,recovery,recovery_steps,spares,lifecycle}`, `cms.services._range_reassign`/`_range_lease`, Engine launch intents/result applier, ADR-025 reconciliation and shared schema validation. Extend their ownership/fencing contracts, not cross-layer ORM imports, provisioner SQL into CTF, `RangeSpec` scratch state or generic JSON field patches. |
| Errors, audit and observability | `CTFValidationError`/existing CTF and cloud errors, `_CtfApiError`, `shared.api.errors`, `shared.audit`, CTF audit helpers, `shared.log_sanitize`, `config.logging.ECSFormatter`, provisioner `log_redact`. Fixed public incorrect/service-error envelopes; distinct bounded operator categories for invalid proof versus outage. Sanitizers/`error.details` normalization and `logger.exception` are not general redaction. No receipt bytes, headers, URL queries, keys, nested provider exceptions or raw bodies in logs, traces, metrics, audit or failure events. Audit registration/revocation with authenticated actor, operation and bounded binding metadata; required security-state audit commits with its transaction. Metrics use bounded labels, not participant IDs. |

Authorized submission-value history under CTF-1305 is a distinct sink from logs
and error envelopes. A receipt profile must declare its retention/disclosure
contract and use only opaque identifiers, never embedded personal data or
signing material. Preserve legacy history semantics and ADR-028 ownership checks;
if its proof format cannot safely be retained/displayed there, explicitly define
and document a receipt-specific redacted projection and bounded evidence storage.
Do not silently expose a reusable credential in search/export/admin surfaces or
remove history for every flag type. Validator outage must have a documented
attempt/cooldown effect: retain legacy HTTP behavior, while receipt-specific
unavailability uses the existing service-error boundary without consuming a
receipt or awarding a solve.

## External lineage and acceptance evidence

The provider chooses its proof format. For JOSE-based profiles, use maintained
libraries with [RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html) algorithm,
issuer/subject/audience and explicit token-type validation; prohibit algorithm
confusion and acceptance of ordinary login tokens as CTF proof.
[RFC 7519 §4.1](https://www.rfc-editor.org/rfc/rfc7519.html#section-4.1)
provides expiry, not-before and receipt-ID lineage; make required claims, maximum
lifetime and finite clock skew explicit in the provider profile.
[RFC 7517](https://www.rfc-editor.org/rfc/rfc7517.html) provides key-set/key-ID
lineage, not trust in participant-supplied keys. These references do not mandate
JWT or supply participant/range authorization. Application binding, registration
and transaction fencing remain Shifter's obligations.

The rows below map #1906's issue requirements → ADR-062 decisions → executable
evidence. Source-level tests ship with #1906; fresh provider deployment and a
distinct second generation remain the #1910 composition gate.

| Issue contract | Design rule | Required evidence and incumbent suites |
| --- | --- | --- |
| Correct assigned-range receipt accepted | R1/R2 | Real `submit_flag` path plus provider conformance fixture and authenticated transport: correct event/participant/challenge/range/materialization/epoch. Extend `tests/ctf/test_programmable_flags.py`, `test_flag_verifiers.py`, `test_submission_service.py`. |
| Every binding failure rejected | R1/R2 | Independently change deployment/audience, issuer/key, event, participant (including same user in another event), challenge, range, epoch; absent/unready/deleted binding, expiry/not-before/skew, invalid signature, unknown algorithm/key, tampered request and spoofed config fields. Verify zero score and no consumed receipt. |
| Reset/reassignment/stale-generation rejection | R3 | Extend real recovery/spare tests and CMS owner-transfer tests, including A→B→A, warm activation, failed handoff, pause/resume, teardown and lease expiry, old key caches, delayed results and crash/retry reconciliation. Require fresh enrollment and old-epoch rejection under concurrent submission. |
| Replay and transaction safety | R3 | PostgreSQL separate-connection barriers in `tests/ctf/test_services/test_submission_concurrency.py`: simultaneous receipt submissions, reset/reassignment between callback and commit, rollback after successful verification, soft-deleted solve, multi-worker restart, duplicate signed representations of one receipt, dynamic scoring/hints. Assert durable consumption and score invariants, not just callback return values. |
| Authenticated, bounded, fail-closed requests | R2/R4 | Extend `test_programmable_flags_security.py` at socket/TLS/provider boundaries: wrong/missing auth, forbidden destination, mixed DNS answers, rebinding, TLS mismatch, no redirects, total timeout across addresses/slow reads, oversized request/body, duplicate/ambiguous JSON, malformed verdict, provider outage and exception redaction. Capture logs, errors, task specs and argv for synthetic secret canaries. |
| All existing flag types compatible | R1/R4 | Static/hash, regex/case policy, programmable registry and installed extension callables, legacy HTTP GET/POST/query/header behavior, any-of and no-flags behavior. Include bundle hydration/refresh and API/history contracts; extend `test_flag_source_of_truth.py`, `test_regex_flag_safety.py`, `test_content_bundle.py` and existing service tests. |
| Operator/extension contract and key lifecycle | R2/R4 | Extend `docs/technical/shifter_platform/ctf.md`, `docs/dev/ctf-scenario-content.md` and organizer guidance with exact profile examples using fake refs, key enrollment/rotation/revocation, deployment ownership, failure/attempt behavior, replay/retention/skew and supported provider versions. Fresh deployed range positive/negative tests plus teardown/second allocation and IAM denial of signing material to portal/guest are required release evidence. |

Reuse ADR-019 testing: run real first-party services/models and mock external
HTTP/cloud boundaries, not a pre-approved context resolver. Existing named suites
do not already cover the new claims. Record eventual test symbols/results and
deployed evidence against #1906; record related requirement links through Ground
Control only if scope is later explicitly attached.

The existing ADR registry/import/secret/IAM checks remain mandatory. This note
adds design rules, no exception or executable guard. Implementation must extend
the incumbent shape, IAM and lifecycle tests where artifacts change, and run
`adr_guard --all --level ci`, import-linter/Ruff for platform Python, and the
repository's Terraform, actionlint and Kubernetes checks for their touched
surfaces. Registry success proves none of the receipt runtime invariants.

## Non-goals and prohibited shortcuts

No new public receipt-submit or score-award route, flag type, plugin lifecycle,
generic cryptographic framework, identity provider, event-asset orchestrator,
receipt polling controller or remote two-phase redemption service. No scenario
names, challenge heuristics, mission fields or proof evaluation in core Shifter.
No changes to ordinary scoring, range-source meaning, tenant authority or legacy
validator signatures. No broad SSRF/TLS/IAM exceptions, guest-root-protected
"secret", trusted organizer JSON, duplicate authored/runtime schema, exception
hierarchy, or optimistic cached verdict masquerading as current authorization.
