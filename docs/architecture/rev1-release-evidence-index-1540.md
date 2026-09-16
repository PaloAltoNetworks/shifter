# REV1 Release-Evidence Index (#1540)

Status: release-evidence integration index

Date: 2026-07-21

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1540>

Design source: `docs/architecture/rev1-release-evidence-integration-preflight-1540.md`

Index baseline: `origin/dev` at `44448536c` (the commit this index was authored
against; the release SHA is fixed by #1539 at release time).

## What this is

A single bounded pointer layer that lets the REV1 release-verification gate
(#1539) find and interpret the maintainability and release evidence for the
REV1.3 (Maintainability and Verification) milestone. Each row names the concern,
its canonical producer or governing ADR, the gate's configuration posture, the
release-evidence status, and either the immutable locator with observed
conclusion (when evidence is already captured) or exactly what #1539 must
capture and pin at the release SHA.

## What this is not

This index does not re-run a gate, re-decide a verdict, or copy evidence. The
linked producer stays authoritative for its result and diagnostics. It adds no
schema, parser, status enum, service, workflow, or persistence: the labels below
describe how existing evidence is produced and are not a runtime lifecycle. It
never manufactures stronger evidence than a producer emits: a row is only marked
`captured` when it cites an immutable producer-owned report or run reference with
the observed conclusion; otherwise it is `not-yet-demonstrated`, an open capture
item rather than a pass. A source path, gate definition, baseline SHA, test
name, or prose assertion alone is not execution evidence.

## Column semantics

- **Gate posture** describes how the gate behaves by construction, independent
  of any single run: `blocking` (a failure blocks the routed pull-request or
  merge path), `advisory` (runs but `continue-on-error` or soft-fail; does not
  block), `live-manual` (evidence is produced by a deliberate run in a deployed
  environment, not by pull-request CI), or `not-implemented` (no gate exists
  yet).
- **Release-evidence status** is `captured` only when this row cites an
  immutable producer-owned report or run reference plus the observed conclusion.
  Otherwise it is `not-yet-demonstrated`, and the final column states exactly
  what #1539 must capture and pin at the release SHA.

## Native blocking dependencies

The three native `blocked_by` dependencies of #1540 are complete, each with an
immutable final-report record on its issue thread:

| Issue | Title | State | Immutable record (observed conclusion) |
| --- | --- | --- | --- |
| #1528 | REV1 Infrastructure: validate every Terraform root on pull requests | closed | [final report](https://github.com/Brad-Edwards/shifter/issues/1528#issuecomment-4950178354): CI green, SonarCloud passed; PR #1599 merge `7c1ed4cd` |
| #1529 | REV1 Testing: make clean-checkout commands and quality metrics trustworthy | closed | [final report](https://github.com/Brad-Edwards/shifter/issues/1529#issuecomment-4951927631): CI green, SonarCloud passed; PR #1603 merge `ac895517` |
| #1530 | REV1 Testing: enforce production-path ownership in routed CI | closed | [final report](https://github.com/Brad-Edwards/shifter/issues/1530#issuecomment-5006743733): CI green, SonarCloud passed, 42 tests; PR #1709 merge `c98a7114` |

## Evidence index

| Concern | Canonical producer / authority | Gate posture | Release-evidence status | Immutable locator + observed conclusion, or what #1539 must capture |
| --- | --- | --- | --- | --- |
| Terraform-root validation (#1528) | `platform/terraform/validation-inventory.yaml`, `scripts/check_tf_roots/`, `_quality.yml` `terraform-matrix` / `terraform-validate` / `terraform-contract-tests` (named `terraform-module-contracts` at the indexed SHA) | `blocking` | `captured` | [#1528 final report](https://github.com/Brad-Edwards/shifter/issues/1528#issuecomment-4950178354): CI green at PR #1599 merge `7c1ed4cd`. Scope: backendless locked `init` + `validate` of inventory-selected roots, not TFLint/Checkov/plan/apply/live-provider. |
| Clean-checkout commands and metrics (#1529) | root `Makefile`, `docs/dev/testing.md`, package configs + lockfiles, `sonar-project.properties`, `tests/platform/test_clean_checkout_posture.py` | `blocking` | `captured` | [#1529 final report](https://github.com/Brad-Edwards/shifter/issues/1529#issuecomment-4951927631): CI green, SonarCloud passed at PR #1603 merge `ac895517`. Scope: clean checkout reproduces CI plus package coverage floors; SQLite-lane coverage is not PostgreSQL/Redis/browser/live-cloud. |
| Production-path quality ownership (#1530) | `.github/quality-path-filters.yaml`, `scripts/quality_ownership/{contract,classify_paths}.py`, `_quality.yml` `paths`, `adr_guard.py` `quality-path-ownership` (ADR-004-R24 / GEN-002) | `blocking` | `captured` | [#1530 final report](https://github.com/Brad-Edwards/shifter/issues/1530#issuecomment-5006743733): CI green, SonarCloud passed, 42 tests at PR #1709 merge `c98a7114`. Open coverage-gap exceptions in `docs/adr/exceptions.yaml`, tracked in #1698. |
| Security gate (blocking jobs) | `_quality.yml` routed SAST (`shifter-platform-sast`, `provisioner-sast`, `packer-sast`, `bootstrap-sast`, `gcp-scripts-sast`, `check-layer-imports-sast`, `installation-sast`, `event-load-harness-sast`), Terraform `security-iac` (Checkov), `secrets-gitleaks`, PR-waiting `sonarcloud` (`sonar.qualitygate.wait=true`); REV1.1 exit #1537 (closed) | `blocking` | `not-yet-demonstrated` | #1539 must pin the routed Quality run at the release SHA and record each listed blocking security job's conclusion. `docs/architecture/rev1/security.md` is a finding source, not remediation proof; remediation is owned by REV1.1 #1537. |
| Security scanners (advisory) | `_quality.yml` `security-trivy-advisory`, `security-osv-advisory`, K8s `checkov` (soft-fail); `codeql-analysis.yml` advisory SARIF upload | `advisory` | `not-yet-demonstrated` | Trivy, OSV-Scanner, K8s Checkov, and the CodeQL upload are `continue-on-error`; never read as blocking release gates even where branch-protection prose names a context. #1539 records their advisory conclusion at the release SHA if used. |
| AWS/GCP backend configuration conformance | `shifter/installation/{loader,publication}.py` + schema/contract/registry, `shifter/installation/examples/{aws,gcp}.yaml`, `shifter/installation/tests/` (`test_examples`, `test_contract`, `test_registry`, `test_schema`, `test_gcp_bundle`) | `blocking` | `not-yet-demonstrated` | #1539 must pin the routed installation test-lane run at the release SHA + conclusion. Scope: bundle and configuration contract conformance for both shipped examples; not range realization, not ADR-039 lifecycle. |
| AWS/GCP range-substrate conformance | ADR-039; `docs/architecture/provider-neutral-range-substrate.md` | `live-manual` | `not-yet-demonstrated` | Per-adapter four-operation (provision/destroy/pause/resume) conformance requires the shared black-box suite plus disposable real-provider evidence; #1539 must record the run and provider/environment per adapter. GCP GDC pause/resume and losslessness gaps remain explicit until closed. |
| ACES manifest conformance | `shared.aces.manifest`, `shared/aces/backend-manifest.json`, `tests/shared/aces/test_backend_{manifest_publication,conformance_gate}.py`, parity row `validation.aces-manifest-conformance` | `blocking` | `not-yet-demonstrated` | #1539 must pin the routed platform test-gate run (provisioning-only profile) at the release SHA + conclusion. Scope: manifest/profile conformance, not package conformance, launchability, guest realization, or live-target evidence. |
| ACES realization (live) | `cms.management.commands.run_aces_backend_validation`, `cms.aces.validation`, `shared.aces.projections`; `docs/architecture/aces-cutover-evidence-1264.md` (producers #1264, #1569) | `live-manual` | `not-yet-demonstrated` | #1539 must record a deployed-environment `run_aces_backend_validation` run reaching `READY`, a succeeded status, and a non-vacuous redacted runtime snapshot with verified content/account/feature entries, with provider/environment/time. Unit and contract tests do not substitute. |
| Live smoke: built-image stack | `_quality.yml` `stack-smoke` | `blocking` | `not-yet-demonstrated` | #1539 must pin the `stack-smoke` run at the release SHA + conclusion. Scope: built-image smoke has no cloud credentials; it is not deployed-environment or live-cloud smoke and does not imply GCP or ACES coverage. |
| Live smoke: AWS deployed | `_shifter-platform.yml` `post-deploy-smoke` | `advisory` (`continue-on-error`) | `not-yet-demonstrated` | #1539 must record the deploy-workflow `post-deploy-smoke` run + conclusion for the deployed AWS environment. It opens an issue on failure and does not block the deploy; do not infer a blocking smoke gate or GCP coverage from it. |
| Live smoke: GCP deployed | (no deployed-GCP post-deploy smoke gate) | `not-implemented` | `not-yet-demonstrated` | No deployed-GCP post-deploy smoke gate exists. Open gap for the GCP path; #1539 records it as a residual limitation with an owner. |
| Cutover authorization | ADR-024; `docs/architecture/aces-migration-parity-inventory.yaml`; `docs/architecture/aces-cutover-archive-plan-preflight-1238.md`; #1310 (open) | `live-manual` | `not-yet-demonstrated` | The reviewed cutover record produced by #1310 is the locator; #1539 records the exact selector/default change, accepted profile/scope, parity bundle, known gaps, rollback window, and release SHA. A design note or an enabled flag is a prerequisite, not authorization. |
| Rollback | ADR-024 rollback posture; default-off `SHIFTER_ACES_NATIVE_PROVISIONING` binding in `config/_aces_settings.py`; preserved legacy selector/reference path; #1310 (open) | `live-manual` | `not-yet-demonstrated` | The documented rollback rehearsal produced with #1310 is the locator; #1539 records that the release's actual selector restores and validates the named legacy path within the stated window. Toggle existence, `--keep`, cleanup success, or retained legacy files are not rollback proof. |

The three distinct meanings often called "conformance" stay separate: backend
configuration conformance (installation bundle and schema), ADR-039 provider
range-substrate lifecycle conformance, and ACES manifest and profile
conformance. A green result in one is not evidence for either of the others.

## Contradictions and duplication resolved

- Only the three merged native blockers are `captured`. Every other row is
  `not-yet-demonstrated` at the release scope, because no immutable
  release-SHA run or report with an observed conclusion exists for it yet. The
  index states what #1539 must capture rather than asserting an unverified pass.
- Security signal is split by actual posture. Routed SAST, Terraform Checkov,
  gitleaks, and PR-waiting SonarCloud are `blocking`; Trivy, OSV-Scanner, K8s
  Checkov, and the CodeQL upload are `advisory`. No single "security passed"
  label collapses the two.
- Smoke evidence is split into built-image, AWS deployed, and GCP deployed rows
  because their credentials, freshness, and blocking semantics differ. The AWS
  post-deploy smoke's `continue-on-error` posture is recorded rather than hidden.
- Cutover and rollback stay `not-yet-demonstrated` while #1310 is open. The
  default-off ACES flag and preserved legacy code are prerequisites, not tested
  rollback.
- This index restates no gate command, metric, ownership matrix, root inventory,
  backend capability, ACES manifest, parity row, or rollback instruction. It
  points to the canonical producer for each, so there is one source of truth.

## Out of scope (non-release-prerequisite parallel work)

Per #1540 and #1539, the following remain useful but do not block REV1 shipment;
each keeps its own owner and milestone:

- Email delivery durability: #1525 (REV1 quality finding Q1).
- SPA coverage, end-to-end, and browser accessibility: #1526 (Q3), governance
  #713.
- Documentation security tests restored to required CI: #1527 (Q4).
- Canonical current-state architecture handbook: #1531.
- Stabilization sequencing and backlog triage: #1532.

## Boundaries

This index contains only commit, pull-request, run, and report references,
public job and profile identifiers, bounded counts, timestamps, and
conclusions. It carries no tokens, user email, secret references or values,
range identifiers, internal addressing, provider identifiers or payloads,
Terraform state, plan, or output, CTF flags or answers, guest output, or raw
ACES runtime snapshots. It executes on no runner, deploy host, or guest and
requires no new endpoint, workflow permission, or credential.

## Consumed by

The REV1 release-verification gate #1539 reviews this index to confirm that
clean-checkout, Terraform, routed-CI, provider-conformance, live-range-smoke,
and sanitized in-guest ACES evidence are discoverable and correctly scoped for
the supported AWS and GCP paths, and that residual limitations are explicit and
owned. For every `not-yet-demonstrated` row, #1539 captures the immutable
release-SHA run or record and its observed conclusion at release time; a row
stays a residual limitation with an owner until that evidence exists.
