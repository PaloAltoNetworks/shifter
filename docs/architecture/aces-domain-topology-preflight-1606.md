# ACES Domain-Topology Expressivity Preflight

Issue: GitHub #1606, "feat: ACES domain-topology expressivity (DC role /
domain-join) to enable domain-backed account realization."

Status: implementation architecture record. This note documents the public
contract consumed by #1606 and the boundary it enforces. The GitHub issue is the
shipping contract for this requirement-free run.

## Boundary And Decision

Choose the **upstream public-contract option**. Domain identity, domain-controller
binding, and domain-join membership are authored scenario meaning, so they belong
in a released ACES vocabulary and its public semantic/capability gates. They do
not belong in a Shifter extension block, package sidecar, CMS schema, tag
convention, image registry field, or provisioner-only overlay.

The issue described the then-pinned `aces-sdl` 0.19.1 contract. Shifter now pins
the released compatible pair `aces-sdl==0.23.0` and
`aces-scenario-packs==2.0.1`, while the provisioner keeps the rolling read window
`[0.19.1, 0.24.0)` for persisted plans. ACES 0.23 carries the public
`identity_domains` authoring surface, typed `domain_controller_for` and
`joins_domain` relations, compiled `domain_topology` bindings, the
`supported_domain_profiles` capability, and
`domain_topology_plan_diagnostics()`. The released upstream contract therefore
closes the expressivity and validation gap without a Shifter dialect.

The released public contract carries, into the compiled `ProvisioningPlan`:

- a stable, plan-addressable domain identity with DNS and NetBIOS identity;
- an explicit binding between a declared node and the domain-controller role;
- an explicit join relation from a declared node to a specific domain, not a
  global boolean or "first DC" convention;
- unambiguous domain anchoring for a domain-scoped account. Node membership does
  not by itself make every account placed on that node a domain account. If the
  public contract uses placement target as that anchor, the rule must be
  explicit; otherwise the account needs a public domain reference; and
- public shape, reference-integrity, semantic-dependency, and conditional
  capability validation that a backend can invoke without importing private
  processor/reference-backend helpers. Shifter invokes the public topology
  diagnostic gate with its declared profile set; upstream semantic validation
  still owns implications such as "SPN requires a domain-anchored account in a
  realizable domain topology."

The existing `ProvisioningPlan.ordering_dependencies` and resource addresses are
the incumbent graph mechanisms. A released contract should preserve domain/DC/
join relations and their ordering dependencies through compilation; Shifter must
not reconstruct workflow from names after planning.

The backend-owned option is rejected for authored topology. Without an upstream
authoring surface, "explicit topology evidence" would have to come from a
Shifter-only YAML extension, package metadata, tag, database row, or config file.
Each is a parallel SDL or duplicate schema prohibited by ADR-024, ADR-031, and
ADR-032. A backend-owned seam remains appropriate later for concrete authority
credentials, provider resources, and guest execution, but it must be keyed by
the explicit public domain identity and cannot manufacture that identity.

`spn` stays absent from both
`SHIFTER_PROVISIONER_CAPABILITIES.supported_account_features` and
`REALIZED_ACCOUNT_FEATURES`. Parsing or carrying topology is not domain
realization, and topology evidence is not proof that a DC was promoted, a node
joined it, or an SPN was registered and read back. No domain-topology term may
be advertised or dispatched as supported until its public capability semantics
and genuine backend effects move together in the downstream realization issue.

## Concept Boundaries

- **Domain identity** is authored DNS/NetBIOS meaning. It is not an image name,
  hostname suffix, scenario id, username suffix, cloud DNS zone, or network.
- **DC role** is a relation between a node and a domain. It is not `os_family`,
  `node_type`, an image-registry match, or the legacy string `role="dc"`.
- **Join membership** names the domain a node joins. It is not a boolean and is
  not implied merely because the node shares a network with a DC.
- **Domain account identity** is distinct from local guest account placement.
  A joined node does not silently reinterpret all authored accounts as domain
  principals.
- **Authority credentials** are backend-owned secret material. DNS and NetBIOS
  names may be authored; domain-administrator passwords, DSRM credentials,
  Kerberos keys/keytabs, and generated account credentials may not be.
- **Observed identity inventory** under `Node.runtime.identity_authorities`
  describes participant-observable realized state. It is not DC-promotion or
  domain-join desired state and must not be reinterpreted as provisioning
  evidence merely because it is serialized inside a node payload.
- **Topology validation** proves explicit references and preconditions.
  **Realization evidence** proves the guest/domain effects. Neither substitutes
  for the other.
- Forests, child domains, trusts, replication, sites, organizational units, and
  directory-provider selection are later vocabulary. The domain reference seam
  must not prevent them, but #1606 must not smuggle them into a minimal contract.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration ownership | ADR-024 and `aces-migration-parity-inventory.yaml` | Classify this as an ACES schema/profile gap. Do not extend CyberScript or create a Shifter authoring dialect during the parallel migration. |
| Authoring and compilation | Released public `aces-sdl` models, processor, planner, public account-feature extractor, and public conformance APIs | Upstream owns syntax, normalization, references, dependency semantics, and conditional capability vocabulary. Do not copy models or private helpers. |
| Package/source validation | `cms.scenarios.pack_validation`, `shared.aces.sdl_validation`, `shared.aces.object_source`, and `shared.aces.package_loader` | Preserve containment, canonical digest binding, safe extraction, single-entry selection, and ACES parsing before planning. |
| Capability publication | ACES `ProvisionerCapabilities.supported_domain_profiles`; `shared.aces.manifest.SHIFTER_PROVISIONER_CAPABILITIES`, `render_shifter_backend_manifest_payload()`, and `shared/aces/backend-manifest.json` | Publish the one honest Shifter profile set and one generated artifact. It remains empty in #1606 because vocabulary consumption is not DC/join/SPN realization. Do not encode topology as an opaque Shifter constraint string or re-add `spn` prematurely. |
| Common admission | `shared.aces.runtime_target.interpret_provisioning_plan`, `_serialized_for_apply`, `composition_envelope`, and `realization_ledger` | `validate()` and `apply()` must share one pure fail-closed path. Reuse the independent declaration/evidence pattern; a manifest claim alone is not realization. |
| Transport/persistence | `serialize_provisioning_plan`, ADR-032-R3/R7, and `engine.Range.range_config` | Carry the public compiled payload verbatim in the existing versioned envelope. Add no topology DTO, table, sidecar, event, or dispatch payload. |
| Separate deployable boundary | `aces_plan.parse_plan`, `AcesPlanError`, and the bounded value objects in `aces_plan_types` | Revalidate envelope version, shapes, identities, references, and supported terms before mutation. A process-local projection is allowed only after that validation. |
| Product authorization | `create_aces_native_range` and the existing `_validate_*`, `_assert_*`, reservation, ownership, active-range, launchability, and audit helpers | Add no endpoint or permission path. A topology/capability declaration is never authorization. |
| Dispatch workflow | `CmsAcesDispatchPort`, `engine.services.create_aces_range`, `engine.launch_intents`, `engine.ecs`, and the request-id command grammar | Keep structured request-id-only dispatch and the existing state-authorized launch intent. |
| Errors and logging | ACES `Diagnostic`; `AcesPackageError`; `CMSError`; `AcesPlanError`; `shared.log_sanitize`; provisioner `log_redact` | Use stable, bounded, value-free errors and request-id fingerprints. Sanitizing control characters does not make a DNS name or credential safe to disclose. |
| Operational evidence | `shared.schemas.aces_operation`, `shared.aces.operations`, `shared.aces.projections`, and `aces_snapshot.snapshot_resources` | Keep sidecars status/topology-address only. Do not persist DNS/NetBIOS identities, credentials, plan bodies, or authority details as operation evidence. |
| Secret handling for later realization | `gcp_guest_secrets`, `shared.cloud` secret seams, and injectable provisioner operations | A future authority resolver extends the existing per-range secret discipline. The legacy process-wide `DC_DOMAIN_PASSWORD` environment binding is not an ACES credential seam. |
| Legacy domain behavior as prior art only | `cyberscript.schemas.range.DCConfig`, CTF `DomainSpec`/`ForestSpec`, `instance_orchestrator`, `DCSetupPlan`, `DomainJoinPlan`, and `SetupOrchestrator` | Reuse proven guest orchestration/executor patterns later where compatible. Do not import, translate into, or copy legacy authored schemas for the ACES path. |
| Architecture enforcement | `.importlinter`, `scripts/check_layer_imports`, `scripts/adr_guard`, ACES conformance, and existing shared/provisioner tests | Keep `aces_*` imports inside `shared.aces`/tests and every current guard enabled. |

## Cross-Cutting Layers The Design Must Pass

### Security, Validation, And Trust Boundaries

1. **Authentication and launch authorization.** No auth surface changes.
   Launch remains session/API-policy controlled through the existing CMS
   service, ownership, active-range, launchability, reservation, and audit
   checks. Authored topology and manifest capability never grant authority.
2. **Package acquisition.** Repo packs remain path-contained and digest-bound;
   object packs remain bounded, safely extracted, identity-checked, and digest-
   verified. A topology extension file outside the canonical pack/SDL digest is
   prohibited.
3. **ACES shape validation.** The released ACES schema owns DNS/NetBIOS shape,
   canonicalization, and field constraints. Shifter must not add a second
   Pydantic/dataclass authoring model or normalize the same values differently.
4. **ACES semantic validation.** Public upstream validation must reject missing,
   duplicate, ambiguous, or dangling domain/DC/join/account anchors and preserve
   dependency edges. `Node.runtime.identity_authorities`, generic relationship
   properties, and arbitrary feature/role names do not satisfy this gate.
   Inference from image, source, OS, username, network, or scenario identity is
   never a fallback.
5. **Backend-family admission.** The public planner and
   `domain_topology_plan_diagnostics()` must reject a profile outside
   `supported_domain_profiles`. Do not duplicate the public topology analyzer as
   Shifter-only constraint parsing. Capability membership does not replace
   semantic reference/implication checks.
6. **Backend validate/apply.** The one pure RuntimeTarget path must require the
   public topology evidence for every materializing domain-scoped feature in
   both resource and CREATE/UPDATE operation views, deduplicate diagnostics, and
   return no serialized plan on error. DELETE/no-op operations must retain the
   existing materialization distinction.
7. **Dispatch and persistence.** Rejection happens before the dispatch port,
   engine `Range.range_config`, operation receipt, task launch, or cloud/guest
   mutation. For accepted future terms, `range_config` remains the sole persisted
   authored-plan surface; no repository/model migration is needed.
8. **Launch-intent and OS process boundary.** Local/ECS/Kubernetes execution
   remains `aces-range <operation> --request-id <uuid>`, validated by
   `engine.launch_intents` and the Kubernetes admission policy. No topology,
   SPN, credential, serialized plan, or domain name belongs in argv, environment
   overrides, workflow output, or a second command payload.
9. **Provisioner parser.** The separate deployable repeats supported-version,
   resource-shape, identity, alias, and cross-reference validation before any
   `_ensure_*`, Terraform, SSH, SSM, PowerShell, or secret operation. A 0.19.1
   plan cannot acquire topology by default: a persisted plan requesting `spn`
   without explicit supported-version topology must fail closed before mutation.
   Older plans with no domain-scoped terms remain readable within the existing
   rolling window.
10. **Secret-handling surface.** #1606 needs no secret lookup or secret creation.
   Future authority credentials must be backend-generated/resolved, scoped to a
   range and explicit domain identity, stored in the existing secret provider,
   and passed through an injectable guest executor. They must never enter SDL,
   `range_config`, snapshots, events, audit state, logs, metadata, startup
   scripts, settings, or shared process-wide environment variables.
11. **Guest/OS exposure.** #1606 performs no DC promotion, DNS change, join,
    reboot, account mutation, or SPN command. A later realizer may reuse the
    setup orchestrator, quoting, masking, readiness, reboot, and verification
    patterns, but topology parsing alone must not render PowerShell or shell.
12. **Error envelopes.** Shared admission returns typed ACES diagnostics naming
    only a stable code, plan address, and governed relation/feature. It must not
    echo DNS/NetBIOS values, SPNs, usernames, credentials, or payloads. This is
    also required at the provisioner boundary because `aces_range_ops` currently
    copies `str(exc)` into logs and failure/status events; `safe_log_value`
    prevents injection but is not confidentiality redaction. Product callers
    keep the existing generic `CMSError` rejection.
13. **Observability and evidence.** Request id, stable diagnostic/failure code,
    stage, resource address, and coarse status are sufficient. Exact authored
    concern values required by a future public non-approximation check may exist
    only in the process-local `ApplyResult`; they must not be copied into the
    persisted runtime snapshot or API projections.

### Configuration And Workflow Shapes

- `SHIFTER_ACES_NATIVE_PROVISIONING` remains the only feature flag and stays
  default off. Add no topology/domain/SPN setting, env-manifest entry, Terraform
  variable, Helm value, Kubernetes secret, provider selector, or workflow input.
- The checked-in manifest remains generated from `manifest.py`; publication
  parity must stay byte-for-byte. Add no conditional-capability key the public
  ACES model/gate does not understand.
- The existing ACES package, topology diagnostics, producer/consumer parity,
  RuntimeTarget, provisioner parser,
  architecture, import, secret, and static checks remain the validation
  workflow. Do not add a parallel topology linter when the public ACES validator
  should own the rule.

## Extensibility Seam

The parameter is the stable **domain address/identity** carried by the public
compiled plan. DC bindings, join memberships, and domain-scoped accounts refer
to that identity; backend authority resolution later accepts that identity plus
the current range/instance context. Do not parameterize on a boolean, the first
DC, a hostname suffix, an image key, or a single global credential.

This supports the next reasonable changes without replacing the contract:
multiple domains in one range, multiple DCs for one domain, explicit account
domain selection, and later forest/trust relations. Those additions extend the
public graph around the same domain identity. They do not require re-editing a
Shifter singleton `dc_config`, widening a global environment variable, or
changing the serialized-plan/dispatch/persistence envelope.

The shared admission seam is the public ACES semantic validator plus
`ProvisionerCapabilities.supported_domain_profiles` and
`domain_topology_plan_diagnostics()`.
The common RuntimeTarget may add backend-effect checks that the public semantic
gate cannot prove, and the provisioner may reconstruct a bounded process-local
topology projection from the same serialized payload after validation. These
are trust-boundary views of one public contract, not authored schemas or a
second conditional-capability language. Version parity tests pin their
conventions to the released producer window.

## Whole-Repo Scope

The implementation must evaluate changes against:

- ADR-024, ADR-031, ADR-032, and
  `docs/architecture/aces-migration-parity-inventory.yaml`;
- the released ACES package pair in `shifter/shifter_platform/pyproject.toml`
  and `uv.lock`, including the public topology model, planner capability
  relation, and topology diagnostics;
- `shared/aces/manifest.py`, `backend-manifest.json`, `runtime_target.py`,
  `domain_topology.py`, `composition_envelope.py`, `realization_ledger.py`,
  `sdl_validation.py`, and `package_loader.py`;
- manifest publication, backend conformance, RuntimeTarget, package loader,
  real-plan, and producer/consumer parity tests under
  `shifter/shifter_platform/tests/shared/aces/`;
- `cms/services/_aces_range_create.py`, `cms/aces/dispatch.py`,
  `engine/services/_aces_range.py`, `engine/launch_intents.py`, `engine/ecs.py`,
  and `engine.Range.range_config`;
- `shifter/engine/provisioner/aces_plan.py`, `aces_plan_types.py`,
  `aces_composition.py`, `aces_range_ops.py`, `aces_snapshot.py`, `events.py`,
  and their tests;
- `shared.schemas.aces_operation`, `shared.aces.operations`, and
  `shared.aces.projections` as unchanged evidence boundaries;
- `cyberscript/schemas/range.py`, CTF `asset.py`/`forest.py`,
  `instance_orchestrator.py`, `dc_setup.py`, `plans/dc_setup.py`, and
  `plans/domain_join.py` as legacy prior art, not ACES contracts;
- `config/_aces_settings.py`, `config/env-manifest.json`, installation runtime
  inventory, task environment allowlists, and the Kubernetes provisioner-job
  admission policy as unchanged host/config surfaces; and
- `.importlinter`, `scripts/check_layer_imports/**`, `scripts/adr_guard/**`, and
  existing quality/security workflows.

## Gotchas And Anti-Patterns

- Do not implement `x-shifter-domain`, a second package manifest, a topology
  JSON blob, a CMS model, a tag convention, or a sidecar record around the
  released upstream contract. A temporary authored seam is still a parallel SDL.
- Do not repurpose `Node.runtime.identity_authorities` as desired topology. It
  is observed runtime inventory, lacks the required domain-provisioning
  relations, and is currently ignored by the provisioner's bounded
  `AcesPlanNode` projection.
- Do not encode DC/join semantics in generic `relationships.properties`, a
  feature name, a role label, or an arbitrary runtime identity relationship.
  Shape-valid opaque metadata is not a governed provisioning contract.
- Do not copy `DCConfig`, `DCConfigExt`, `DomainSpec`, `ForestSpec`, or their
  validators into `shared.aces`. They demonstrate legacy needs but are not the
  ACES compatibility contract.
- Do not use `join_domain: true`; it is ambiguous as soon as a range has two
  domains. Do not select the first DC or first network by list order.
- Do not infer DC/join/domain/account scope from `os_family`, node/source/image
  names, usernames, DNS suffixes, account `spn`, scenario/package ids, or
  placement on a shared subnet.
- Do not treat every account on a joined node as a domain principal. Local
  account realization and domain-account realization need an explicit public
  semantic distinction.
- Do not add `spn` to the manifest or evidence ledger merely because a parser
  can see topology. A marker file, snapshot echo, parsed relation, secret row,
  or rendered command is not SPN registration/readback evidence.
- Do not represent structural conditional support with an opaque manifest
  string or a second Shifter evaluator. The IPv4 constraint precedent is a
  scalar backend limitation; topology-aware scenario-family admission belongs
  in the public supported-domain-profile gate, while cross-resource implications
  and references belong in the public semantic validator.
- Do not let the rolling 0.19.1 reader interpret absence as an implicit default
  domain. Version compatibility permits reading old non-domain plans, not
  inventing evidence for old `spn` payloads.
- Do not log domain DNS/NetBIOS names or place them in failure events merely
  because they are not passwords. They disclose internal authored topology.
  `safe_log_value` is an injection sanitizer, not redaction.
- Do not reuse `DC_DOMAIN_PASSWORD` for ACES. A process-wide environment secret
  cannot safely represent per-range/per-domain authority and would expose one
  credential to unrelated operations in the same task.
- Do not add domain identity to runtime sidecars or API response allowlists.
  The serialized plan already persists authored intent; operational evidence
  remains bounded status/address data.
- Do not add a new exception hierarchy, event bus, status enum, repository,
  feature flag, CLI grammar, workflow, Terraform input, or Kubernetes object.

## Non-Goals And Implementation Boundaries

- No Shifter-owned domain authoring vocabulary or backend-owned bridge around
  the public ACES contract.
- No reinterpretation of ACES observed runtime identity inventory, generic
  relationships, roles, or features as provisioning intent.
- No DC promotion, directory/DNS/Kerberos deployment, domain join, reboot
  orchestration, domain account creation, SPN registration/readback, credential
  generation/rotation/recovery, or guest verification in #1606.
- No forest, child-domain, trust, replication, site, OU, group-policy, LDAP,
  directory-provider, or cross-realm vocabulary.
- No re-declaration of `spn`, topology realization, or any conditional
  capability without released public semantics and genuine realization
  evidence.
- No API/UI, auth scope, model/migration, operation record, snapshot schema,
  setting, env variable, CLI argument, Terraform/Kubernetes/cloud permission,
  workflow, or cutover change.
- No modification of CyberScript hydration, `RangeSpec`/`InstanceSpec`, legacy
  DC/domain-join behavior, or the default-off feature-flag posture.

For this architecture-sensitive implementation, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

The Shifter consumer is implemented against the released 0.23 contract. Genuine
domain-controller, join, domain-account, and SPN effects remain downstream work
for #1561 and must not widen the empty profile declaration before that evidence
exists.
