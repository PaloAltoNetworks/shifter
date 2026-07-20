# ACES Account SPN Realization Preflight

Issue: GitHub #1561, "feat: realize ACES account SPN as a real service
principal (currently a marker file)."

Status: pre-implementation architecture guidance. The issue is the shipping
contract. This note does not implement Active Directory, SPNs, or capability
changes and is not an implementation plan.

## Boundary And Decisions

An ACES account `spn` is directory identity state. It is not a guest account
attribute, local-user metadata, a hostname alias, or a file. Genuine realization
requires a live identity authority that owns the principal, uniqueness-preserving
registration in that authority, and readback from the authority after mutation.

Use the released ACES 0.23 public contract consumed by #1606:
`identity_domains`, `domain_controller_for`, `joins_domain`, compiled
`domain_topology` bindings, `supported_domain_profiles`, and
`domain_topology_plan_diagnostics()`. The serialized ACES `ProvisioningPlan`
remains the only authored-intent contract. Do not add a Shifter domain DTO,
package sidecar, CMS model, tag convention, or provider overlay.

The first genuine Shifter profile is range-local Windows Active Directory on the
GCE range-cell backend. For every admitted domain, the backend promotes and
verifies one Windows controller, joins and verifies its Windows member nodes,
realizes domain-bound accounts in AD, registers each authored SPN uniquely, and
reads the resulting `servicePrincipalName` back from AD. Non-Windows domain
participants and more than one controller per domain fail before dispatch in
this slice. The implementation must remain keyed by domain identity so those
constraints can be widened later without introducing a singleton domain config.

Do not choose the issue's controller-only shortcut under the current public
contract. ACES 0.23's `active_directory` profile carries both controller and join
semantics; publishing that profile while recognizing only a controller would
make the capability declaration ambiguous. Do not encode a `controller-only`
Shifter constraint string to work around the public contract. A later released
public profile/sub-capability could support that alternative explicitly.

Move these three independently authored declarations together, and only after
the full effect chain has cross-boundary evidence:

- add `active_directory` to
  `SHIFTER_PROVISIONER_CAPABILITIES.supported_domain_profiles`;
- add `spn` to
  `SHIFTER_PROVISIONER_CAPABILITIES.supported_account_features`; and
- add `spn` to `REALIZED_ACCOUNT_FEATURES`.

Regenerate `shared/aces/backend-manifest.json` from `manifest.py`. A parser,
rendered PowerShell command, secret row, startup script, provisional snapshot,
or successful VM launch is not evidence for any of those declarations.

Everything remains behind `SHIFTER_ACES_NATIVE_PROVISIONING` (default off). Add
no second flag or domain/SPN setting.

## Effect And Ordering Contract

The public resource addresses, `domain_topology` bindings, and
`ordering_dependencies` define the graph. The provisioner must retain and
revalidate them across its separate deployable boundary; it must not infer order
from names, list position, image identity, IP suffixes, or a legacy `role="dc"`.

The realized dependency chain is:

1. all GCE network and instance resources exist and the provisioner management
   channel is ready;
2. the topology's authority account has a deterministic backend-owned password,
   distinct from the management SSH identity;
3. each controller is promoted, rebooted, reconnected through the same pinned
   host-key channel, and verified against the exact authored DNS/NetBIOS identity;
4. the controller creates a machine-scoped offline-domain-join package for each
   member; the member is pointed at its declared controller, applies only that
   package, reboots, reconnects, and is verified against the exact domain;
5. each domain-bound account is created or reconciled once in that domain, not
   once per target-node instance; and
6. the SPN is registered with duplicate detection and then read back from the
   same directory principal. A missing, conflicting, or mismatched readback
   fails the range.

The authority account is bootstrap authority, not a normal local placement and
not a participant login. Other accounts with an explicit `domain_ref` are domain
principals. They must not also be created by Linux `useradd`, Windows
`New-LocalUser`, or the local-account credential installer. Accounts without a
domain binding keep the existing local-account path.

Initial backend policy for an admitted `active_directory` binding is deliberately
bounded:

- one concrete Windows controller instance per domain; controller `count > 1`
  and multiple controller addresses fail closed;
- every member is Windows and has range-internal reachability to its declared
  controller under the realized primary-network/firewall model;
- the first-profile authority account denotes the built-in domain Administrator
  identity (RID 500), is authored as `Administrator`, is enabled and
  password-authenticated, and has a usable generated password policy. Promotion
  and post-reboot readback must verify that exact identity; local-only `groups`,
  `shell`, and `home` terms are rejected because this path does not realize them,
  and no process-wide or authored credential is accepted;
- a domain account uses an AD-portable, case-insensitively unique account name
  and an admitted domain account/authentication field combination. The minimum
  #1561 slice accepts an enabled password account with no local-only `shell`,
  `home`, or public-key semantics. A requested `groups` or `disabled` effect is
  either realized and read back in AD in the same change or rejected before
  dispatch; the existing local-user support claim does not transfer to AD; and
- an SPN is a bounded, canonical, single-line service/instance value. Leading or
  trailing whitespace, control characters, missing service/instance components,
  directory-equivalent duplicate authored values, and a value already owned by
  another directory principal in the forest are rejected. Preserve authored
  case through write and readback; do not silently trim, case-normalize, or
  reassign it.

Use `setspn -S` (or an equivalently uniqueness-preserving AD operation), suppress
its value-bearing output, and verify with `Get-ADUser ... -Properties
servicePrincipalName`. `setspn -A`, blind `Set-ADUser -Add`, and write-without-
readback are fail-open for uniqueness or evidence and are not acceptable.

Reconciliation is read-before-create and idempotent. An existing matching domain,
join, account, or SPN succeeds; an existing conflicting one fails rather than
being deleted, renamed, moved, or reassigned. Destroy remains reconstructive:
GCE teardown removes the range-local directory with its guests and deletes every
deterministic domain/account/DSRM secret. No external directory is mutated or
adopted by this issue.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration and public contract | ADR-024, ADR-031, ADR-032, `aces-domain-topology-preflight-1606.md`, released ACES 0.23 models/planner | Keep ACES authoring, normalization, topology references, and profile semantics upstream-owned. Do not extend CyberScript or create a Shifter SDL. |
| Package/source trust | `cms.scenarios.pack_validation`, `shared.aces.sdl_validation`, `shared.aces.object_source`, `shared.aces.package_loader` | Preserve path containment, bounded extraction, canonical digest binding, single-entry selection, and ACES validation before planning. Domain metadata outside the digested SDL is prohibited. |
| Capability declaration | `shared.aces.manifest`, `render_shifter_backend_manifest_payload()`, `backend-manifest.json` | Keep one generated manifest. Publish `active_directory` and `spn` only with the realized effect and evidence in the same change. |
| Independent realization gate | `shared.aces.composition_envelope`, `shared.aces.realization_ledger`, `shared.aces.domain_topology`, `shared.aces.runtime_target` | Reuse the one pure `validate()`/`apply()` path and the declaration-versus-evidence split. Add backend combination/value policy there; do not fork validation between validate and apply. |
| Transport and persistence | `serialize_provisioning_plan`, ADR-032-R3/R7, `engine.Range.range_config` | Carry the public payload and dependency edges in the existing versioned envelope. Add no topology DTO/table/event/dispatch payload. |
| Product authorization | `create_aces_native_range` and its ownership, launchability, reservation, active-range, audit, and feature-flag helpers | Add no endpoint, permission, or alternate launch service. Authored authority is never product authorization. |
| Dispatch workflow | `CmsAcesDispatchPort`, `engine.services.create_aces_range`, `engine.launch_intents`, GCP task runner, Kubernetes provisioner-job admission | Keep `aces-range <operation> --request-id <uuid>` and the canonical env/arg allowlists unchanged. No topology, SPN, or credential enters a task argument or env override. |
| Separate consumer boundary | `aces_plan.parse_plan`, `AcesPlanError`, `aces_plan_types`, `test_plan_provisioner_parity.py` | Add only a bounded process-local projection of the public topology carrier, including dependency edges and account address/domain reference. Repeat shape, profile, cross-reference, cardinality, OS, connectivity, account, and SPN policy before cloud mutation. |
| GCE realization | `aces_gcp_plan`, `aces_gcp_apply`, `RangeCellPlan`, existing `_ensure_*` primitives and reconstructive cleanup | Keep neutral GCE resource creation. Domain work is a verified post-boot phase, not Terraform, GCE labels, startup metadata, or a new provider workflow. |
| Local account realization | `aces_composition`, `aces_gcp_composition`, `aces_account_credentials` | Preserve the local-account path only for accounts without domain bindings. Remove the SPN marker behavior from every reachable dialect and do not send domain accounts through local user/credential realization. |
| Secret lifecycle | `gcp_guest_secrets._read_or_create_secret`, deterministic ACES secret ids/delete helpers, `utils.crypto` | Extend the same read/create/delete and injectable-ops pattern. Scope authority, DSRM, and domain-account credentials by `(range_id, domain identity, account address/purpose)`, not by a member instance or username alone. Use separate authority and DSRM secrets, and derive opaque collision-resistant secret-id components rather than embedding domain names, account names, or SPNs in Secret Manager inventory. |
| Guest control plane | `executors.factory.build_guest_execution_context`, `GuestSSHExecutor`, provisioner-issued management key/host key, `SetupOrchestrator`, `SetupStep` | Use private-IP SSH with strict host-key checking, readiness/reboot handling, retries, masking, and verification. Harden this incumbent rather than adding an SPN-specific executor: its current template renderer places context values in script text and `GuestSSHExecutor` appends `stdin_input` to the same PowerShell program, so neither is a separate credential-data channel. The guest receives no Secret Manager identity. |
| AD guest operations | `plans.dc_setup.DCSetupPlan`, `plans.domain_join.DomainJoinPlan`, and their tests | Reuse and harden the existing promotion/join plan mechanics rather than copying their workflows. Inject per-domain credentials and exact identity checks. Do not call legacy `_run_dc_setup`/`instance_orchestrator`: those own CyberScript role/XDR/RDP behavior, first-DC inference, `DC_DOMAIN_PASSWORD`, and value-bearing logs. |
| SPN/account operation | Existing `SetupPlan`/`SetupStep` convention and `SetupOrchestrator` | A bounded verified AD-account/SPN plan is the appropriate existing extension point. Do not put this behavior in the startup-script renderer or cloud resource layer. |
| Errors and logs | ACES `Diagnostic`, `AcesPlanError`, `AcesGcePlanError`, `SetupError`, `shared.log_sanitize`, provisioner `log_redact`, setup sensitive-context masking | Use the existing exception layers and wrap guest/provider failures at the ACES boundary into stable value-free stages. Do not introduce a parallel exception hierarchy or expose raw command/provider text. |
| Operational evidence | `aces_snapshot.snapshot_resources`, `events.publish_aces_*`, `shared.schemas.aces_operation`, `shared.aces.operations`, `shared.aces.projections` | Keep snapshots/status topology-address-only. Successful apply may be published only after directory readback; do not add identities, SPNs, usernames, secret refs, or command output to sidecars. |
| Live cutover evidence | `run_aces_backend_validation`, `cms.aces.validation`, `aces-cutover-evidence-1264.md` | Exercise the normal launch path with an explicit domain/SPN validation package. A succeeded operation is evidence only because provisioner success is now downstream of DC/join/SPN readback. |
| Architecture enforcement | `.importlinter`, `scripts/check_layer_imports`, `scripts/adr_guard`, manifest/conformance/parity tests, secret/static checks | Keep every current boundary and guard enabled; only `shared.aces`/tests import ACES tooling. |

## Cross-Cutting Layers The Design Must Pass

### Security, Validation, And Trust Boundaries

1. **Authentication and launch authorization.** No auth surface changes. CMS
   session/API policy, ownership, active-range, launchability, reservation, and
   audit checks remain authoritative. An ACES authority account grants authority
   only inside the isolated range directory.
2. **Package acquisition.** Repo and object packages retain containment, size,
   safe-extraction, immutable identity, and digest checks. A domain/SPN sidecar
   outside the canonical SDL digest is rejected.
3. **ACES shape validation.** `aces_sdl.identity_domains.IdentityDomain`, typed
   domain relationships, `Account.domain_ref`, DNS/NetBIOS validators, and the
   account model own authored shape. Shifter adds no second authoring schema.
4. **ACES semantic/profile validation.** The processor/planner and
   `domain_topology_plan_diagnostics()` own references, consistent bindings,
   authority anchoring, controller dependencies, account/node agreement, and
   profile membership. Shifter preserves diagnostic codes/addresses but replaces
   value-bearing messages.
5. **Backend effect policy.** The shared pure admission path additionally checks
   the supported profile/OS/cardinality/connectivity combination, authority
   credential policy, domain-account versus local-account semantics, AD account
   portability/uniqueness, and SPN shape/uniqueness. It covers resources and
   CREATE/UPDATE operations, deduplicates diagnostics, and returns no serialized
   plan on error; DELETE/no-op semantics remain unchanged.
6. **Dispatch and persistence.** Rejection occurs before the dispatch port,
   `Range.range_config`, receipt, task launch, secret creation, or GCE mutation.
   Accepted authored identity values persist only inside the existing serialized
   plan; no model migration or evidence record is added.
7. **Launch-intent and Kubernetes admission.** The request-id-only command,
   pinned image, service account, env allowlists, read-only/non-root container,
   bounded memory-backed workspace, and admission-policy parity remain unchanged.
   Do not add `DC_DOMAIN_PASSWORD`, a domain name, SPN, plan body, or secret ref
   to argv/env/workflow output.
8. **Provisioner parser.** The separate deployable repeats envelope version,
   payload shape, dependency, identity, profile, reference, combination, and
   value checks before `_ensure_*`, Secret Manager, SSH, PowerShell, or guest
   mutation. A persisted pre-0.23 plan cannot acquire an implicit domain, and an
   SPN without explicit valid topology remains rejected.
9. **Image/network boundary.** Controllers must resolve to Windows Server images
   on which AD DS can be installed and the management channel survives promotion.
   Members and controllers must be reachable under the actual primary-subnet and
   GCE firewall model; authored topology does not imply network connectivity.
   Guest capability/readiness is verified and failure is closed, never guessed
   from `os_family` or image naming.
10. **Secret store and IAM.** The provisioner reuses its existing Secret Manager
    admin boundary for deterministic per-range secrets. Range guests have no
    secret-store access. Authority, DSRM, and service-account passwords never
    enter SDL, `range_config`, GCE metadata/labels, instance outputs, snapshots,
    events, audit rows, config, or shared environment. Secret identifiers are
    opaque deterministic derivatives of plan addresses/purpose; they do not
    repeat authored domain, username, or SPN values in cloud inventory.
11. **OS/process exposure.** Authored identity and in-memory credentials reach a
    guest only through the existing pinned management SSH channel. Password
    values are runtime data on a distinct stdin/parameter channel; they are not
    rendered into PowerShell source, process argv, environment, a provisioner or
    guest temp file, GCE startup metadata, or a reusable command document. The
    current `SetupOrchestrator` template path does not provide that property and
    must be hardened at the common executor/orchestrator seam before passwords
    use it. A member never receives the reusable RID-500 authority password.
    Instead, the controller creates an opaque, machine-scoped `djoin` package;
    the provisioner carries it only through a dedicated no-log in-memory result
    path and the pinned stdin channel. Windows requires that package at a file
    path while applying `/requestODJ`, so the member writes it to a randomly named
    transient file, removes it in `finally`, and receives no reusable domain
    authority. An SPN passed to `setspn` is a non-secret directory identifier that
    is necessarily visible in that guest child process's argv; it remains bounded
    and quoted, while passwords never share that exposure.
12. **Guest verification.** Promotion, reboot/reconnect, DNS, join, domain account,
    uniqueness-preserving SPN registration, and AD readback are mandatory
    effects. Every script is idempotent, emits fixed stage tokens only, suppresses
    value-bearing cmdlet/executable output, and converts failures to bounded
    stage errors. After first-controller promotion, reconnect may switch from the
    pre-promotion `aces` login to the verified domain Administrator, but it must
    keep the provisioner-issued key and pinned host key rather than fall back to
    trust-on-first-use or password SSH.
13. **Error envelopes and logs.** Setup masking is defense in depth, not
    permission to print values. Domain DNS/NetBIOS names, SPNs, usernames,
    passwords, raw commands, provider exceptions, and command output do not enter
    diagnostics/logs/status reasons. `safe_log_value` prevents log injection but
    is not confidentiality redaction; `aces_range_ops` forwards `str(exc)` into
    failure events, so the exception crossing that boundary must already be
    bounded and value-free, with suppressed chaining.
14. **Observability/evidence.** Request-id fingerprint, stable diagnostic/failure
    code, coarse stage, plan address, and status are sufficient. Runtime snapshots
    and API projections remain free of directory inventory. Live validation proves
    the effect by making READY depend on in-guest directory readback, not by
    publishing that readback.

### Configuration, Persistence, And Workflow Shapes

- `SHIFTER_ACES_NATIVE_PROVISIONING` stays the only feature flag and defaults
  off. Add no env-manifest entry, Terraform variable, Helm value, Kubernetes
  Secret, provider selector, or workflow input.
- `Range.range_config` remains the sole persisted authored-plan surface; GCE
  resources plus deterministic Secret Manager entries remain the backend state.
  Add no repository/model/migration, sidecar kind, event type, or output schema.
- Provisioner IAM already supports dynamic ACES guest secrets. Do not widen
  guest IAM or grant a controller/member access to Secret Manager.
- The checked-in backend manifest remains generated. The existing local/ECS/GCP
  request-id dispatch and provisioner-job admission grammar remain unchanged.
- Cleanup keeps the current apply-failure/destroy path and reconstructs secret
  identities from the plan. Reconciliation reads existing secrets and guest/AD
  state rather than rotating credentials or recreating principals.

## Extensibility Seam

The seam is the stable **domain identity/address** from the public compiled plan.
Build a process-local domain realization view keyed by that identity, with an
ordered controller-address collection, member instances, authority account
address, and domain-account addresses. Guest operations receive that view plus
the current range and concrete instance outputs; secret operations receive the
domain/account identity and purpose.

Do not parameterize on a global boolean, first node, first DC, hostname suffix,
image key, username, member instance, or `DC_DOMAIN_PASSWORD`. One controller per
domain is an explicit initial policy check, not a singleton data model.

This seam permits the next reasonable changes—multiple controllers with
replication/failover, Linux domain members, multiple independent domains,
external authority adapters, and later trust/forest relations—without replacing
the ACES plan transport, secret namespace, dispatch grammar, or guest executor.
Those changes widen a domain-keyed adapter/policy; they do not add another
authoring or persistence contract.

## Whole-Repo Scope

The implementation must evaluate changes against:

- ADR-024, ADR-031, ADR-032;
  `aces-migration-parity-inventory.yaml`;
  `aces-backend-manifest-realizability-preflight-1563.md`;
  `aces-account-credentials-preflight-1560.md`; and
  `aces-domain-topology-preflight-1606.md`;
- the pinned ACES packages in `shifter/shifter_platform/pyproject.toml` and
  `uv.lock`, especially public account-feature extraction and domain-topology
  diagnostics;
- `shared/aces/manifest.py`, `backend-manifest.json`, `domain_topology.py`,
  `composition_envelope.py`, `realization_ledger.py`, `runtime_target.py`,
  `sdl_validation.py`, and `package_loader.py` plus their manifest, topology,
  RuntimeTarget, conformance, real-plan, and producer/consumer parity tests;
- `cms/services/_aces_range_create.py`, `cms/aces/dispatch.py`,
  `engine/services/_aces_range.py`, `engine/launch_intents.py`, GCP task-runner
  code, and `engine.Range.range_config` as unchanged product/dispatch boundaries;
- `aces_plan.py`, `aces_plan_types.py`, `aces_composition.py`,
  `aces_gcp_composition.py`, `aces_gcp_plan.py`, `aces_gcp_apply.py`,
  `aces_account_credentials.py`, `gcp_guest_secrets.py`, `aces_range_ops.py`,
  `aces_snapshot.py`, `events.py`, and their provisioner tests;
- `executors.factory`, `GuestSSHExecutor`, `SetupOrchestrator`, `SetupStep`,
  `DCSetupPlan`, and `DomainJoinPlan` as the guest-control incumbents;
- `shared.schemas.aces_operation`, `shared.aces.operations`,
  `shared.aces.projections`, `cms.aces.validation`, and
  `run_aces_backend_validation` as unchanged redacted evidence/read boundaries;
- `config/_aces_settings.py`, `config/env-manifest.json`, installation runtime
  inventory, GCP IAM, task env allowlists, and both base/Helm copies of the
  provisioner-job admission policy as unchanged host/config surfaces; and
- `.importlinter`, `scripts/check_layer_imports/**`, `scripts/adr_guard/**`,
  secret scanning, static analysis, and existing quality workflows.

## Gotchas And Anti-Patterns

- Remove the Linux `/etc/aces/spn/<user>` and Windows
  `C:\ProgramData\aces\spn\<user>.txt` behavior from every reachable path. Do
  not preserve it as fallback, debug evidence, or a second local copy.
- Do not create both a local account and an AD account for one domain-bound
  placement. The same username in two authorities is two principals, not parity.
- Do not treat `domain_ref`, topology carriage, DC promotion alone, account
  creation alone, `setspn` exit zero, or snapshot echo as SPN realization.
- Do not advertise `spn` without `active_directory`, add either declaration
  without the independent ledger entry/effect, or derive the ledger from the
  manifest.
- Do not copy upstream topology validation into the platform. Shifter's extra
  policy is only the backend effect subset; the separate provisioner repeats the
  minimum checks required at its trust boundary and is pinned by parity tests.
- Do not use `DCConfig`, `DomainSpec`, `ForestSpec`, `role="dc"`,
  `join_domain: true`, first-DC selection, or legacy instance setup as ACES intent.
- Do not call legacy `_run_dc_setup`: it reads process-wide
  `DC_DOMAIN_PASSWORD`, mixes XDR/RDP/participant behavior into DC setup, and logs
  authored identity. Reuse the lower setup-plan/executor mechanics with injected
  domain-scoped state.
- Do not reuse one credential for DSRM, authority, service accounts, member
  joins, management SSH, RDP, or participants. Their scopes and lifecycles
  differ. In particular, never deliver the RID-500 authority password to a
  member; use a machine-scoped offline-domain-join package.
- Do not key a domain account secret per member instance. `count` fans out
  machines; it must not silently fan out a single directory principal.
- Do not embed domain ids/names, account addresses/usernames, or SPNs in new
  Secret Manager ids or labels. Deterministic cleanup needs a stable opaque key,
  not a reversible identity inventory.
- Do not put a credential in PowerShell argv, `Start-Process -ArgumentList`, GCE
  metadata, an env var, a temp script, Terraform, a Kubernetes Secret, or command
  output. Do not render it into a PowerShell script body either: stdin-fed script
  text can still be captured by PowerShell script-block logging. Quoting prevents
  injection; it does not change exposure classification.
- Do not reuse local `groups`, `disabled`, `shell`, `home`, or `publickey`
  realization for a domain-bound account. Each requested term needs verified AD
  semantics or a pre-dispatch rejection for that combination.
- Do not accept local-only `groups`, `shell`, or `home` effects on the authority
  account; promotion and RID-500 reconciliation do not realize those effects.
- Do not log successful `Get-AD*`/`setspn` output. Existing setup orchestration
  logs stdout/stderr after masking only recognized secrets, and internal domain
  identity is not automatically masked.
- Do not accept "already a DC" or "already joined" without verifying the exact
  intended domain. Do not overwrite a conflicting SPN owner during retry.
- Do not infer that authored networks provide AD reachability. The ACES GCE path
  places a node on its primary network and base ingress is intra-subnet; validate
  the actual controller/member path before mutation.
- Do not assume the management `aces` account or host key survives DC promotion.
  Preserve and live-test strict host-key reconnect across every required reboot.
- Do not expose domain credentials through the existing portal/Guacamole secret
  readers merely because the provisioner stores them in the same cloud service.
- Do not add a new exception hierarchy, event bus, status enum, repository,
  command, workflow, flag, or runtime setting.

## Non-Goals And Implementation Boundaries

- No external/customer AD integration, cross-range directory, forest/child
  domain, trust, replication, multi-controller failover, site, OU, GPO, LDAP API,
  certificate service, keytab export, or general Kerberos client configuration.
- No Linux DC/member realization in this slice. Such a plan fails before
  dispatch; there is no marker or best-effort local fallback.
- No participant-role mapping, portal/Guacamole credential brokerage, credential
  reveal/recovery/rotation UI, or generic secret retrieval API.
- No new SDL, package metadata, API schema, database model/migration, event or
  snapshot field, config/env binding, Terraform/Kubernetes object, cloud
  permission, CLI argument, workflow, or cutover.
- No modification of CyberScript hydration, `RangeSpec`/`InstanceSpec`, or legacy
  domain authoring semantics. Compatible guest setup mechanics may be hardened
  and reused without making the legacy schema an ACES contract.
- No claim that #1561 realizes unrelated `mail`, shell/home semantics for domain
  accounts, arbitrary auth methods, external directory availability, or every
  future `active_directory` topology combination.

## Evidence Bar

Capability movement requires all of the following classes of evidence:

- real ACES 0.23 compilation and producer/consumer parity for topology bindings,
  dependency edges, account addresses/domain refs, and SPNs;
- negative admission/parser cases for absent/conflicting topology, unsupported
  OS/cardinality/connectivity/account combinations, old plans, malformed or
  duplicate SPNs, and manifest/ledger drift;
- setup-plan/orchestration tests proving quoting, secret-on-stdin behavior,
  ordering, reboot/reconnect, idempotency, uniqueness failure, exact AD readback,
  cleanup, and value-free errors/logs/events; and
- a normal product-path live validation on GCE whose READY transition is
  downstream of controller, member-join, account, SPN, and readback success, with
  unconditional teardown.

For this architecture-only change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```
