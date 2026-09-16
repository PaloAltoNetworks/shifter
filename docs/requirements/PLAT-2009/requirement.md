---
id: PLAT-2009
title: "ACES backend conformance is the primary oracle (fixture + live, no vacuous pass)"
status: DRAFT
type: NON_FUNCTIONAL
priority: MUST
wave: 3
created_at: 2026-07-08T07:05:51.695926Z
updated_at: 2026-07-08T07:05:51.695926Z
---

# PLAT-2009: ACES backend conformance is the primary oracle (fixture + live, no vacuous pass)

## Statement

The Shifter ACES RuntimeTarget backend shall be verified by the ACES-owned conformance suite as its primary oracle: (1) the existing provisioning-only fixture gate (run_fixture_suite) shall stay green; (2) a live target probe (run_target_conformance, profile PROVISIONING_ONLY) shall drive the backend through the ACES RuntimeManager/RuntimeControlPlane and shall fail on a vacuous pass, it shall require a non-empty changed_addresses set and at least one PROVISIONING snapshot entry. All backend diagnostics shall be bounded, single-line, and free of realization detail (no terraform/ssm/ami/cidr/subnet/secret/password substrings). Conformance logic shall be consumed from aces_conformance, never reimplemented in Shifter code.

## Rationale

Contract-locked development makes the conformance suite the enforcement that converts the backend contract from documentation into a machine-checked, non-vacuous guarantee (ADR-087). The live probe is the anti-gaming control against a backend that schema-validates but never realizes anything; sanitization keeps conformance output safe for CI/review threads.
