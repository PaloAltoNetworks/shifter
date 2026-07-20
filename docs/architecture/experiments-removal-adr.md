# ADR-027: Remove legacy experiments in favor of a future ACES-backed design

## Status

Accepted.

## Date

2026-07-01

## Context

The legacy `cms.experiments` feature was built as an experiment authoring and
execution workflow, but it never reached an end-to-end alpha:

- No executor consumes `EXPERIMENT_PAYLOAD`.
- The provisioner image has no `experiment` command/subcommand.
- The command rendering path carried AWS-only assumptions.
- The feature was already hidden and disabled by default through
  `EXPERIMENTS_ENABLED`.
- Issue #1195 recorded the product decision to remove it because it is
  superseded by the pending ACES migration.

Keeping the legacy code would preserve callable dead paths, deployment
configuration, and tests for a feature that cannot complete a run on any cloud.

## Decision

Shifter removes the legacy experiments feature instead of completing or
redesigning it in place.

The removal includes:

- The `cms.experiments` Django app, models, services, views, templates,
  websocket consumers, event handlers, orchestrator, upload helpers, and tests.
- Mission Control script/file screens and APIs that existed only to feed
  experiment scripts.
- Experiment routes, navigation entries, API routes, websocket routes, queue
  configuration, runtime environment keys, GCP Pub/Sub subscriptions, workflow
  path filters, and logging configuration.
- Legacy experiment specs and UAT artifacts.
- Legacy database tables and app metadata through a CMS-owned cleanup
  migration.

Future experiment capability must start from an ACES-backed design and an
accepted replacement contract. It must not reuse the deleted `cms.experiments`
runtime path or revive the removed feature flag as a shortcut.

## Consequences

- Existing legacy experiment rows and uploaded experiment-script records are
  intentionally dropped by the cleanup migration. There is no supported
  rollback data path for this half-built feature.
- Range event delivery remains durable for range projections, but experiment
  run reconciliation and experiment event bridging are removed with the app.
- ACES migration planning should treat legacy experiments as an archive/delete
  surface rather than current runtime authority.
- If a future ACES experiment runner is built, it needs new product,
  security, data-retention, and operator runbook review.

## Non-Goals

- This ADR does not implement ACES experiment-core.
- This ADR does not add a replacement executor, artifact collector, UI, API,
  queue, or schema.
- This ADR does not remove current CMS scenario authoring, CTF behavior,
  Mission Control range/terminal behavior, or engine/provisioner range
  lifecycle behavior.
