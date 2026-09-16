# ACES Composition Realization Verification Preflight

Issue: GitHub #1569, "verify ACES composition realization in-guest."

Status: pre-implementation architecture guidance. This note does not add a
probe, change runtime evidence, modify the validation package, or enable the
ACES-native path.

## Boundary and decisions

Composition success must become a synchronous precondition of ACES range
success. VM creation, startup-script submission, a bootstrap marker, command
exit alone, and the current topology-only snapshot are not composition proof.
Every admitted content placement, local-account placement, and feature binding
must have its claimed guest state read back on every concrete instance of its
target node before `apply_aces_range_cell` returns, the runtime snapshot is
emitted, the ACES operation becomes `succeeded`, or the range becomes `READY`.
Domain-bound accounts and SPNs retain the #1561 scope: realize and read them
back once from the declared authoritative directory, not once per member VM.
That authority-scoped exception must stay explicit; it does not permit one
successful local guest to stand in for failed siblings.

Keep the existing realization mechanisms and close only their proof gap:

- Source-backed content already uses authenticated post-boot delivery plus an
  independent installed-file/tree digest readback. Feature services and
  artifact/configuration bindings use the same synchronous setup/verification
  boundary. Active Directory accounts and SPNs already use directory readback.
  Preserve those authorities; do not run a second delivery workflow.
- Inline files, source-less directories, and local-account attributes remain
  idempotent bootstrap effects, but require a post-boot probe over the existing
  authenticated guest channel. The probe checks the resulting state, not a
  marker or bootstrap log. Existing credential plans count only when their
  `verification_result` succeeds.
- A successful guest-local per-authored-item result means every fan-out instance
  of the target node passed. A successful directory-scoped result means the
  declared authority readback passed under the #1561 domain contract. One
  successful local copy must never mask a failed sibling. Retry/reconcile
  repeats the applicable idempotent state check.

Reuse `runtime_snapshot-v1` as the sanitized evidence surface. Extend its
existing `resources` list with one entry per verified authored composition
resource, using only the existing shape:

```json
{"address": "<compiled resource address>", "resource_type": "content-placement|account-placement|feature-binding", "status": "verified"}
```

The entry is an aggregate assertion made only after every applicable concrete
guest passes, or after the declared authority passes for a directory-scoped
account/SPN. It contains no target address, node index, username, group, shell,
home, path, source, version, feature name, service name, digest, mode, SPN,
domain, secret reference, command, output, or diagnostic. The producer must
prove exact coverage of the plan's composition resource identities before
publishing; a plan-derived entry without a completed state check is an
over-claim. Keep topology entries (`node`/`network`, `provisioned`) unchanged.
This is an additive use of the current snapshot contract, persister, outbox
events, retention, projections, and Mission Control endpoint, not a new record
kind, participant-runtime record, table, API, or receipt.

`run_aces_backend_validation` must continue to launch through the product path
and read through `shared.aces.projections`, but its non-vacuous gate must also
require verified composition evidence. The canonical validation package must
author representative content, account, and feature composition so a
topology-only backend cannot pass. The evidence collector must reject malformed,
duplicate, unverified, or forbidden-detail composition entries and require the
expected composition kinds; it must not read raw ORM rows or the serialized
plan as a shortcut.

## Canonical incumbents to reuse

| Concern | Canonical incumbent and boundary |
| --- | --- |
| ACES schema and admission | `shared.aces.runtime_target`, `composition_envelope`, `realization_ledger`, and `manifest` remain the only ACES-aware capability/admission path. Do not create a composition DTO or duplicate SDL validation outside `shared.aces`. |
| Provisioner plan projection | `aces_plan`, `aces_composition`, and their version/shape/reference checks remain the plain-data consumer boundary. Compiled resource address is the evidence identity; authored values are probe inputs only. |
| Guest execution | `executors.factory.build_guest_execution_context`, `GuestSSHExecutor`, `SetupOrchestrator`, `SetupStep`, and the Linux/Windows setup-plan dialects own readiness, strict host-key SSH, retry, timeout, script transport, and verification results. Add no SSH, WinRM, agent, callback server, or cloud-metadata polling path. |
| Existing verified realization | `aces_content_delivery`, `plans.aces_content_delivery`, `plans.aces_feature_service`, `aces_account_credentials`, and `aces_active_directory` remain authoritative for their effects. A caller must inspect `verification_result.success`; `SetupResult.success` alone is not verification. |
| Lifecycle and cleanup | `aces_gcp_apply` and `aces_range_ops` retain the one failure boundary: a failed/missing probe triggers existing reconstructive cleanup and `failed`; evidence and `READY` occur only after apply succeeds. |
| Evidence construction | `aces_snapshot.snapshot_resources` is the single reducer. `events.publish_aces_snapshot`, `range.aces.snapshot`, `engine.services.record_aces_runtime_snapshot`, and `shared.aces.operations.persist_runtime_snapshot_record` remain the only write workflow. |
| Persistence and reads | `AcesOperationRecord`, its idempotency/retention policy, `shared.schemas.aces_operation`, `shared.aces.projections`, and the Mission Control ACES runtime-snapshot endpoint remain canonical. Do not persist guest output or add a composition-result repository. |
| Validation workflow | `cms.aces.validation`, `run_aces_backend_validation`, and `scenario-dev/shifter-aces-validation` remain the cutover gate. Keep normal launch ownership, active-range admission, audit, polling, and teardown. |
| Errors and logs | Reuse `AcesGceCompositionError`, the existing bounded realizer errors, `SetupError`, provisioner `log_redact`, platform `shared.log_sanitize`, and the existing ACES status/API envelopes. Do not add an exception hierarchy for probe failures. |

## Cross-cutting layers the design must pass

### Security and validation

1. **Package, SDL, and capability gates:** package containment/digest checks,
   upstream ACES parsing, manifest diagnostics, `composition_envelope`, the
   independent realization ledger, domain-topology checks, and the default-off
   feature flag all remain before dispatch. Verification does not make an
   unsupported shape admissible. If an account feature cannot be realized and
   checked with its authored semantics on a supported OS (notably `shell`/`home`
   on Windows), the common OS-aware `validate()`/`apply()` admission path must
   reject it before dispatch and the provisioner must repeat that rejection
   before mutation. Existence is not an approximation and the coarse manifest
   must not over-claim.
2. **Provisioner transport gate:** `parse_plan` repeats contract/producer
   version, resource shape, identity, duplicate, and reference validation before
   cloud or guest mutation. Probe construction consumes only this validated
   process-local projection. It must not parse raw persisted dictionaries again.
3. **Probe shape and command safety:** account identifiers, groups, paths,
   expected digests, and service identities pass the incumbent OS-specific
   validators and quoting/encoding rules. Linux values travel in the script
   supplied over SSH stdin and are shell-quoted; Windows uses a static
   PowerShell script with runtime values on actual stdin where the incumbent
   plan supports it. Never concatenate unvalidated values into a command name.
4. **Guest-state semantics:** inline files require exact installed-byte digest
   readback, link/reparse-point defenses, and exact backend-owned permission
   policy. Linux sensitive files require the expected owner and mode; Windows
   sensitive files require the expected owner and a protected ACL with no
   unexpected allow or deny principal -- `AreAccessRulesProtected` alone is not
   proof. Directories require a real directory with link/reparse-point defenses;
   local accounts require existence plus every authored
   group/shell/home/disabled/auth-method effect; services require
   package/version presence and enabled/running state; delivered files/trees,
   domain accounts, and SPNs retain their stronger incumbent probes. Fixed
   markers may identify probe completion but are never the checked state.
5. **Evidence write shape:** strengthen the current
   `shared.schemas.aces_operation` runtime-snapshot validation as needed; keep
   bounded JSON, secret-key rejection, payload digest verification, aware
   timestamps, contract/profile checks, and idempotency. Composition entries
   have exactly `address`, `resource_type`, and `status`, with allowlisted types
   and `verified` status. Preserve the existing 64 KiB payload bound: validate
   the complete sanitized snapshot before cloud mutation and fail closed if it
   cannot fit; never truncate, sample, or silently omit composition evidence.
   Old topology-only v1 snapshots remain readable during rolling deployment.
6. **Evidence read/auth shape:** `shared.aces.projections` remains the response
   allowlist. Mission Control continues to require authenticated session/API
   token, Mission Control actor, exact range-read scope, and ownership lookup
   before sidecar access. `cms.aces.validation` reads only that redacted seam and
   retains the forbidden-substring defense in depth.

### Secrets, config, OS exposure, and error envelopes

- **Secrets:** use only the provisioner-managed host SSH secret and trusted host
  public key already carried by the instance output. Retrieval remains through
  the cloud secret-store adapter; `GuestSSHExecutor` owns private temporary key
  permissions and cleanup. Account passwords/public keys retain their existing
  Secret Manager paths and masking. No probe secret, callback token, guest cloud
  credential, presigned URL, or persisted bootstrap result is added.
- **Config and env shapes:** `SHIFTER_ACES_NATIVE_PROVISIONING` remains the only
  feature gate and stays default off. No new setting, env var, Terraform input,
  Kubernetes admission field, IAM permission, port, or firewall rule is needed.
  Reuse injectable setup operations/timeouts for tests; if a later operator
  knob is justified, it must flow through typed config, `env-manifest.json`,
  runtime renderers, deployment manifests, and parity checks once.
- **Process and host exposure:** the provisioner command remains
  `aces-range provision --request-id <uuid>`; plan and expected state remain
  DB-backed. Do not put authored composition, payloads, digests, credentials, or
  results in CLI argv, environment, VM labels, GCE metadata, process titles, or
  workflow output. This issue does not expand the existing inline-text startup
  metadata path. PowerShell's encoded static script may be in argv, but runtime
  values and secrets must not be.
- **Logs and errors:** setup orchestration logs stdout/stderr and target details,
  so probes emit fixed bounded markers only and never echo checked values.
  Convert executor/provider failures to value-free composition failures before
  `aces_range_ops`, which otherwise logs and forwards `str(exc)`. `safe_log_value`
  prevents injection; it is not confidentiality redaction. Status reasons,
  range failures, command errors, and API errors must expose only a stable phase
  and generic failure, correlated by request id.

## Extensibility seam

The existing `SetupPlan`/`SetupStep` OS dialect is the probe seam. It is
parameterized by one validated node projection and that node's applicable
composition placements, produces only fixed success/failure, and is invoked
through the injected guest-execution/orchestrator operations already used by
content and features. A later composition kind adds one fail-closed admission
entry, one OS-specific state check, and one allowlisted snapshot resource type;
it does not change dispatch, persistence, auth, transport, lifecycle, or the
validation command. Provider variation remains behind
`build_guest_execution_context`; guest-local fan-out remains a node `count`
concern, while directory-scoped cardinality remains owned by the domain-address
seam established in #1561.

## Whole-repository scope and evidence expectations

The implementation must evaluate the following together:

- ADR-031/032/034, `aces-cutover-evidence-1264.md`, and the #1560/#1561/#1564/
  #1565 preflights;
- `shared/aces/{manifest,realization_ledger,composition_envelope,runtime_target,
  contracts,operations,projections}.py` and `shared/schemas/aces_operation.py`;
- CMS native launch services, `cms/aces/validation.py`, the validation command,
  validation package, and Mission Control ACES API auth/serializers;
- Engine ACES range persistence, dispatch, event consumers, idempotent sidecar
  persisters, retention, and status projection;
- provisioner `aces_{plan,composition,gcp_composition,gcp_apply,content_delivery,
  account_credentials,active_directory,range_ops,snapshot}.py`, setup plans,
  executor factory/SSH transport, setup orchestrator, secret adapters, and
  reconstructive cleanup; and
- `_aces_settings.py`, `env-manifest.json`, task-runner request-id CLI, GCE
  startup metadata, Terraform/Kubernetes runtime/IAM surfaces as unchanged
  boundaries, plus import/layer/ADR guards.

Evidence must cover Linux and Windows; multiple authored items on one node;
`count > 1`; every claimed account attribute; inline/sensitive file and empty
directory state; all feature shapes; existing source-backed and AD readbacks;
verification nonzero/timeout/transport failure; missing/duplicate/malformed or
value-leaking snapshot entries; exact composition coverage; cleanup and absence
of `succeeded`/snapshot/`READY` on failure; command validation requiring all
three composition kinds; and flag-off/cyberscript invariance. Script-rendering
or mocked snapshot tests alone are not cross-boundary evidence.

## Gotchas and anti-patterns

- Do not turn startup metadata success, a marker file, VM reachability, parent
  directory, package-manager exit, or `SetupResult.success` into proof.
- Do not add a callback listener, guest agent, metadata result blob, Pub/Sub
  topic, polling table, composition sidecar kind, participant record, or audit
  payload. The authenticated post-boot channel and runtime snapshot already
  cover the need.
- Do not re-deliver source content or features merely to verify them, and do not
  merge content, accounts, and features into a second authored schema.
- Do not emit plan values, guest paths, usernames, groups, SPNs, digests,
  stdout/stderr, provider errors, instance indexes, IPs, or secret references as
  evidence or diagnostics.
- Do not report one verified authored item when only one of a node's concrete
  instances passed, and do not publish plan-derived composition entries before
  exact guest-check coverage succeeds.
- Do not bypass the operation-record size bound or publish a partial snapshot.
  A future scale/pagination contract must be versioned explicitly rather than
  smuggled in as multiple incomplete `runtime_snapshot-v1` records.
- Do not silently ignore unsupported Windows/POSIX semantics, missing groups,
  unavailable package versions, failed verification steps, or unsupported
  retries. Narrow admission/capability claims rather than approximate.
- Do not create duplicate validators, evidence reducers, serializers,
  repositories, cloud factories, guest executors, exception families, or
  lifecycle state machines.

## Non-goals and implementation boundaries

- No ACES cutover, default-flag change, cyberscript behavior change, new cloud
  provider, participant-runtime capability, evaluator/observation protocol, or
  public write API.
- No replacement of the ACES plan, backend manifest, realization ledger, guest
  executor/orchestrator, range lifecycle, operation sidecar, or Mission Control
  authorization model.
- No general remote-execution redesign, arbitrary probe/plugin language,
  pack-supplied commands, guest callback service, new persistence, or raw
  bootstrap-log collection.
- No migration of existing inline ACES text out of the compiled plan/startup
  metadata and no redesign of account credential generation; the change may
  read back those existing effects but must not duplicate their sensitive data.
- No claim for an account/content/feature shape whose full supported-OS and
  applicable guest-local fan-out or directory-authority semantics cannot be
  verified before `READY`.
