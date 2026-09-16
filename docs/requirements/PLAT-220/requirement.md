---
id: PLAT-220
title: "Configurable Range Egress IP Allowlist"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-05-13T16:31:56.853436Z
updated_at: 2026-05-25T23:52:03.781550Z
---

# PLAT-220: Configurable Range Egress IP Allowlist

## Statement

The platform shall accept configuration for allowlisted egress IP ranges (CIDR blocks) that apply to range network egress. The allowlist shall be a first-class platform capability, defined declaratively, applied uniformly across supported cloud backends (AWS, GCP), and enforceable without bespoke per-scenario scripting. The platform default behavior in the absence of an explicit allowlist (deny-all, allow-all, or status-quo) shall be documented, and the configuration mechanism shall not be coupled to any single cloud's native firewall syntax.

## Rationale

Range egress is currently configured implicitly through cloud-specific firewall rules embedded in Terraform and Helm. There is no platform-level abstraction an operator can point at to say "ranges may reach these CIDRs and only these." Without a first-class allowlist surface, scenario authors and operators cannot reason about egress policy independently of cloud plumbing, and audit / compliance work has no single source of truth. This requirement establishes the platform-level configuration surface that subsequent capabilities (scenario overrides, composable sets, admin UI, RBAC) refine.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#775` (PLAT-220: Configurable Range Egress IP Allowlist)
- IMPLEMENTS → PULL_REQUEST `834` (PLAT-220: configurable range egress IP allowlist)
- IMPLEMENTS → CODE_FILE `shifter/installation/range_egress.py`
- IMPLEMENTS → CODE_FILE `shifter/installation/loader.py`
- IMPLEMENTS → CODE_FILE `platform/terraform/modules/range/vpc/variables.tf`
- IMPLEMENTS → CODE_FILE `platform/terraform/gcp/modules/platform-core/main.tf`
- IMPLEMENTS → CODE_FILE `platform/terraform/gcp/modules/platform-core/variables.tf`
- IMPLEMENTS → ADR `ADR-017`
- DOCUMENTS → DOCUMENTATION `docs/architecture/range-egress-ip-allowlist.md`
- TESTS → TEST `shifter/installation/tests/test_range_egress.py`
- TESTS → TEST `shifter/installation/tests/test_loader.py`
- IMPLEMENTS → GITHUB_ISSUE `775`
