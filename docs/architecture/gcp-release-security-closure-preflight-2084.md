# GCP Exact-Release Security Closure Preflight (#2084)

Status: pre-implementation architecture guidance

Date: 2026-09-11

Issue: GitHub #2084, "security: reconcile the GCP release security gate to
deployed artifacts"

GEN-002 supplies the executable-governance constraint; issue #2084 is the
exact-release shipping contract. This note fixes the release, evidence, and
security boundaries before implementation; it does not remediate a finding,
run a scanner, deploy an artifact, change a cloud identity, or decide that the
release is ready.

The repository was inspected at `99e2a610271985d9072e37612e13f00943e28076`.
That is an inspection baseline, not the release revision or execution evidence.

## Boundary And Decisions

#2084 is one exact-release decision, not a repository alert burn-down and not a
new security platform. The release unit is the following bound set:

- one immutable source commit (and release tag when one exists);
- the four GCP OCI images built from it: portal, provisioner, guacd, and
  guacamole-client, identified by registry root and digest;
- the digests actually admitted by GKE and the image IDs reported by the
  running workloads;
- every GCE guest image in the selected release profile, identified by project,
  name, server-assigned numeric image ID, family/channel, build, validation, and
  promotion evidence; and
- only when GDC is selected, the exact exported qcow2 object generation and
  checksum. A GCE image, GCE family, qcow2 export, and OCI digest are different
  artifact identities and must never substitute for one another.

Use one reviewed Markdown closure record, following the pointer-layer contract
in `rev1-release-evidence-integration-preflight-1540.md`. It points to native
producer results and a restricted report where sensitive evidence is required;
it does not copy SARIF, SBOMs, provider payloads, reproduction steps, or logs.
No database model, API, DTO, service, workflow state machine, scanner
abstraction, or exception hierarchy is justified for this one release. Raw
guest SBOM, immutable guest build-source record, exact-image scan, and
running-image evidence do require one
bounded private GCS bucket because publishing those payloads as Actions
artifacts would disclose cloud inventory and vulnerability detail. The bucket
is retained infrastructure, not a queryable release database; public artifacts
carry only a redacted verdict, source revision, opaque locator, and digest.

The release verdict is fail-closed:

- scanner invocation success is not analysis success;
- an alert count is not an exploit count, and zero repository alerts is not
  proof that the deployed image or guest is clean;
- a missing, expired, inaccessible, wrong-SHA, wrong-digest, stale, ambiguous,
  or contradictory result is `unresolved`, not a pass;
- advisory signal remains advisory, but every finding relevant to the selected
  release still needs a reviewed disposition before release; and
- a release exception is a bounded decision about one affected artifact and
  finding. It never changes the scanner's result or erases the finding.

No new ADR is needed. ADR-003 and ADR-004 own CI and security enforcement,
ADR-037 owns OCI provenance and its explicit non-OCI VM-image boundary,
ADR-042 owns source-release identity, ADR-054 owns the dedicated-customer GCP
authority and evidence boundary, and ADR-004-R23 plus the #1699 preflight own
purpose-scoped GCP CI identities. If implementation weakens or changes one of
those durable policies, update its ADR and enforcement in the same change.

## Current-Tree Facts The Closure Must Not Hide

At the inspection baseline:

- `_quality.yml` waits for the Sonar quality gate only on pull requests.
  Protected-branch pushes and manual deploy dispatches run a full analysis but
  do not pass `sonar.qualitygate.wait=true`; `deploy.yml` can therefore observe
  a successful Quality job without an accepted Sonar analysis result.
- `codeql-analysis.yml` runs Python and JavaScript `security-extended`, but the
  analysis step is `continue-on-error: true`. Its workflow conclusion is not a
  finding-policy verdict and may also hide an upload/configuration failure.
- Trivy scans Dockerfile/IaC configuration with `--exit-code 0`; it does not
  scan the built OCI digests. OSV scans only the repository-root
  `package-lock.json`, also advisory, while the deployed images and repository
  contain additional Python, Node, OS, and tool dependency roots.
- Dependabot does not currently cover every uv root despite the documented
  every-package-root convention. It omits `scripts/assert_portal_inspection`,
  `scripts/handle_sd_replacement`, `uat/event-load-harness`, and
  `uat/range-functional-smoke`; all four have locked development dependencies,
  and the UAT roots also have runtime dependencies. The closure must inventory
  each actual manifest/lock root and establish its update and scan owner rather
  than infer repository coverage from one lock or updater configuration.
- `_gcp-dev.yml` does produce SBOM/provenance attestations for all four OCI
  images, verifies the exact repository/digests, pins the GKE overlay, and waits
  for rollouts. Those controls establish identity, not a vulnerability verdict.
  The closure must also read back the running workload image IDs/digests.
- No current GCE guest-SBOM producer was found. The #1343/#1699 build,
  validation, and promotion evidence binds guest identity and health, but it is
  not a package inventory. A release claiming guest-SBOM triage must close that
  gap for each shipped guest rather than relabel OCI provenance as VM evidence.
- `sonar-project.properties` contains global rule suppressions. In particular,
  its Docker digest-suppression rationale still describes floating-tag policy,
  while ADR-037 and all current Docker `FROM` lines require digests. Every
  suppression is review input; stale text or historical approval is not current
  false-positive evidence.
- The purpose-specific GCP service accounts and subject bindings exist in
  `cicd-oidc-identity`, but deploy and destroy still receive the same broad
  `platform_roles` list. Separate names/subjects do not by themselves prove
  least privilege. Terraform merge state also does not prove live WIF,
  Environment policy, secret cutover, or effective permissions.
- The source tree contains the #94 initiation/finalization bounds. That proves
  intended code shape only; the release still needs selected-SHA tests and a
  supported-GCP-path result before #94 can be treated as closed evidence.
- The GCP workflow writes bootstrap credentials to
  `platform/terraform/gcp/environments/<env>/local.auto.tfvars` on a
  self-hosted runner and builds a `kubectl create secret --from-literal=...`
  argv containing database and Guacamole secrets. The closure must remove or
  explicitly resolve these disk/process-list exposure paths; sanitizing logs
  does not make them safe.
- `config.views` logs raw user email on dashboard routing and logout, while
  upload/storage paths log object keys. `safe_log_value` prevents injection; it
  is not confidentiality redaction. These are explicit review targets for the
  release's supported logging paths.

## Exact-Release Evidence And Finding Dispositions

The public closure record identifies the release source SHA, logical GCP
environment/profile, deploy run and attempt, four OCI digests, guest artifact
fingerprints, and immutable native evidence locators. Exact live project names,
numeric provider IDs, raw alerts, package paths that expose topology, and
sensitive reproduction remain in a restricted report; the public record uses a
stable non-secret fingerprint and locator where disclosure is inappropriate.

Each Sonar issue/hotspot, CodeQL alert, dependency/CVE finding, IaC finding, and
historical issue claim relevant to the release gets its own row with:

- native tool/finding key and producer/tool version or database timestamp;
- exact source SHA and affected source path, lock root, OCI digest, guest-image
  fingerprint, or explicit non-runtime/build-only scope;
- the producer's real conclusion and blocking/advisory posture;
- one disposition: `fixed`, `reviewed-unaffected`, `reviewed-false-positive`,
  `release-exception`, or `unresolved`;
- the code change, rescan, SBOM/reachability proof, test, or bounded review that
  supports that disposition; and
- for a release exception, owner, rationale, exact affected artifact(s), expiry,
  compensating control, and regression/verification tests.

These are labels in a human review record, not a new application or workflow
enum. A fix requires a rescan at the selected SHA. `reviewed-unaffected`
requires artifact/lock/build-graph evidence that the component does not reach
the selected runtime or guest; a directory name or developer-dependency label
alone is insufficient. `reviewed-false-positive` requires rule-specific data
flow or semantic reasoning plus a regression test where one is meaningful.
Anything else remains `unresolved` and blocks the exact-release decision.

Reconcile #1752, #1756, #1758, and #1768 by native finding key and current path,
not by closed issue state, commit message, changelog prose, or old counts. A
moved line may be the same defect; a removed alert may reflect an exclusion or
failed analysis rather than a fix. Review every existing Sonar exclusion and
suppression against the current source set and release profile. No new global
ignore, blanket `NOSONAR`, broad SARIF dismissal, severity-wide waiver, or
directory exclusion belongs in #2084.

`docs/adr/exceptions.yaml` remains the only repository architecture/policy
waiver registry. If a finding is waived by an inline Checkov skip or another
ADR-governed suppression, both the tool-native suppression and a narrow active
ADR exception are required. The release record separately supplies the exact
artifact and test evidence required here. Do not turn every scanner
false-positive into an ADR exception, and do not treat an ADR exception as a
scanner disposition. The current broad platform-core GCP Checkov exception must
be re-reviewed per policy and narrowed, replaced, or removed; it cannot stand
in for exact-release triage.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse and boundary |
| --- | --- | --- |
| Release/source identity | ADR-042, `version.txt`, Release Please, `deploy.yml` event SHA | Bind every result to the selected immutable commit. A branch, version string, latest run, or release note is only a locator. |
| CI routing and aggregate gate | `.github/workflows/deploy.yml`, `_quality.yml`, `.github/quality-path-filters.yaml`, `scripts/quality_ownership/**`, ADR-004-R24 | Extend the existing Quality/deploy dependency graph when a machine gate changes. Do not add a second path router, release workflow, or parallel job graph. |
| Sonar | `_quality.yml` `sonarcloud`, `sonar-project.properties`, the server-side `raes-strict` gate | Consume the final quality-gate result for the exact analysis. Scanner/action exit alone is insufficient; suppressions stay centralized and individually justified. |
| CodeQL | `codeql-analysis.yml`, `.github/codeql/codeql-config.yml`, GitHub code-scanning result/alert identity | Preserve the Python/JavaScript `security-extended` categories and deliberate `scenario-dev/**` product-boundary exclusion. Do not copy queries or build a SARIF parser when the native result API supplies the verdict and alert keys. |
| Dependency estate | `.github/dependabot.yml`, every package-local manifest/lock, runtime `requirements*.lock`, Dockerfiles, OCI SBOM attestations | Inventory all roots and close or explicitly evidence the current missing Dependabot coverage through the existing per-root updater pattern. Dependabot is update cadence; lock alerts are source signal; final-image/guest SBOMs are artifact signal. Reconcile them rather than making one replace the other. |
| OCI identity/deploy | ADR-037-R5/R6, `_gcp-dev.yml` build/attest/verify/digest pin, GKE rollout/readback | Scan and record the exact four digests that are verified and deployed. Do not scan a mutable tag or rebuild equivalent-looking bytes after triage. |
| Guest images | `packer-gcp.yml`, `packer-gcp-validate.yml`, `packer-gcp-promote.yml`, `verify-build-evidence.sh`, `verify-promotion-evidence.sh`, `gcp-guest-images.md`, #1343/#1699 evidence | Bind the build producer's protected source revision to the server-assigned numeric image ID in immutable private evidence. Extend the versioned candidate contract with an SBOM created by a trusted scanner from a candidate-derived disk attached and mounted read-only; candidate code cannot produce or modify it. Never model a GCE image as OCI provenance or trust a family/label as evidence. |
| GCP CI authorization | `platform/terraform/gcp/{global/cicd-oidc,modules/cicd-oidc-identity}`, `scripts/check_tf_gcp_wif_trust/**`, `docs/dev/deploy-secrets.md`, ADR-004-R23 | Keep one pool, exact repo/ref/subject provider condition, pairwise-disjoint Environment subjects, explicit purpose secrets, resource-owned grants, semantic tests, and operator cutover/readback. |
| Runtime deployment shape | `installation.schema.RootConfig`, `GcpBackendSettings`, bootstrap preflight, `scripts/gcp/render_runtime_env.py`, installation runtime inventories, Helm/Kustomize policy | Add no release-only config manifest. Existing closed schemas and renderers own provider/profile/env validation. |
| Participant credentials | `ctf.services.participant.accounts`, `ctf.services.participant.credentials`, `CTFEvent.participant_password_override`, Django validators, #1924 | Default account creation remains CSPRNG-generated. The encrypted event override remains an explicit event-local policy, not a deployment/adoption-profile setting or universal password. |
| Agent uploads | `mission_control.api.upload_serializers`, `cms.services._uploads`, `cms.assets.validation`, signed upload token, `cms.assets.s3`, `shared.cloud.ObjectStorage`, #94/#696/#1181 guidance | Reuse the one byte cap, positive-int shape, provider Content-Length binding, authoritative final HEAD, bounded header inspection, and conditional immutable copy. |
| Other untrusted content | `ctf.services.attachment`, `ctf.inspection`, `shared.uploads.inspection`; `shared.raes.object_source`, `cms.scenarios.pack_validation`, upstream `raes-env-packs` | Keep domain format registries separate while sharing pure inspection primitives. RAES archives keep identity pinning, size/entry/expanded-byte limits, safe extraction, contract validation, and digest verification. |
| Auth/revocation | `config` OIDC/Identity Platform backends, Django sessions, `management.admin_services` lifecycle, `shared.api_tokens`, CTF account boundaries, `shared.remote_access`, Mission Control Guacamole lifecycle | Verify each credential/session kind through its owning service. Do not claim that one logout, token row, or user flag revokes every already-established provider/remote channel. |
| API/errors | explicit DRF serializers, `shared.api.errors`, `shared.errors`, domain exception families | Keep the canonical error envelope and authored bounded messages. Never return raw scanner, provider, storage, password-validator, database, or archive exception text. |
| Secrets/logs/audit | Secret Manager references and entrypoint hydration, `shared.field_encryption`, `shared.log_sanitize`, provisioner `log_redact`, `shared.audit`, request IDs | Use fingerprints and stable IDs. `safe_log_value` is injection defense; use fingerprinting or omit confidential values. Do not add a sanitizer, audit table, or release logger. |
| Policy exceptions | tool-native narrow suppression plus `docs/adr/exceptions.yaml` when an ADR rule is waived | Keep owner/reason/expiry/path enforcement. The release record binds the waiver to exact artifacts and tests; no second global exception registry. |

## Credential And Identity Decisions

The first GCP adoption baseline uses generated participant credentials. Shared
event-password override does **not** become part of the deployment/adoption
profile and must not gain a root config field, environment variable, Terraform
value, bootstrap default, or seeded universal value. The existing encrypted,
owner-enabled event-local override may remain a supported product capability,
but it is outside the baseline release evidence unless the release owner
explicitly includes and separately tests that weaker event policy. Evidence for
the baseline covers distinct generated credentials, common Django validation,
force-change quarantine, one-time delivery/reset behavior, token revocation,
and absence from projection/log/audit/cache. Do not restate #1645's historical
universal shared-password premise as current behavior.

For #1621/#1646/#1699, code shape and merged Terraform are prerequisites only.
Release evidence must bind:

- repository OIDC subject customization and exact protected source refs;
- branch restrictions/approval policy on each literal purpose Environment;
- provider condition plus each service account's effective WIF members;
- the absence of legacy shared service-account secrets/fallbacks;
- positive build, validate, promote, deploy, and destroy dispatches and denied
  wrong-ref, tag/PR, and wrong-purpose attempts; and
- effective allowed and denied permissions from IAM policy readback, Policy
  Troubleshooter where applicable, and Cloud Audit Logs for the checked-in
  operations.

The existing purpose seam is retained: purpose -> literal Environment subject,
service account, checked-in command set, resource-owned IAM grants, secret name,
and tests. Deploy and destroy must have independently derived grants even when
some permissions overlap; reusing `platform_roles` wholesale is not evidence of
least privilege. The special `refs/heads/gcp-dev` deploy allowance is valid only
while live branch and Environment policy prove it protected for the selected
release; otherwise remove it rather than treating a workflow-side ref check as
the cloud authorization boundary.

## Cross-Cutting Layers The Intended Design Must Pass

1. **Release and workflow admission.** The selected commit, event type, full
   protected ref, repository, Environment, run ID, and run attempt are validated
   before credentials or mutable cloud operations. `deploy.yml` remains the
   orchestration owner. Fork PRs and untrusted refs receive no scanner secret,
   cloud token, protected Environment, or self-hosted runner.
2. **Scanner result gates.** Sonar must expose the final quality-gate result for
   the exact analysis on any run used to authorize the release. CodeQL must
   distinguish analysis/upload failure from completed analysis and use exact
   alert identities for policy review. Dependency tooling must scan the exact
   built/runtime/guest artifacts. Any asynchronous producer is polled to a
   bounded terminal result; timeout and missing result fail closed.
3. **Artifact identity and provenance.** OCI build output digest, attestation
   subject, scanner subject, rendered manifest, admitted workload, and running
   image ID all agree, and an unexpected workload or container fails the closed
   runtime inventory. Guest build/validation/promotion/SBOM evidence agrees on
   source SHA and numeric image identity. An immutable build-producer record,
   not a validator claim or mutable image label, establishes the source binding.
   Tags, families, labels, package locks, and repository paths never replace
   byte/resource identity.
4. **Dependency and content shapes.** Package locks remain owned per package;
   Docker stages define what reaches the final OCI image; guest package
   inventory is collected outside the candidate trust domain from an exact
   candidate-derived disk attached and mounted read-only by a credentialless
   trusted scanner. Do not collect home directories, environment, cloud
   metadata, config files, histories, or arbitrary guest filesystem content
   into an SBOM artifact. Intentionally vulnerable scenario
   targets are a separately named release artifact/trust domain, not a blanket
   platform exclusion or false positive.
5. **GCP authentication and IAM.** GitHub OIDC, provider repository/ref/subject
   conditions, exact service-account member binding, resource IAM, GKE RBAC,
   workload identity, and guest no-SA/no-scope posture all pass independently.
   Names and Terraform plans are not effective-policy proof; denied-path tests
   are required.
6. **Runtime configuration.** `RootConfig`, selected GCP bundle, bootstrap
   preflight, Terraform variable validation, runtime inventory, generated env,
   Kubernetes admission, and Django startup settings remain the canonical
   closed shapes. A release record, scanner finding, or customer input cannot
   introduce an env key, secret name, provider reference, image, or authority.
7. **HTTP authentication and authorization.** OIDC/Identity Platform verification
   (including Identity Platform `check_revoked=True`), active-user checks,
   bearer-first API-token authentication, session CSRF, token scope, CTF account
   boundaries, object policy, and service-level reauthorization remain
   additive. UI state and scanner disposition grant no authority.
8. **Upload/content validation.** Agent initiation rejects boolean/non-integer/
   non-positive/over-cap sizes before presign; finalization uses signed identity,
   current cap, provider-reported size, bounded content inspection, and an
   identity-conditional immutable copy before tag/model/audit. CTF attachments
   keep their own 50 MiB/extension/category policy and full-stream text check;
   explicitly opaque forensics formats remain an owned limitation. RAES object
   packs remain bounded and digest/contract verified before parsing or launch.
9. **Revocation and lifecycle.** Evidence distinguishes API-token `revoked_at`,
   inactive/deleted-owner denial, participant reset token revocation, Django
   session hash invalidation/new-request liveness, logout cookie flush, provider
   logout/revocation, queued bootstrap cancellation, undelivered Guacamole-token
   clearing, and already-open remote sessions. Document measured maximum
   revocation bounds; do not promise instantaneous teardown where the current
   channel only rechecks on the next request or expiry.
10. **Secret handling and OS exposure.** Scanner/cloud tokens use action-managed
    credentials or environment, never command arguments, URLs, summaries, or
    artifacts. Generated tfvars, auth files, SSH keys, tunnel logs, SBOMs, and
    reports live under `RUNNER_TEMP` with restrictive permissions and `always()`
    cleanup, especially on persistent self-hosted runners. Secret values are
    streamed on stdin or through existing secret mounts/adapters, never
    `kubectl --from-literal`, shell tracing, process argv, repo-worktree files,
    Terraform outputs, or environment dumps.
11. **Errors, logs, and evidence publication.** Public APIs keep the shared
    error envelope; workflows use nonzero exits and bounded `::error::` records.
    Logs and public closure evidence contain stable findings, logical artifact
    names, digests/fingerprints, result categories, and correlation IDs only.
    Raw exceptions, provider/API bodies, credentials, emails, object keys,
    presigned/token URLs, private endpoints, Terraform data, guest output,
    SARIF, and sensitive reproduction stay out of public artifacts and comments.
12. **Persistence and exceptions.** Git history stores only the pointer/decision
    record; GitHub/Sonar/registry/GCP producers retain native evidence, with raw
    release payloads confined to the private retained GCS evidence bucket. Existing
    Django state, `shared.audit`, promotion verdicts, and provider logs keep
    their owned purposes and do not become a release database. ADR waivers use
    the existing registry and expiry guard; scanner dispositions remain in the
    exact-release review.

## Extensibility Seam

The release seam is an artifact-set entry parameterized by logical artifact
role, immutable source/resource identity, provider/environment/profile, native
producer/version, evidence locator, actual posture/result, and limitation. A
future GCP tenant, guest profile, OCI component, or release adds an entry and
native evidence; it does not add a provider switch to application code or edit
a universal scanner schema.

The IAM seam remains the existing explicit purpose tuple described above. A
future CI purpose adds one subject/account/grant/test slice instead of widening
another purpose. Evidence bucket access is conditioned by purpose-owned object
prefix: build creates build records, validation reads those records and creates
validation records, promotion reads validation records, and other producers
cannot cross those boundaries. The guest seam is the immutable build-source
record plus versioned validation evidence: an externally collected guest-SBOM
locator and digest bind to the same numeric candidate identity rather than
creating a guest registry. The participant-credential seam remains event-local
creation policy (`generated` versus explicit `event_shared`), not deployment
configuration.

If repeated releases later demonstrate a need for machine-readable attestation
or VEX, design and version that contract from observed records. Do not make the
one-release Markdown vocabulary a de facto API now.

## Whole-Repository Scope

The implementation must evaluate these existing surfaces together:

- release/CI: `.github/workflows/{deploy,_quality,codeql-analysis,_gcp-dev}.yml`,
  `.github/workflows/packer-gcp*.yml`, `gcp-dev-destroy.yml`,
  `.github/quality-path-filters.yaml`, `scripts/quality_ownership/**`,
  `sonar-project.properties`, `.github/codeql/codeql-config.yml`,
  `.gitleaks.toml`, `.github/dependabot.yml`, and package locks;
- artifact supply chain: the four production Dockerfiles, ADR-037,
  `rev1-build-deployment-provenance.md`, Artifact Registry/GKE digest rendering,
  build attestations/SBOMs, Packer GCP templates/scripts, validation/promotion
  evidence and verifier, guest families, and GDC export only if selected;
- GCP trust/runtime: foundational `cicd-oidc` and `cicd-oidc-identity`,
  `packer-build-infra`, platform-core/portal IAM, Terraform validation
  inventory, `.tflint.hcl`, `platform/terraform/.checkov.yaml`,
  `scripts/check_tf_gcp_wif_trust/**`, GKE RBAC/NetworkPolicy/admission,
  bootstrap preflight, runtime renderers/inventories, Secret Manager hydration,
  and `docs/dev/deploy-secrets.md` operator readback;
- credentials/auth: participant account/credential services and forms,
  `EncryptedStringField`, Django password validators/session auth,
  OIDC/Identity Platform, `management` lifecycle services,
  `shared.api_tokens`, CTF middleware/WebSocket boundaries, remote-access and
  Guacamole bootstrap/token lifecycle;
- untrusted content: Mission Control upload serializers/views, `cms.services`
  upload flow, CMS validation/token/storage helpers, both `shared.cloud`
  adapters, `shared.uploads.inspection`, CTF attachment service/inspection/S3,
  RAES object staging, upstream pack validation/digest, and content-delivery
  size/digest boundaries; and
- errors/evidence/governance: domain exceptions, `shared.errors`,
  `shared.api.errors`, `shared.log_sanitize`, provisioner `log_redact`,
  `shared.audit`, `docs/adr/{index,exceptions}.yaml`, `scripts/adr_guard/**`,
  `docs/requirements/GEN-002/requirement.md`,
  #94/#696/#1181/#1343/#1540/#1699/#1924/#1943/#2081 guidance, and the
  restricted security-reporting channel.

Runtime hosts include GitHub-hosted analysis/image runners, the persistent GCP
deploy runner, Artifact Registry, GKE admission and workloads, Secret Manager,
Cloud Logging/Audit Logs, Packer builder/validator VMs, shipped guest disks, the
browser, Django/ASGI workers, Guacamole, PostgreSQL/Redis, and object storage.
Evidence must say which layer it exercised; one layer never implies another.

## Gotchas And Anti-Patterns

- Do not aggregate Sonar, CodeQL, Dependabot, Trivy, OSV, Checkov, or GitHub
  dashboard totals into an exploit count or one context-free "security pass."
- Do not treat a successful scanner process, SARIF upload, build, attestation,
  deployment, rollout, smoke job, or closed historical issue as the downstream
  analysis/result it merely enables.
- Do not triage mutable tags, image families, latest branches, or source locks
  and claim the result applies to different deployed bytes.
- Do not classify a vulnerable package as unaffected solely because the import
  is not obvious. Include OS packages, copied build output, CLI executables,
  plugins/providers, entrypoints, and guest services in reachability review.
- Do not scan intentionally vulnerable range artifacts as ordinary platform
  code, but do not hide them globally either. Name the artifact, isolation,
  expected vulnerability, deployment boundary, and tests.
- Do not add global Sonar/CodeQL/Trivy exclusions, blanket CVE ignores,
  severity-wide exceptions, perpetual waivers, or one `platform-core` decision
  covering unrelated Checkov rules.
- Do not confuse generated participant passwords, an event-local encrypted
  override, bootstrap operator credentials, API tokens, invite/reset tokens,
  provider tokens, Guacamole URLs, SSH keys, and guest credentials. They have
  different owners, storage, delivery, and revocation semantics.
- Do not add a deployment-wide shared participant password or expose the event
  override through read DTOs, form initial values, logs, audit, email replay,
  cache, Terraform, Kubernetes, or env configuration.
- Do not interpret separate service-account names as capability isolation while
  deploy/destroy share broad roles, legacy secrets survive, an Environment is
  unprotected, or the provider admits an unintended ref.
- Do not pass secrets in subprocess argv or retain them in a self-hosted runner
  worktree. Masking, `safe_log_value`, `sensitive=True`, or a private repository
  does not fix process-list/disk exposure.
- Do not duplicate upload caps, file registries, magic signatures, archive
  validators, token parsers, cloud storage calls, error families, or log
  sanitizers. A client-side check, MIME type, extension, ETag, or signed size is
  not authoritative content validation.
- Do not claim logout or `is_active=false` tears down an already-open remote
  session unless the owning channel performs and demonstrates that teardown.
- Do not copy sensitive reproduction, raw alerts, SBOM bodies, guest output,
  provider identifiers, or Terraform state into a public issue or closure doc.
  #1531 owns the reporting-contact correction; #2084 uses the approved private
  channel that exists at release time.

## Non-Goals And Implementation Boundaries

- No issue implementation, scanner execution, cloud/API query, deploy,
  promotion, secret rotation, issue closure, or release approval in this
  preflight.
- No promise to fix every historical repository alert or prove every alert
  exploitable. The obligation is complete, evidence-backed disposition for the
  selected release artifacts and supported paths.
- No redesign of Sonar, CodeQL, Dependabot, GitHub branch protection, the
  application API, authentication providers, participant accounts, uploads,
  RAES ingestion, Packer, GKE, or the release system beyond changes directly
  required to obtain a trustworthy exact-release outcome.
- No new release database, scanner service, VEX schema, artifact registry,
  generic evidence service, exception store, config manifest, customer identity, credential type,
  status enum, controller, repository, audit table, logging framework, or
  generic security abstraction.
- No universal antivirus/content-safety claim for uploaded executables or CTF
  opaque forensic formats. Evidence covers the documented size, identity,
  type/stream, containment, and authorization guarantees on supported paths.
- No claim of immediate revocation for provider sessions or established remote
  channels whose incumbent contract provides next-request, expiry, or bounded
  cleanup behavior. Record and test the actual bound.
- No reporting-contact redesign (#1531), no unrelated security backlog
  closure, no AWS release decision, and no expansion of the BigRAE release into
  unrelated-customer shared-control-plane multitenancy.

## Validation Expectations

For this documentation-only preflight:

```bash
python3 scripts/adr_guard/adr_guard.py --files \
  docs/architecture/gcp-release-security-closure-preflight-2084.md \
  --level fast
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future implementation inherits the repository-required `actionlint`, TFLint,
import-linter, Kubernetes, ADR guard, and stack-native tests for every touched
surface. Release evidence additionally needs exact-SHA scanner conclusions,
OCI/guest artifact scans, GKE and IAM readback, negative permission probes,
supported-path auth/revocation/upload tests, and secret/log/error leak tests.
