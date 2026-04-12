# Testing

This section defines how Shifter is verified from the outside in.

The intent is not to duplicate unit and integration tests. The intent is to
capture the operator-facing and user-facing checks that prove a deployed
environment is actually usable.

## Principles

- Treat deployed behavior as the system under test.
- Capture evidence, not just pass or fail.
- When one user-visible defect appears, check the adjacent surface instead of
  assuming the failure is isolated.
- Keep the protocol structured enough that it can be moved into a dedicated UAT
  harness later without rewriting the test design.

## Artifacts

- [Mission Control GCP Dev UAT](mission-control-gcp-dev-uat)
  Human-readable audit protocol for the current GCP environment and Mission
  Control surface.

## Machine-Readable Suite Definitions

The protocol is mirrored in `shifter/shifter_platform/tests/uat/`.

These files are not executable test code. They are structured suite definitions
for agents or future UAT tooling that can drive Playwright, `curl`, `gcloud`,
`kubectl`, and other external tooling.
