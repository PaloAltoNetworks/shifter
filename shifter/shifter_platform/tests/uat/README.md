# UAT Suite Definitions

This directory contains machine-readable UAT suite definitions.

These files are intentionally not executable test code. They define:

- scope
- actors
- environment prerequisites
- ordered test cases
- assertions
- required evidence
- adjacent checks to run when a failure is observed

The intent is to let an external harness or agent map the protocol onto tools
such as Playwright, `curl`, `gcloud`, `kubectl`, and GitHub Actions inspection
without redesigning the suite each time.

## Format

Each suite definition should include:

- suite metadata
- environment and secret requirements
- supported tools
- actor definitions
- ordered cases with:
  - `id`
  - `title`
  - `actor`
  - `surface`
  - `preconditions`
  - `steps`
  - `assertions`
  - `evidence`
  - `adjacent_checks`

## Current Suites

- `mission_control_gcp_dev.yaml`
  UAT protocol for the current GCP Mission Control deployment.
