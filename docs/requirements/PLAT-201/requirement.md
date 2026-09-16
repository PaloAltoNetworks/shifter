---
id: PLAT-201
title: "Capacity-Aware Provisioning"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-04-16T22:49:24.290391Z
updated_at: 2026-07-26T23:57:38.478001Z
---

# PLAT-201: Capacity-Aware Provisioning

## Statement

The range provisioning engine shall consume event-level capacity declarations (see CTF-908) to plan resource allocation before spinup, including: per-AMI pre-bake counts, cross-account or cross-cloud resource partitioning, and per-account quota-headroom checks. The engine shall refuse or warn on provisioning requests whose declared capacity exceeds detectable headroom, rather than proceeding and failing during spinup.

## Rationale

CTF-907 defers quota enforcement to the Engine/CMS layer "if needed." Polaris demonstrated the need is real and the concern is broader than static quotas: it is anticipatory planning for shared resources that don't surface in per-range provisioning (Bedrock throughput, NAT bandwidth, SSM concurrency, cross-account IAM capacity). Making the engine capacity-aware reduces operator firefighting and makes event feasibility assessable before participants arrive.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#680` (PLAT-201: Capacity-Aware Provisioning)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/capacity/contract.py` (Closed capacity-admission policy contract)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/capacity/catalog.py` (Deployment-owned partition and metric catalog)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/capacity/demand.py` (Demand derivation including per-AMI pre-bake counts)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/cloud/aws/capacity_inventory.py` (AWS quota-headroom reads with cross-account assume-role)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/cloud/gcp/capacity_inventory.py` (GCP quota-headroom reads via Cloud Monitoring)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/engine/models/_capacity_assessment.py` (Assessment snapshot, event budget, and per-range draw ledger)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/engine/services/_capacity_plan.py` (Engine capacity assessment and reservation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/engine/services/_capacity_admit.py` (Per-range admission draw-down against the event budget)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/scenarios/images.py` (Scenario image projection for pre-bake planning)
- IMPLEMENTS → CONFIG `shifter/shifter_platform/config/_capacity_planning_settings.py` (Capacity catalog and read-identity settings)
- TESTS → TEST `shifter/shifter_platform/tests/shared/capacity/test_contract.py` (Admission policy: outcome precedence, headroom arithmetic, indeterminate rules)
- TESTS → TEST `shifter/shifter_platform/tests/shared/capacity/test_catalog.py` (Catalog strict validation and policy versioning)
- TESTS → TEST `shifter/shifter_platform/tests/shared/capacity/test_demand.py` (Demand scaling and per-AMI pre-bake counts)
- TESTS → TEST `shifter/shifter_platform/tests/shared/cloud/test_capacity_inventory.py` (AWS adapter shape validation and cross-account reads)
- TESTS → TEST `shifter/shifter_platform/tests/shared/cloud/test_capacity_inventory_gcp.py` (GCP adapter parity and protobuf series handling)
- TESTS → TEST `shifter/shifter_platform/tests/engine/test_capacity_plan.py` (Assessment outcomes, overlapping reservations, transaction discipline)
- TESTS → TEST `shifter/shifter_platform/tests/engine/test_capacity_admit.py` (Draw-down idempotence, ledger integrity, release, reconciliation)
- TESTS → TEST `shifter/shifter_platform/tests/engine/test_capacity_plan_degraded.py` (Degraded paths: unmeasurable metrics never read as available headroom)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_capacity_admission_wiring.py` (Refuse-or-warn before spinup on wave and spare-pool paths)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_capacity_draw_wiring.py` (Per-range draws on participant and spare creation paths)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_capacity_helpers.py` (Bounded summaries and never-fatal capacity failures)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_scenario_image_projection.py` (Scenario image projection, shared vs per-participant scope)
