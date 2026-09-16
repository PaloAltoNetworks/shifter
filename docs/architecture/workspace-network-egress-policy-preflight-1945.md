# Workspace Network Egress Policy Preflight

Issue: GitHub #1945. Requirement: PLAT-238.

This note records architecture constraints for the workspace-level zero-egress
slice. It does not implement the requirement and is not an implementation plan.

## Decision boundary

There is one provider-neutral egress vocabulary:
`installation.range_egress.RangeEgressMode`. A workspace selector uses the
contextual subset `status-quo | none`; the effective range value uses the full
canonical vocabulary after resolution. These are two meanings of one enum, not
two enums or policy DTOs. `status-quo` inherits the normalized deployment mode
(including a deployment-wide `none`), while `none` is an explicit override. A
workspace does not own a copy of `RangeEgressPolicy`, deployment-global CIDR
allowlists, provider fields, routes, or firewall rules. This distinction matters
because an empty allowlist, missing provider resource, or false feature flag
must never be interpreted as zero egress.

The compatibility default is `status-quo`. A policy change affects launches
linearized after that change and never mutates a running range. At launch, the
single CMS workspace-admission seam resolves the workspace selector against the
validated deployment baseline while holding the same workspace-row mutex used
for launch reauthorization and policy mutation. The resulting closed
`RangeEgressMode` is pinned on the Engine range, verified on idempotent replay,
and delivered in the exact operation-generation input. The provisioner never
queries mutable workspace state.

The current cyberscript and RAES create paths call `admit_workspace_launch`
before `_reserve_active_range_slot`, while the latter owns the transaction that
reauthorizes under the workspace row lock. Merely adding a policy read to the
existing pre-reservation call is therefore racy. The authoritative verdict must
be produced and returned by the locked reservation/admission transaction; the
earlier call may remain only a non-authoritative pre-check. Both create paths
then pass that same returned value to Engine. They must not independently
re-read or re-resolve it after the lock is released.

The enforcement invariant applies to participant range subnets:

- AWS `none` keeps the existing range Terraform seam and creates no participant
  `0.0.0.0/0` route, NAT target, Internet Gateway path, or accidentally
  reachable service endpoint.
- GCE `none` creates no external interface and no Cloud NAT configuration that
  names the range's participant subnets. Per-range target-tagged egress deny is
  required defense in depth, but it is not evidence that a subnet has no NAT
  path.
- A non-`none` GCE range retains the existing native Cloud NAT behavior through
  explicit subnet-scoped NAT ownership in the GCE range-cell provider seam.
  Workspace code never edits Google resources directly.

The current GCP stable range VPC uses
`source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"`. That is
incompatible with the acceptance criterion: a firewall deny can block traffic,
but the subnet is still enrolled in NAT. The GCE range-cell network plan must
therefore own an explicit NAT-eligibility decision and the corresponding native
resource lifecycle. The current `vpc-per-range` option is not a shortcut: it has
no provisioner reachability path and cannot replace the default shared-VPC path
without a separate reachability design.

For `none`, the range-cell plan also suppresses every participant egress lane
that the current GCE profile/config can otherwise enable: public-web profile
egress, configured egress CIDRs, and participant-tagged Private Google Access.
An externally addressed per-range access gateway is an ingress/management edge,
not a participant guest and not proof of zero egress. It may remain only when
conformance proves it cannot route or NAT participant-originated internet
traffic and its forwarding is limited to the existing exact access target;
guest iptables is never the controlling egress mechanism. DNS, NTP, package,
agent, and provider-service paths need the same explicit participant versus
management classification on both clouds.

Removing the shared all-subnet NAT is a coordinated migration. Existing active
GCE ranges must either have equivalent explicit NAT attachment before cutover or
be drained; otherwise compatibility ranges lose egress. Conversely, retaining
the all-subnet NAT through cutover makes every new `none` range non-conforming.
The rollout must not expose either mixed state. A range-owned Cloud Router/NAT
shape is preferable to concurrent per-launch mutation of one Terraform-owned
NAT object, but its regional router/NAT/address quotas and cleanup behavior are
a release gate. If those quotas do not support the declared range capacity, the
architecture decision must be revisited before coding rather than hidden behind
a firewall-only approximation.

Normal participant launches already reject the GDC VM Runtime backend under
ADR-030. PLAT-238 must not weaken that gate. A future backend admitted for a
workspace-bound launch must either declare and prove native `none` support or
fail admission before reservation; it may not silently substitute its default
egress behavior.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Policy vocabulary and deployment baseline | `shifter/installation/range_egress.py`, `loader.py`, `render.py`, `runtime_inventory.py`, `runtime_inventory_gcp.py`, `config/_runtime_env.py`, and `config/env-manifest.json` | Reuse `RangeEgressMode`, root-config validation, sanitized issues, provider bridge rendering, and runtime-shape parity. Do not create another policy DTO or mode parser. The existing provisioner `RANGE_EGRESS_MODE` is not the CMS baseline binding. |
| Workspace persistence and authorization | `workspaces.models.Workspace`, `workspaces.roles.ROLE_OPERATIONS`, `workspaces.services._memberships._lock_workspace_and_actor`, lifecycle projections/errors | Store one closed scalar with a database constraint and compatibility default. Add one explicit update operation for owner/admin; never compare roles in a view or SPA. Personal workspaces remain policy-capable. |
| Workspace API | session-only lifecycle endpoints, explicit DRF serializers, `shared.api.errors`, committed OpenAPI and generated frontend types | Use bearer-first authentication, active-session/CSRF enforcement, opaque tenant denial, exact request fields, and the standard error envelope. Do not add a writable `ModelSerializer`. |
| Launch resolution | `cms.services._range_workspace`, `_reserve_active_range_slot`, cyberscript and RAES create facades | Extend the one admission verdict. The authoritative policy read occurs under the workspace lock and both launch families consume the same returned scalar. |
| Immutable range ownership | Engine `Range`, `engine.services._range`, RAES create service, replay binding checks | Persist the effective mode in the range-create transaction before dispatch and reject a replay with a different decision. Keep it beside, not inside, scenario/RAES contracts. |
| Provisioner delivery | `engine.launch_intents`, `engine.operation_inputs`, `shared.operation_envelope`, `provisioner_db_operation_input` | Add the scalar to both range operation-input families, validate it through the canonical enum, select by exact operation ID, and fail closed on absence/mismatch. |
| AWS realization | `terraform_vars.py` and `engine/provisioner/terraform/modules/range` | Parameterize the existing Terraform bridge from the pinned input. Preserve its direct `allowlist`/`none` validation and endpoint/route suppression. |
| GCP realization | `gcp_range_cell_plan`, `gcp_range_cell_firewall`, `gcp_range_cell_resources`, apply/destroy clients, and `platform/terraform/gcp/modules/range/vpc` | Extend the existing range-cell plan/resource lifecycle with native, explicit subnet NAT eligibility. Keep target-tag firewall denial as defense in depth and remove the incompatible all-subnet enrollment only through a safe cutover. |
| SPA | organization workspace policy route placeholder, central capability surfaces, `frontend/src/api/client.ts`, TanStack Query conventions | Replace the existing placeholder, use server-derived capabilities and generated contracts, preserve same-origin CSRF, and keep mutation retries disabled. |
| Audit and logging | `shared.audit`, workspace audit context, `shared.log_sanitize`, provisioner `log_redact` | Strict-audit successful changes with old/new modes and request attribution; log bounded decisions and internal correlation only. No-op writes produce no audit event. |
| Documentation publication | `docs/adr/documentation-coverage.yaml`, user/technical documentation indexes, ADR-017/026/046 | Publish the user-visible default/semantics and the cross-cloud realization/migration boundary through the existing coverage manifest; do not treat this preflight as the shipped feature documentation. |

The workspace projection may expose the non-secret mode to members already
authorized to read that workspace. Mutation requires a dedicated centrally
mapped operation; navigation capability, staff status, an organization page,
or a role string is not authority. Archived-workspace behavior must reuse the
existing lifecycle rule rather than inventing a policy-only state machine.

## Cross-cutting security layers

1. **Identity and authentication.** Existing OIDC/Identity Platform validation
   binds the Django user first. The policy endpoint uses the incumbent
   `ApiTokenAuthentication`-before-`SessionAuthentication` ordering plus
   `IsAuthenticatedSession`, so platform tokens are not accidentally admitted.
   It is same-origin, session-cookie and CSRF protected; no policy or token is
   stored in browser storage.
2. **Authorization and tenant opacity.** The endpoint resolves a public
   workspace UUID and reauthorizes the new operation through
   `workspaces.services`. Unknown workspace, absent membership, and denied role
   remain the same opaque failure. The SPA's capability check is advisory.
3. **HTTP and domain shape.** An explicit serializer accepts one closed choice
   and rejects unknown keys. The service repeats the domain check with the
   canonical enum. Database choices plus a check constraint prevent legacy,
   admin, or direct-ORM writes from persisting a new vocabulary accidentally.
4. **Concurrency and persistence.** Policy mutation and launch resolution lock
   the same Workspace row. The locked result is persisted before asynchronous
   dispatch, and Engine replay compares it. A read before the lock is only a
   friendly pre-check and cannot become the provisioned decision.
5. **Configuration shape.** `settings.range_egress` remains the only
   operator-authored baseline. CMS needs its normalized non-secret mode through
   the canonical runtime renderer/settings binding so `status-quo` can inherit
   an existing deployment-wide `none` posture. Any binding change must update
   the runtime inventory, `config/env-manifest.json`, provider renderer parity,
   and direct validation. It must not create a second root YAML key or accept a
   raw unvalidated env value.
6. **Operation transport.** The mode is range realization state, not scenario
   content. It travels in the versioned, size-bounded operation envelope
   materialized for the exact operation generation. Legacy and RAES consumers
   use one canonical enum/parser; neither may use permissive `.get()` fallback,
   “latest by request,” or a direct workspace/database read. Requiring a new
   exact-key payload field is an ADR-043 contract change: new generations use an
   explicit contract version that requires the mode, while retained pre-cutover
   generations remain compatibility-only during the declared rolling window.
   Do not make the field optional or synthesize a default to avoid versioning;
   absence or mismatch in the new version fails before provider mutation.
7. **OS and job exposure.** Keep process argv limited to the existing
   request/range and operation UUIDs. The mode does not belong in per-launch
   argv, shell interpolation, Kubernetes Job env, provider labels, events, or
   guest metadata. Terraform receives it through the existing staged variables
   object; GCP receives it through the in-process range-cell plan. Avoiding a new
   Job env also avoids widening the provisioner env inventories and admission
   allowlists.
8. **Secret boundary.** Modes and CIDRs are non-secret policy, but agent URLs,
   cloud credentials, kubeconfigs, VPN material, and secret references remain
   on their existing Secret Manager/Kubernetes Secret paths. Zero-egress must
   suppress runtime dependencies on those external services rather than copying
   credentials or signed URLs into a guest as a workaround.
9. **Provider validators.** AWS Terraform variable validation remains a direct
   backstop. The GCE plan must validate the closed mode before producing Cloud
   NAT/firewall resources, and provider create/destroy remains idempotent and
   ownership-scoped. Cloud-native state, not an application log, proves the
   route/NAT invariant.
10. **Errors and observability.** Workspace command errors reuse the classified
    workspace error path and `shared.api.errors`; CMS uses `CMSError`; operation
    input and provider failures keep their existing bounded classifications.
    Public bodies, events, and notifications never include raw SQL, provider
    responses, CIDR inventories, or exception strings. Audit records old/new
    mode; logs use request/range IDs, stable codes, and sanitized fingerprints.

Validation evidence must cover the database default/migration, session/token and
role matrix, unknown fields, mutation-versus-launch locking, both launch
families, Engine replay, both operation-input parsers, provider plan/apply/destroy
idempotency, and compatibility behavior. Cloud conformance additionally proves
AWS route-table and GCP Cloud NAT state, then probes from inside a `none` range
that external IP/domain lanes (including previously allowed service lanes) are
unreachable. GCP firewall denial alone is not sufficient evidence.

## Extensibility seam

The extension parameter is a closed effective `RangeEgressMode` on
`WorkspaceLaunchAdmission`, persisted on Engine Range and projected into the
operation input. Provider adapters map that value to native route/NAT/firewall
plans. This permits a later workspace allowlist/profile decision to extend the
canonical policy resolver without adding workspace identity to provider code or
editing both launch families. It does not pre-authorize workspace-owned CIDRs;
that future shape needs its own persistence, authorization, migration, and
cross-provider decision.

Each registered range backend should expose a closed egress-capability mapping
(`none` supported or denied) beside the existing backend/purpose admission seam.
A future provider or substrate then changes one mapping and supplies conformance
evidence instead of growing scattered provider conditionals.

## Gotchas and anti-patterns

- Do not model `none` as an empty allowlist, `deny-all`, disabled firewall, or
  missing endpoint. Those postures have different route/NAT semantics.
- Do not put the full `RangeEgressPolicy` in a Workspace JSON field, role,
  scenario/RAES artifact, provider tag, or duplicate frontend enum.
- Do not read the workspace in Engine/provisioner code or reread the mutable
  setting during retry. Pin once and replay-verify.
- Do not enforce only in the SPA, only in the provisioner, or separately in the
  cyberscript and RAES launch functions.
- Do not make the existing pre-reservation `admit_workspace_launch` call the
  policy linearization point; it currently runs before the workspace-locked
  reservation transaction.
- Do not add a required key to the version-1 operation payload in place. Queued
  and replayable inputs require the ADR-043 rolling contract window, and the new
  contract must still fail closed when its mode is absent.
- Do not pass the mode in argv or add a per-range env override. In particular,
  the deployment-owned `RANGE_EGRESS_MODE` must not remain authoritative after
  an effective range decision has been pinned.
- Do not claim GCP no-NAT while the stable NAT remains
  `ALL_SUBNETWORKS_ALL_IP_RANGES`; a target-tagged firewall does not change NAT
  enrollment.
- Do not patch one Terraform-owned Cloud NAT concurrently from range Jobs, and
  do not remove it before compatibility subnets have a replacement.
- Do not switch `none` ranges to `vpc-per-range` without solving and validating
  provisioner, management, and remote-access reachability.
- Do not leave profile web egress, configured CIDRs, Private Google Access,
  public DNS/NTP, S3/SSM/STS/Bedrock, or a forwarding VPN gateway reachable by
  accident. Classify each as participant, management, disabled, or replaced.
- Do not create a new exception hierarchy, audit store, query cache, API client,
  provider controller, or network filter for this slice.

## Non-goals and implementation boundaries

- Retroactively changing, restarting, or revoking egress from running ranges.
- Workspace-specific CIDR allowlists, proxies, DNS policy, billing, quota,
  provider placement, VPC/project/account tenancy, or organization inheritance.
- Replacing the deployment-global `settings.range_egress` baseline or weakening
  its AWS/GCP allowlist and deny-all behavior.
- Sharing range access with workspace members or changing individual range
  ownership, CTF authority, remote-access checks, or the backend-purpose gate.
- Treating portal/GKE/provisioner/runner egress as participant range egress.
- Approving GDC for live-fire or designing a GDC zero-egress realization.
- A guest-agent, iptables, sidecar, application proxy, Kubernetes NetworkPolicy,
  or other hand-rolled substitute for AWS/GCP native range-network controls.
