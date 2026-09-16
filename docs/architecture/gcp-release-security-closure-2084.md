# GCP Exact-Release Security Closure (#2084)

Status: implementation candidate; exact-release verdict unresolved

Date: 2026-09-12

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/2084>

Design source:
`docs/architecture/gcp-release-security-closure-preflight-2084.md`

Inspection baseline: `99e2a610271985d9072e37612e13f00943e28076`
(`origin/dev` when implementation started). This is not the selected release
revision.

## Verdict

The repository now has the controls needed to produce and gate the requested
evidence. No GCP release is approved by this record yet. The verdict remains
`unresolved` until one immutable selected source revision has all native
producer results in the matrix below and every identity and artifact agrees.

This record follows the pointer-layer contract established by
`rev1-release-evidence-index-1540.md`: native scanner, GitHub Actions, registry,
GKE, GCE, IAM, and audit results remain authoritative. This page records their
immutable locators and interpreted conclusions without copying sensitive
payloads, SARIF, SBOM contents, cloud identifiers, or reproduction details.

## Selected release identity and producer evidence

| Evidence | Required exact binding | Status for this record | Authoritative locator / capture rule |
| --- | --- | --- | --- |
| Source | One 40-hex commit; release tag if present | `not-yet-demonstrated` | Record the merged release commit and the exact PR/Quality run. A branch name or this inspection baseline is insufficient. |
| SonarCloud | Analysis revision and terminal `raes-strict` quality-gate verdict | `not-yet-demonstrated` | The candidate makes every canonical analysis wait for the quality gate. Record the exact analysis/run and observed verdict after CI. Scanner execution alone is insufficient. |
| CodeQL | Python and JavaScript `security-extended` analyses at the selected commit | `not-yet-demonstrated` | The candidate removes `continue-on-error`. Record both exact workflow jobs and reconcile their alert keys after the PR run. |
| Source dependencies | All 8 `package-lock.json` and 12 `uv.lock` roots | `candidate-captured` | OSV-Scanner v2.4.0 lockfile-only scan reported no findings locally on the implementation tree; npm audit reported zero vulnerabilities for all npm roots. The release result must come from the selected-commit Quality run. |
| OCI artifacts | Portal, provisioner, guacd, and guacamole-client repository plus digest | `not-yet-demonstrated` | `_gcp-dev.yml` emits attestations/SBOMs, then a separate `gcp-release-scan-dev` job scans every exact digest with independently checksum-pinned Trivy 0.71.2 before rollout. Raw manifests/reports go to retained private GCS; record the immutable run/attempt, opaque verdict locator, and private object generations/digests. |
| Running GKE workloads | Closed workload/component/container map; declared and runtime repository plus digest | `not-yet-demonstrated` | Record the deploy run's redacted `gcp-running-image-verdict-<sha>` plus the corresponding private evidence object generation/digest after every rollout succeeds. Every normal, init, and ephemeral container in the namespace must belong to the checked-in release map and report the exact approved `repository@sha256`; an extra workload or sidecar fails the gate. Provisioner is a task image and is covered by its digest scan/attestation and admission policy rather than a continuously running pod. |
| GCE guest images | Project, name, numeric image ID, family/type, immutable build-source record, source revision, validation run/attempt and exact verdict-artifact ID | `not-yet-demonstrated` | The build identity writes an immutable private record under the server-assigned numeric image ID. Protected validation requires that record, the candidate label, its own checked-out revision/ref, and the exact candidate identity to agree before booting or publishing evidence. Its redacted GitHub artifact binds the full private-evidence digest to the candidate project/name/numeric ID/family/type/revision. Promotion fetches that exact artifact ID from the successful protected run; a lifecycle GCP credential cannot mint or substitute it. Record every selected profile's build, validation, and promotion run. A family or mutable label is not evidence. |
| Guest SBOMs | Non-empty SPDX JSON, SHA-256, source-pinned Syft version/archive digest, exact candidate-derived disk and validation evidence | `not-yet-demonstrated` | Validation evidence schema 3 binds `guest-sbom.spdx.json` to the exact candidate numeric image ID. A separate credentialless trusted scanner receives a candidate-derived disk attached read-only and mounts it `ro,nosuid,nodev,noexec`; candidate code never executes in the SBOM producer. Raw evidence is retained in private GCS and only a redacted verdict is public. Promotion verifies the protected run, private-evidence digest, file metadata, collection boundary, source image ID, scanner identity, SBOM digest, SPDX shape, and packages. Record each private object generation/digest and observed result. |
| Effective GCP authorization | Exact GitHub Environment subject, service account, grants, allowed and denied operations | `not-yet-demonstrated` | Capture provider/binding readback, protected Environment policy, effective IAM/Policy Troubleshooter results, and Audit Logs for build, validate, promote, release-scan, deploy, and destroy. Terraform source alone is insufficient. |

Missing, inaccessible, expired, stale, wrong-SHA, wrong-digest, ambiguous, or
contradictory evidence leaves the row unresolved and blocks the release. The
same is true when a producer ran successfully but its governed analysis result
did not pass.

## Current finding reconciliation

### Sonar history

| Issue | Current interpretation | Disposition |
| --- | --- | --- |
| #1756 | The 15 `mcp/ops` new-code findings were addressed by merged PR #1757 (`e50713a67051716e8bfae5067539b57c4488c71e`). | `fixed`, subject to the selected-commit Sonar rescan. The still-open issue is not evidence of a current defect, and the merge is not a substitute for the rescan. |
| #1758 | `_content_ref_from_resource` complexity was reduced by merged PR #1759 (`9ffa9b3be789e9fb15dda2292522abf45694b5c0`). | `fixed`, subject to the selected-commit Sonar rescan. |
| #1768 | The issue explicitly records first-party coverage improvement as hygiene rather than a failing release gate; PR #1769 (`238e2f7ff8c67b6b2507cd94cc454153ef2a5a01`) removed vendored minified JS from the metric. | `reviewed-unaffected` only when the exact selected-commit quality gate passes its configured coverage threshold. The remaining backlog stays owned by #1768. |

The stale Docker `S7023` global suppression has been removed because every
current `Dockerfile` `FROM` is digest-pinned. No new Sonar exclusion or blanket
finding ignore is introduced.

### CodeQL

GitHub reported eight open CodeQL alerts on `main` at inspection time. They are
not treated as eight exploitable release defects; each current data flow is
resolved in the candidate and remains `fixed-pending-rescan`:

| Alert(s) | Path | Candidate resolution |
| --- | --- | --- |
| 1176 | `workspaces/services/_memberships.py` | Fingerprint the role at the log sink. |
| 1169, 1112 | `mission_control/api/guacamole.py` | Return an authored bootstrap message and classify persisted failure text. |
| 1165 | `config/csp_report.py` | Fingerprint URL-bearing fields; retain only bounded directive/disposition text. This is the current-path successor to #1752's CSP finding; PR #1754 fixed the original alerts but does not decide this newer alert. |
| 1121, 1120 | `ctf/services/attachment.py` | Do not echo inspection/storage exceptions; fingerprint confidential log fields. |
| 1118 | `shared/api/errors.py` | Map DRF details to a fixed message allowlist/code classification rather than returning arbitrary detail text. |
| 1111 | `mission_control/views/_guacamole_bootstrap.py` | Classify persisted failure text before the legacy response. |

CodeQL analysis/upload is now blocking. These rows become `fixed` only when
the selected-commit Python and JavaScript jobs complete and the current alert
instances are absent; a workflow failure is not interpreted as zero findings.

### Dependency findings and ownership

GitHub reported 111 open Dependabot alerts against `main` at inspection time.
That total is historical branch signal, not the candidate dependency verdict.
The implementation updates the affected current locks, including AsyncSSH
2.24.0, Django REST Framework 3.18.1, sqlparse 0.6.0, Hono 4.13.7, qs
6.16.0, fast-uri 3.1.7, and Vitest 4.1.11. Other alert families already resolve
above their published fixed versions in the `dev` locks, including Django,
cryptography, h2, daphne, pyasn1, browserslist, js-yaml, postcss, nanoid,
DOMPurify, Mermaid, `@hono/node-server`, `ip-address`, `body-parser`, and
`brace-expansion`.

The blocking OSV job discovers every lock root instead of scanning only the
repository root. Dependabot now assigns weekly uv update ownership to every
Python package root, including the previously omitted
`scripts/assert_portal_inspection`, `scripts/handle_sd_replacement`,
`uat/event-load-harness`, and `uat/range-functional-smoke`. Lockfile evidence
does not replace the four OCI scans or guest SBOM review.

## Historical security issue reconciliation

| Issue | Current evidence and decision | Release status |
| --- | --- | --- |
| #94 | Closed through PR #2101 (`9b4517081c40ce31f488a612f0276915d9dcc297`). The server-owned byte limit is enforced before presign and at finalization; signed Content-Length, authoritative object HEAD, oversize cleanup, bounded inspection, and immutable-copy tests cover the supported GCP path. | Source mechanism `captured`; selected-commit tests and deployed path still required. |
| #1645 | The universal-shared-password premise is no longer current. PR #1933 (`e9888dae876855e90e2a27a9a2cfe6cb933002af`) and current tests prove unique CSPRNG credentials by default, one-time reset/display, hash-only persistence, session/API-token invalidation, audit redaction, and force-change state. | The GCP adoption baseline selects generated credentials. The encrypted event-local shared-password override remains an explicit organizer policy and is excluded from deployment config, Terraform, bootstrap defaults, and the adoption profile. |
| #1621 / #1646 | PRs #1623 and #1685 established protected-ref validation and evidence-bound promotion; #1699/PR #2145 added purpose identities and strict run/evidence/image-ID verification. This candidate adds an immutable build-identity/source record and binds an externally produced read-only-disk SBOM through evidence schema 3. | Source mechanism `captured`; protected selected-commit build/validation/promotion runs remain required. Open issue state is context, not a release veto. |
| #1699 | Closed through PR #2145 (`f6f0b7b340cd3dd81f9de8b3bd49368ad5e2e774`). Build, validate, promote, deploy, and destroy use distinct subjects and accounts. This candidate adds a sixth isolated release-scan subject/account, repository-scoped read grants, and object-prefix-conditioned evidence access; build alone creates immutable build-source records, validation can only read those records and create validation records, and promotion remains read-only. Deploy/destroy role sets are independently derived; neither receives broad Compute Admin or Storage Admin. Compute lifecycle is limited to network/security roles; storage mutation is condition-bound to the deterministic assets, audit-log, and GDC-image buckets, while workload-IAM administration is granted only on the exact state and configured external content buckets. Destroy does not receive Service Usage Admin. | Source mechanism `captured`; live effective-permission and denied-path proof remains unresolved and blocks release. |
| #1752 | Original alerts 1117/1164 were fixed through PR #1754. The newer CSP alert 1165 is separately addressed above. | `fixed-pending-rescan`. |
| #1756 / #1758 | Merged fixes are identified above; their open state does not supersede native Sonar evidence. | `fixed-pending-rescan`. |
| #1768 | Coverage hygiene remains useful and owned, but its own issue states that it is not a failing release gate. | `reviewed-unaffected` only if the selected-commit gate passes. |

## Supported-path security verification

| Concern | Owning controls and evidence required |
| --- | --- |
| Participant credentials | `test_bootstrap_credential_hardening.py`, `test_participant_password_issuance.py`, and the organizer guide prove generated defaults, explicit event override, one-time delivery/reset, Django validation, force-change state, session/API-token invalidation, and secret-free audit. |
| Agent upload bounds | #94's initiation, finalization, provider signing, frontend-contract, and cleanup tests. Exact cap, one byte over, quota interaction, crafted input, and mismatch/cleanup ordering are all represented. |
| Other untrusted content | CTF attachment header/full-stream inspection and RAES object-source archive identity, byte/entry/expanded-size limits, safe extraction, schema, and digest tests. Arbitrary scanner/provider exception text is not returned to clients. |
| Tokens and sessions | Participant password reset invalidates sessions and revokes tokens; API token authentication rejects revoked/expired rows; management disable flows revoke live tokens. Provider and remote-access channels remain separate owning boundaries and need the selected-profile runtime checks. |
| Secrets and logs | Deployment tfvars/config and Kubernetes secret staging use mode-0600 files under `RUNNER_TEMP`, are explicitly removed, and never put secret values in Terraform or kubectl argv. CSP URLs, user email, storage keys, inspection/provider causes, and role values are omitted or fingerprinted. |
| Sensitive findings | Reproduction details, provider payloads, raw SARIF/SBOMs, and exact cloud identities stay in the retained private `release-evidence` bucket. Actions artifacts contain only a redacted verdict, source SHA, opaque locator, private-evidence digest, and opaque candidate-binding digest. Promotion authenticates the exact artifact ID and originating successful protected run before reading private evidence. Public disclosure follows `SECURITY.md`. #1531 remains the owner of the separate public reporting-contact correction. |

## Release exceptions

All current GCP Checkov decisions are inline on the exact resource and paired
with `docs/adr/exceptions.yaml`; the prior global GCP skip list is removed.

| Owner | Finding(s) and affected artifact | Rationale / compensating verification | Expiry |
| --- | --- | --- | --- |
| `@Brad-Edwards` | CKV_GCP_6, CKV_GCP_79, CKV_GCP_109, and CKV_GCP_111, portal Cloud SQL instance | `ssl_mode=ENCRYPTED_ONLY` supersedes legacy `require_ssl`; the supported PostgreSQL major is an explicit migration decision; error-statement and all-statement logging are excluded because queries can contain participant data or credentials, while connection, severity, duration, lock-wait, and pgaudit logging remain enabled. Blocking Checkov, Terraform validation, and release tests. | 2027-03-11 |
| `@Brad-Edwards` | CKV_GCP_12, CKV_GCP_21, CKV_GCP_65, portal GKE cluster | Dataplane V2 enforces NetworkPolicy; labels are caller-supplied through the module contract; human RBAC groups are intentionally absent in favor of IAM Connect Gateway and KSA/GSA. | 2027-03-11 |
| `@Brad-Edwards` | CKV_GCP_62, audit-log GCS bucket | This is the terminal access-log sink; self-logging recurses. The Google-managed usage-log principal has only `roles/storage.objectCreator` on the sink, and source buckets depend on that binding. | 2027-03-11 |
| `@Brad-Edwards` | CKV_GCP_62, foundational release-evidence GCS bucket | The private evidence bucket must precede and outlive platform-core, including its audit sink; depending on that sink breaks bootstrap/destroy, while self-logging recurses. PAP, uniform access, versioning, locked 90-day retention, 365-day lifecycle, object-prefix-conditioned create-only producers, build-record-only validation read access, digest-anchored deploy evidence, and validation-record-only promotion read access remain enforced. | 2027-03-11 |
| `@Brad-Edwards` | CKV_GCP_107, CKV_GCP_124, CKV2_GCP_10, optional Identity Platform gen1 beforeCreate hook | Google-managed Identity Platform requires the public invoker; the portal independently enforces the domain allowlist and policy-constrained deployments disable the hook. | 2027-03-11 |
| `@Brad-Edwards` | CKV_GCP_83, platform-events and dead-letter Pub/Sub topics | Google-managed encryption is retained until a dedicated messaging CMEK lifecycle is deployed and exercised. | 2026-12-11 |

No exception changes a native scanner result. At release time each active row
must still be applicable to the selected artifact, unexpired, and supported by
the named tests; otherwise it is unresolved.

## Release capture checklist

Before changing this record's verdict, the release owner must record:

- the immutable selected source SHA and release tag, if any;
- the exact CI run/attempt and terminal Sonar and CodeQL conclusions;
- the blocking all-lock OSV result plus exact OCI digest scan/attestation/SBOM
  private object generations/digests and redacted verdict locators;
- the matching GKE running-image private object and redacted verdict;
- every selected GCE image's numeric ID, immutable build-source object,
  protected build/validation/promotion run, exact schema-2 redacted verdict
  artifact ID, schema-3 private validation object, external read-only scanner
  identity, and guest-SBOM digest;
- effective WIF membership, Environment branch policy, allowed operations,
  denied wrong-ref/wrong-purpose operations, and Audit Log locators for all six
  purpose identities; and
- each active exception's owner acceptance and expiry check.

Only then may every row be changed from `not-yet-demonstrated` or
`fixed-pending-rescan` to a supported disposition and the exact-release verdict
be approved.
