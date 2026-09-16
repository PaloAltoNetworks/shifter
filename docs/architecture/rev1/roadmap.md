# REV1 Milestones And Issue Map

## Principles

- Fix security and correctness boundaries before expanding features.
- Reuse existing issues where they already describe the work.
- Keep CyberScript authoritative until ACES parity and rollback gates pass.
- Do not use Workspaces, SPA, or backend programs to expand product remit during
  stabilization.
- Close or rescope stale backlog items instead of preserving them indefinitely.

## REV1.1 Security and Trust Boundaries

Milestone: [REV1.1 Security and Trust Boundaries](https://github.com/Brad-Edwards/shifter/milestone/29)

**Exit criterion:** no user-controlled identity field grants organizer/admin
authority; application and build identities have least privilege; privileged
artifacts have verifiable provenance; browser and OIDC bootstrap policy is
explicit and tested.

New issues:

- [#1516 REV1 Security: separate self-service identity from organizer authorization](https://github.com/Brad-Edwards/shifter/issues/1516)
- [#1517 REV1 Security: scope GCP workload identities to named resources](https://github.com/Brad-Edwards/shifter/issues/1517)
- [#1518 REV1 Security: isolate provisioner Job and Secret mutation privileges](https://github.com/Brad-Edwards/shifter/issues/1518)
- [#1519 REV1 Security: establish verifiable build and deployment provenance](https://github.com/Brad-Edwards/shifter/issues/1519)
- [#1520 REV1 Security: add a staged browser security policy baseline](https://github.com/Brad-Edwards/shifter/issues/1520)
- [#1521 REV1 Security: require verified OIDC email before administrator bootstrap](https://github.com/Brad-Edwards/shifter/issues/1521)

Required existing issues, all assigned to this milestone:

- Identity and abuse controls: #1206 and #322.
- Range and credential isolation: #1171, #1295, #1377, and #343.
- Edge and CI security: #201, #247, and #1498.

Exit verification: [#1537](https://github.com/Brad-Edwards/shifter/issues/1537).
All 15 implementation issues block #1537 through native GitHub issue
dependencies.

## REV1.2 Contract and Runtime Architecture

Milestone: [REV1.2 Contract and Runtime Architecture](https://github.com/Brad-Edwards/shifter/milestone/30)

**Exit criterion:** the ACES process boundary is versioned and rejects partial
plans; every first-party package is architecture-classified; provisioner and
provider-selection boundaries have an accepted implementation sequence.

New issues:

- [#1522 REV1 ACES: make the provisioning plan transport versioned and fail closed](https://github.com/Brad-Edwards/shifter/issues/1522)
- [#1523 REV1 Architecture: classify every first-party package and extract the audit port](https://github.com/Brad-Edwards/shifter/issues/1523)

Required existing issues, all assigned to this milestone:

- Persistence and domain contracts: #478 and #524.
- Presentation/service ownership: #994 and #991.
- Backend bundle authority: #721, #726, #728, #729, #1322, and #1323.
- ACES realization and evidence: #1477, #1478, #1479, and #1264.

Exit verification: [#1538](https://github.com/Brad-Edwards/shifter/issues/1538).
The repository-wide gate boundary and current RAES naming constraints are
recorded in
[`rev1-contract-runtime-exit-preflight-1538.md`](../rev1-contract-runtime-exit-preflight-1538.md).
The reviewed exit-verification evidence bundle is
[`rev1-contract-runtime-exit-1538.md`](../rev1-contract-runtime-exit-1538.md).
Only #728, #729, #1562, #1566, #1567, and #1569 are native blockers for #1538.
The remaining REV1.2 remediation and the REV1.1 security gate continue in
parallel and are not runtime-verification prerequisites.

Issue #530 should be closed or respecified because CTF is already in the current
import boundary checks; its broader missing requirement is whole-platform
classification.

## REV1.3 Maintainability and Verification

Milestone: [REV1.3 Maintainability and Verification](https://github.com/Brad-Edwards/shifter/milestone/31)

**Exit criterion:** contributors can understand the current system without
reconstructing it from preflights; clean-checkout verification matches CI;
coverage and live-boundary evidence have explicit policies; the roadmap has a
small, ordered stabilization set.

New issues:

- [#1524 REV1 Testing: exercise production PostgreSQL semantics in CI](https://github.com/Brad-Edwards/shifter/issues/1524)
- [#1525 REV1 Reliability: replace fire-and-forget email with durable delivery](https://github.com/Brad-Edwards/shifter/issues/1525)
- [#1526 REV1 Frontend: enforce SPA coverage, E2E, and browser accessibility gates](https://github.com/Brad-Edwards/shifter/issues/1526)
- [#1527 REV1 Testing: restore documentation security tests to required CI](https://github.com/Brad-Edwards/shifter/issues/1527)
- [#1528 REV1 Infrastructure: validate every Terraform root on pull requests](https://github.com/Brad-Edwards/shifter/issues/1528)
- [#1529 REV1 Testing: make clean-checkout commands and quality metrics trustworthy](https://github.com/Brad-Edwards/shifter/issues/1529)
- [#1530 REV1 Testing: enforce production-path ownership in routed CI](https://github.com/Brad-Edwards/shifter/issues/1530)
- [#1531 REV1 Documentation: publish a canonical current-state architecture handbook](https://github.com/Brad-Edwards/shifter/issues/1531)
- [#1532 REV1 Program: sequence stabilization gates and triage the open backlog](https://github.com/Brad-Edwards/shifter/issues/1532)

Required existing issues, all assigned to this milestone:

- Module and automation maintainability: #561, #682, #683, #686, #688, #689,
  #692, and #998.
- Runtime performance and functional evidence: #846, #983, #987, #988, and
  #615.
- Notification delivery prerequisites: #525 and #1460.
- Accessibility governance: #713.
- PostgreSQL/concurrency correctness: #997, #1135, #1137, #1138, #1140,
  #1144, #1145, and #1147.
- ACES cutover and cleanup: #1310, #1311, #1312, and #1313.

Evidence integration: [#1540](https://github.com/Brad-Edwards/shifter/issues/1540).
The nine new remediation issues block #1540.

Exit verification: [#1539](https://github.com/Brad-Edwards/shifter/issues/1539).
The REV1.2 gate, all 37 implementation issues, and #1540 directly block #1539.
The nine new issues also block #1540 so the integrated evidence cannot be
declared complete before its component evidence exists.

## Program sequence

1. Complete the REV1.1 implementation issues and #1537 on the parallel security
   track.
2. Complete #728, #729, #1562, #1566, #1567, and #1569, then close #1538 from
   their reviewed contract, runtime, and live-validation evidence.
3. Continue the remaining REV1.2 remediation in parallel without promoting it
   to a #1538 prerequisite.
4. Complete the REV1.3 implementation and evidence-integration issues; #1538
   blocks the controlled cutover and #1539.
5. Perform controlled ACES cutover and cleanup in the enforced order #1310 ->
   #1311 -> #1312.
6. Resume additive Workspaces/API and SPA phase 2 work only after #1539 closes.

The sequence is intentionally independent of calendar estimates. Each milestone
exits on evidence, not on elapsed time or issue count.
