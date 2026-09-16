---
id: PLAT-221
title: "Scenario-Level Egress Allowlist Overrides"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-05-13T16:32:04.586352Z
updated_at: 2026-05-13T16:32:04.586352Z
---

# PLAT-221: Scenario-Level Egress Allowlist Overrides

## Statement

Scenario definitions shall be able to declare additional egress CIDRs or override the platform default allowlist (PLAT-220) for ranges provisioned from that scenario. Scenario-level entries shall compose with platform-level entries (additive by default; explicit override and replacement semantics shall be documented). The platform shall apply the effective allowlist (platform + scenario) at range provisioning time and shall make the effective set inspectable to operators before and after apply.

## Rationale

Scenarios have legitimate, scenario-specific egress needs, a phishing scenario needs reach to a controlled mail target, a malware-analysis scenario needs reach to a sandboxed payload host, a baseline scenario should not silently inherit anything broader than the platform default. Without a scenario-level surface, every author either fights the platform default or works around it via cloud-side hacks. Refines PLAT-220 by surfacing per-scenario egress as first-class composition rather than out-of-band bypass.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#776` (PLAT-221: Scenario-Level Egress Allowlist Overrides)
