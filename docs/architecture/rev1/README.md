# Shifter Platform Review 1

## Review baseline

- Repository: `Brad-Edwards/shifter`
- Baseline: `origin/dev` at `cb3668ea66de45bdab66933c675f944357e60943`
- Review date: 2026-07-11
- Scope: platform architecture, implementation quality and efficiency,
  consistency, modularity, reuse, security, tests, and the planned roadmap
- Explicit constraint: improve the existing platform without expanding its remit

This review assessed both the code at the baseline and the direction represented
by 417 open issues, 12 open milestones, the Ground Control requirement set, the
ADR registry, and the ACES migration program. Intentionally vulnerable scenario
content was excluded from product-security findings.

## Executive judgment

Shifter has a stronger engineering control plane than its maturity might suggest.
The ADR registry is executable, the main Django API fails closed by default,
classified application layers pass import contracts, the Python estate is well
tested, and the ACES migration uses a sensible parallel-path and rollback model.
The current problem is not an absence of architecture.

The main risk is that implementation and roadmap concurrency are outrunning the
boundaries the project has defined. The platform currently combines a mutable
Django schema contract with a separately deployed provisioner, permissive cloud
and Kubernetes workload identities, an incompletely versioned ACES process
boundary, and several adjacent migrations. Those risks are amplified by a
417-issue backlog, 186 architecture documents (163 issue preflights), more than
2,100 commits since 2026-04-01, and effective single-maintainer ownership.

Overall assessment: **sound direction, strong local controls, but not yet a
stable corporate/open-source platform boundary**. The right next move is a
stabilization sequence, not a broader feature program.

| Dimension | Assessment | Main reason |
| --- | --- | --- |
| Architectural soundness | Caution | Good ADRs and service intent; unstable process/data and provider boundaries remain |
| Implementation quality | Caution | Strong typing/linting and many focused tests; large orchestration and infrastructure surfaces remain |
| Consistency/modularity/reuse | Caution | Enforced for classified layers, incomplete across all installed first-party apps |
| Security | High risk until fixed | One authorization escalation plus broad GCP/Kubernetes and supply chain privileges |
| Test quality | Caution | Strong unit volume; production database, browser, async-delivery, Terraform, and live-boundary fidelity need work |

## Highest-priority findings

1. **The identity-to-organizer boundary does not preserve authoritative
   privilege assignment.** Exploit-level details are withheld from this public
   report under `SECURITY.md`; the role mapping and existing memberships require
   private remediation and audit.
2. **The ACES process boundary can silently accept incompatible or partial
   plans.** The consumer does not enforce the producer version and silently
   ignores unknown resources and unresolved network references.
3. **GCP workload identities and Kubernetes Secret mutation rights exceed the
   application boundaries they are intended to support.** A portal or worker
   compromise has project- or namespace-wide consequences.
4. **Build provenance is weaker than runtime hardening.** Credentialed workflows
   use mutable action tags, container bases float, and downloaded provisioning
   tools are not consistently checksum or signature verified.
5. **The provisioner still integrates through Django-owned tables and
   migration-managed grants.** Existing issue #478 is the correct remediation
   and should gate further expansion of that integration surface.
6. **The roadmap changes too many adjacent contracts concurrently.** ACES,
   backend bundles, live-fire isolation, Workspaces/API, SPA phase 2, and AWS
   cleanup should be sequenced behind explicit stabilization gates.
7. **The main test suite does not exercise the production database.** CI starts
   PostgreSQL but `TESTING=1` forces SQLite for 4,739 tests; only one dedicated
   concurrency module is rerun on PostgreSQL.
8. **CTF email status is not durable or truthful.** An in-process thread pool
   can lose work on restart, while announcement state is advanced before
   recipient delivery succeeds.

## Proposed milestones

The proposed GitHub milestones and issues are catalogued in
[roadmap.md](roadmap.md). They deliberately reuse existing issues where the
backlog already describes the work. New `REV1` issues cover only gaps found by
this review.

1. **REV1.1 Security and Trust Boundaries**: close privilege-escalation,
   workload-identity, Secret-integrity, provenance, browser-policy, and OIDC
   bootstrap gaps.
2. **REV1.2 Contract and Runtime Architecture**: make ACES transport fail
   closed, complete layer classification, and use existing issues to stabilize
   the provisioner and provider selection boundaries.
3. **REV1.3 Maintainability and Verification**: establish a current architecture
   handbook, make verification reproducible, and reduce roadmap/backlog
   concurrency before additive programs proceed.

## Detailed reports

- [Architecture and roadmap](architecture.md)
- [Security](security.md)
- [Implementation and tests](quality-and-testing.md)
- [Milestones and issue map](roadmap.md)

## Verification performed

- `python3 scripts/adr_guard/adr_guard.py --all --level ci`: passed all checks.
- `uv run lint-imports --config ../../.importlinter`: six contracts kept.
- `uv run ruff check .`: passed for `shifter_platform`.
- `uv run ruff format --check .`: 729 files already formatted.
- GitHub checks on the baseline commit: relevant platform, JavaScript,
  migration-proof, and SonarCloud checks succeeded; path-irrelevant jobs skipped.
- Django default suite: 4,739 passed in 214.9 seconds; production-only line
  coverage was 88.05% after excluding self-covering test modules.
- Provisioner unit suite: 1,063 passed and eight skipped in 159 seconds.
- Excluded documentation suite: 25 passed in 7.83 seconds when run separately.

The review did not perform live AWS/GCP/Kubernetes authorization simulation,
DAST, authenticated browser testing, event load testing, or destructive range
validation. These limits are material and are reflected in the proposed work.
