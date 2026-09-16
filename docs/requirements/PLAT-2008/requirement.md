---
id: PLAT-2008
title: "ACES-native provisioning is a feature-flagged parallel path; cyberscript stays live"
status: DRAFT
type: CONSTRAINT
priority: MUST
wave: 3
created_at: 2026-07-08T07:05:42.432045Z
updated_at: 2026-07-08T07:05:42.432045Z
---

# PLAT-2008: ACES-native provisioning is a feature-flagged parallel path; cyberscript stays live

## Statement

The ACES-native provisioning path shall be built as a parallel implementation gated by a single feature flag (SHIFTER_ACES_NATIVE_PROVISIONING, default off). With the flag off, behaviour shall be byte-identical to today: ACES catalog entries remain non-launchable and the existing cyberscript scenario -> RangeSpec -> hydrate -> interpret -> provisioner path is unchanged and authoritative. The ACES-native path shall not modify or route through cyberscript hydration, RangeSpec/InstanceSpec, or the existing create_range body; it may only add parallel modules and additive, flag-gated branches. This holds until an explicit, separately authorized cutover flips the switch (ADR-024 parity-gated parallel cutover).

## Rationale

The overriding goal is a fully conformant ACES core with cyberscript deprecated after a proven parallel cutover. Building the ACES path in parallel behind a flag keeps production (cyberscript) live and untouched, makes the new path independently testable, and prevents cyberscript path-dependencies from leaking into the ACES layer or vice versa. This is the concrete instance of ADR-024 for the provisioning surface.
