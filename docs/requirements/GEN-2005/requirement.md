---
id: GEN-2005
title: "Participant-control realization and integrity"
status: DRAFT
type: CONSTRAINT
priority: MUST
wave: 2
created_at: 2026-09-06T00:00:00Z
updated_at: 2026-09-06T00:00:00Z
---

# GEN-2005: Participant-control realization and integrity

## Statement

When Shifter admits a RAES participant-control profile, it MUST satisfy all of
the following obligations:

1. Consume the exact released RAES semantics, provider protocol, runtime and
   conformance contracts through `shared.raes`. Bind profile, mechanism,
   provider implementation and configuration identities and digests explicitly.
   Scenario or participant content MUST NOT select executable code. Shifter
   MUST NOT duplicate portable DTOs, control semantics or conformance verdicts.
2. Resolve the admitted participant, controller, episode, run, declared world,
   authority and current range generation from trusted product and compiled
   scenario bindings. Keep platform, tenant, credential, service and isolation
   integrity outside that world. An integrity failure invalidates or fails the
   realization; it MUST NOT be relabeled as an in-world adversarial occurrence.
3. Compose selected mechanisms through the released RAES rules at the same
   exact context and history cut. Mandatory missing, stale, unknown,
   unsupported, failed, weakened, abstaining or conflicting results MUST NOT
   authorize an effect. Preserve distinct approval, authorization and execution
   decisions, explicit effect dependencies and durable finite causal budgets.
4. Mediate every admitted consequential action through the owning authenticated
   and authorized service and backend path. Bind any required explicit approval
   to the exact proposal and current authority. Fence actual invocation against
   stale generation, authority and ownership; task acceptance or a result-applier
   fence alone MUST NOT establish this guarantee. Reject unsupported targets or
   guarantee strengths before any prohibited world or backend effect.
5. Commit control history, provider-state transitions, causal budgets and effect
   claims through the released authoritative runtime. Correlate native approval,
   Engine operations, audit and readback without creating a shadow runtime or
   duplicating execution truth. Retry and replay MUST preserve logical effect
   identity. Partial and indeterminate outcomes require readback before a retry
   that could repeat an effect; interruption or revocation MUST NOT imply rollback.
6. Apply audience and sink policy to decisions, reasons, approvals, receipts and
   audit evidence as well as participant content. Preserve bounded, digest-bound
   references and limitations without exposing credentials, raw rejected content
   or backend-private state through portable records, logs, events or errors.
7. Advertise support only for the exact installed and admitted mechanism,
   profile, provider, configuration, participant/world and deployment envelope
   supported by released RAES conformance and real service/provider readback.
   Manifest presence, unit tests or another backend's results MUST NOT substitute
   for realization evidence or imply mechanism, guarantee or fidelity parity.

## Rationale

Portable RAES authority does not select a Shifter mechanism or establish its
organizational authority, resource coverage or platform integrity. Shifter needs
an independently selected, measurable realization contract that composes with
its existing CTF, CMS, Engine, audit and deployment ownership boundaries.

ADR-058 specifies the initial design. This requirement remains DRAFT because
issue #1967 supplies design authority, not a runtime mechanism. Issues #1968
and #1969 respectively own implementation and real-boundary proof. Activation
and implementation/test links must be reviewed with the delivery that actually
satisfies these clauses; no runtime or conformance claim is made here.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `1967` (Participant-control mechanism and realization design)
- DOCUMENTS → GITHUB_ISSUE `1968` (Selected mechanism implementation tracking)
- DOCUMENTS → GITHUB_ISSUE `1969` (Real-boundary proof tracking)
- DOCUMENTS → ADR `docs/adr/index.yaml` (ADR-058)
- DOCUMENTS → DOCUMENTATION `docs/architecture/raes-participant-control-realization-envelope-1967.md` (Selected realization envelope and claim/evidence contract)
- DOCUMENTS → SPEC `https://github.com/OpenRAE/rae/blob/ebb70a34b8e7d1cc8964c443841ae57e12ed1014/docs/research/modular-participant-control/composition.md` (Accepted portable PC-01 through PC-15 authority)
