---
id: GEN-2003
title: "Conformance with PANW open-source contributor rules"
status: ACTIVE
type: CONSTRAINT
priority: MUST
wave: 1
created_at: 2026-05-12T16:38:05.081640Z
updated_at: 2026-05-19T07:24:40.283404Z
---

# GEN-2003: Conformance with PANW open-source contributor rules

## Statement

The repository SHALL conform to the rules published in [`PaloAltoNetworks/.github/docs/community-rules.md`](https://github.com/PaloAltoNetworks/.github/blob/master/docs/community-rules.md). Specifically:

1. **SUPPORT.md**, present at repository root, containing one of the two legal-approved canonical support messages (Community Supported or TAC Supported) verbatim. Shifter MUST use the Community Supported wording.
2. **SECURITY.md**, present at repository root with the `<!-- BEGIN PANW SECURITY.MD V0.0.1 BLOCK -->` block from `PaloAltoNetworks/.github/SECURITY.md` verbatim, OR absent locally and inheriting the org-level template via the `PaloAltoNetworks/.github` cascade.
3. **CODE_OF_CONDUCT.md**, present at repository root with the Contributor Covenant v1.4 text from `PaloAltoNetworks/.github/CODE_OF_CONDUCT.md` verbatim, OR absent locally and inheriting the org-level template.
4. **CONTRIBUTING.md**, present at repository root with the PANW org template as the body. Shifter-specific addenda are allowed (build commands, ADR enforcement, towncrier convention, base-PR-off-`dev` policy) but the org-template prose MUST appear verbatim.
5. **README.md**, follows the section structure of [`PaloAltoNetworks/.github/docs/README.example.md`](https://github.com/PaloAltoNetworks/.github/blob/master/docs/README.example.md) (Summary, Getting Started, Prerequisites, Installing, Usage, Support, Deployment, Running the tests, Built With, Contributing, Versioning, Maintainers, Acknowledgments). Sections MAY be reordered or augmented; the listed sections MUST be present in some form.
6. **License**, MIT (the 2025-era PANW OSS default per the community-rules doc), or other PANW-approved open-source license from `choosealicense.com`.
7. **No CLA bot, no DCO**, PANW org policy is no CLA, no DCO; the repository MUST NOT add either.
8. **Conventional-commit PR titles**, PR titles SHALL match the conventional-commit shape (`type: subject` with subject starting lowercase), so towncrier and release-drafter conventions stay aligned. Enforced via `.github/workflows/pr-title-lint.yml`.
9. **Repository topics**, at least one product topic from PANW's approved list (`cortex`, `pan-os`, etc.) MUST be applied to the repo via GitHub Settings → Topics. (Note: not enforced by repo content; recorded here so it's visible during audits.)

## Rationale

PANW publishes a documented set of community rules for any repository under the `PaloAltoNetworks` org. Shifter is moving to that org; conforming proactively avoids per-repo retrofit churn and matches the polish-tier of every actively maintained PANW OSS repo. PR PaloAltoNetworks/shifter#1204 (#762) + cleanup PaloAltoNetworks/shifter#1206 implement most of the items above; this requirement encodes the contract so future drift is caught and so the conformance posture is auditable when PSIRT/OSPO reviews the eventual `PaloAltoNetworks/shifter` repo.

## Traceability

- IMPLEMENTS → DOCUMENTATION `SECURITY.md` (PANW org SECURITY.md V0.0.1 block, verbatim, satisfies clause 2)
- IMPLEMENTS → DOCUMENTATION `SUPPORT.md` (Community Supported canonical text from PANW community-rules, satisfies clause 1)
- IMPLEMENTS → DOCUMENTATION `CODE_OF_CONDUCT.md` (Contributor Covenant v1.4 from PANW org, satisfies clause 3)
- IMPLEMENTS → DOCUMENTATION `CONTRIBUTING.md` (PANW org CONTRIBUTING.md verbatim + Shifter-specific addendum, satisfies clause 4)
- IMPLEMENTS → DOCUMENTATION `README.md` (README structure following PANW README.example.md, satisfies clause 5)
- IMPLEMENTS → CODE_FILE `.github/workflows/pr-title-lint.yml` (PR title lint enforcing conventional-commit shape, satisfies clause 8)
- IMPLEMENTS → DOCUMENTATION `LICENSE` (License file (clause 6, currently "all rights reserved"; pending PANW-legal swap to MIT))
