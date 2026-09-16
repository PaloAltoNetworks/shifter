---
id: PLAT-2007
title: "ACES-native provisioning spec (locked neutral contract)"
status: DRAFT
type: INTERFACE
priority: MUST
wave: 3
created_at: 2026-07-08T07:05:21.044293Z
updated_at: 2026-07-08T07:05:21.044293Z
---

# PLAT-2007: ACES-native provisioning spec (locked neutral contract)

## Statement

Shifter shall define an ACES-native, cyberscript-free provisioning specification (ProvisioningSpec) that losslessly represents the provisioning-only topology of a compiled ACES ProvisioningPlan: compute nodes (os family, count, cpu/memory resources, image reference, services, network membership) and networks (cidr, gateway, isolation, ACL rules). The spec shall be a versioned, validated contract with stable invariant identifiers (ACESPS-*) and an invariant-to-check inventory, shall contain no cyberscript concepts (no scenario_id, no role enum, no os_type enum), and shall be the sole persisted artifact the engine and provisioner consume for the ACES-native path, consumed without importing any ACES SDL package (aces_* imports remain confined to shared/aces per ADR-024).

## Rationale

The merged #1262 adapter discards the compiled ACES topology and hydrates a pre-authored cyberscript scenario by scenario_ref, making the ACES path depend on cyberscript (contamination). A neutral, lossless, locked spec is the ADR-024 seam that lets the engine/provisioner realize a genuine ACES topology while keeping ACES semantics free of cyberscript's RangeSpec kernel (scenario_id/role/os_type). Locking it concentrates scarce review on a small stable surface per contract-locked development (ADR-087).
