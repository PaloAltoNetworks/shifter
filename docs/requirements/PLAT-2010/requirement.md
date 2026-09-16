---
id: PLAT-2010
title: "Shifter ACES RuntimeTarget provisioning backend (real topology interpret)"
status: DRAFT
type: FUNCTIONAL
priority: MUST
wave: 3
created_at: 2026-07-08T07:06:04.047594Z
updated_at: 2026-07-08T07:06:04.047594Z
---

# PLAT-2010: Shifter ACES RuntimeTarget provisioning backend (real topology interpret)

## Statement

Shifter shall implement the ACES Provisioner protocol (validate(plan)->diagnostics, apply(plan,snapshot)->ApplyResult) as a RuntimeTarget backend that faithfully interprets a compiled ACES ProvisioningPlan into the ProvisioningSpec, reading node resources (cpu/memory), image source, network cidr/gateway, and ACLs, rather than requiring or consuming a scenario_ref. validate/apply shall funnel through a single pure interpret step (no I/O), fail closed with typed bounded diagnostics on any plan term outside the declared ProvisionerCapabilities envelope, and never dispatch on an error. On a valid plan, apply shall dispatch provisioning through an injected port (keeping shared free of cms/engine per ADR-024), write an operation_receipt sidecar record keyed by request_id, and return an ApplyResult with non-empty changed_addresses and a PROVISIONING RuntimeSnapshot. The prior scenario_ref passthrough shall be removed.

## Rationale

This replaces the #1262 passthrough (which discards ram/cpu/source/cidr/acls and depends on cyberscript scenarios) with a real RuntimeTarget backend mirroring the aces_backend_libvirt / LilRAE (formerly APTL) reference pattern, so a genuine ACES topology drives Shifter provisioning. The injected dispatch port preserves the ADR-024 import boundary; the receipt/snapshot make the backend conformance-observable.
