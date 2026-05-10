# Root-Configured Backend Bundles

Status: planning, constrained by ADR-011

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1109>

Current-state inventory:
[Branch Routing and Provider Coupling Inventory](branch-routing-provider-coupling-inventory.md)

## Context

Shifter currently mixes runtime provider seams with branch-targeted deployment
behavior. The application already has useful cloud adapter boundaries, but the
public deployment model is still hard to explain: branch names imply provider
and environment intent, while Terraform, Helm, generated env files, and Django
settings each carry part of the final deployment shape.

That model is workable for a controlled internal deployment, but it is a poor
fit for an OSS repository. Users should be able to choose the backend they want
and validate that choice from a single installation contract.

Pulumi is not part of the target architecture. Existing Pulumi-related names
should be treated as legacy compatibility names unless an implementation issue
explicitly migrates them.

## Recommendation

Shifter OSS should use a root-configured backend bundle model:

```text
root config -> selected backend bundle -> generated runtime, infra, validation, and deploy behavior
```

The public model should be:

```yaml
backend: aws
deployment:
  name: shifter
  domain: shifter.example.com
```

Internally, a backend bundle may decompose into capability adapters for identity,
storage, queueing, task execution, secrets, infrastructure, and range execution.
That decomposition should remain an implementation detail unless an advanced
configuration mode is deliberately introduced later.

## Architecture Principles

- One root config is authoritative for backend selection and deployment-level
  settings.
- A backend is the OSS unit of choice. Users select `aws`, `gcp`, `local`, or a
  future backend, not a mix of low-level capabilities.
- Branch names must not be architectural deployment selectors.
- Backend bundles own their required settings, generated outputs, validation
  checks, infrastructure entrypoints, health checks, and setup docs.
- Runtime code should select adapters from validated backend configuration, not
  from branch routing or scattered environment assumptions.
- Shared contracts remain under `shared`, and cross-layer access continues to go
  through service boundaries.
- Existing AWS and GCP behavior should migrate through compatibility paths that
  preserve current security controls.

## Draft Requirements

These requirements have been created in Ground Control as `DRAFT` requirements.
They should remain `DRAFT` while the architecture is reviewed and transition to
`ACTIVE` only when implementation starts.

| UID | Title | Type | Priority | Statement |
| --- | --- | --- | --- | --- |
| `PLAT-2001` | Root installation configuration | Functional | MUST | Shifter must have one authoritative root installation configuration that selects the backend bundle and supplies deployment-level settings used to derive runtime, infrastructure, and validation behavior. |
| `PLAT-2002` | Backend bundles are the OSS backend selection unit | Constraint | MUST | OSS users must choose a complete backend bundle rather than composing low-level provider capabilities in the default setup path. |
| `PLAT-2003` | Backend bundle contract | Interface | MUST | Each backend bundle must expose a stable machine-readable contract for required settings, generated outputs, infrastructure entrypoints, validation checks, health checks, and documentation. |
| `PLAT-2004` | Branch-independent deployment targeting | Constraint | MUST | Deployment target selection must come from explicit configuration or invocation, not from repository branch names. |
| `PLAT-2005` | Backend-derived runtime configuration | Functional | MUST | Django, workers, and provisioner processes must derive provider and capability adapter selection from validated backend configuration. |
| `PLAT-2006` | AWS/GCP compatibility and security preservation | Non-functional | MUST | Migration of existing AWS and GCP support must preserve current security controls, guardrails, and operational safety unless an ADR records an intentional change. |
| `GEN-2001` | Standalone OSS deployment scope | Constraint | MUST | This repository must model one standalone Shifter deployment and avoid cross-install orchestration concepts in the OSS app model. |
| `GEN-2002` | Backend-aware setup and validation UX | Functional | SHOULD | Users should be able to initialize, configure, and validate their selected backend before applying infrastructure or starting the application. |

## ADR Status

`ADR-011` accepts the root-configured backend bundle direction and supersedes
the branch-routing portions of `ADR-005`.

Follow-on implementation should preserve the adapter seam rule in `ADR-005-R1`,
keep identity provider details behind the `ADR-009` auth seam, and update ADR
evidence only when corresponding files change.

## Issue Map

- #1110 Draft requirements and ADR for root-configured backend bundles.
- #1111 Inventory branch routing and provider coupling. See
  [Branch Routing and Provider Coupling Inventory](branch-routing-provider-coupling-inventory.md).
- #1112 Define root installation config schema.
- #1113 Define backend bundle contract and registry.
- #1114 Derive runtime configuration from selected backend bundle.
- #1115 Add backend-aware setup and doctor validation UX.
- #1116 Migrate AWS support into a backend bundle.
- #1117 Migrate GCP support into a backend bundle.
- #1118 Replace branch-targeted deployment docs and CI routing.
- #1119 Define initial local backend scope.

## Suggested Sequence

1. Use the current-state inventory to define the root config schema and backend
   bundle contract.
2. Implement config loading, backend registry, and doctor validation.
3. Migrate AWS and GCP through compatibility paths.
4. Replace branch-targeted docs and CI routing with backend validation and
   explicit deployment invocation.

## Open Questions

- What is the first-class root config filename and location?
- Should the local backend be Docker Compose first, Kubernetes first, or staged?
- Which commands should form the public setup UX: `make`, a Python CLI, Django
  management commands, or a small standalone tool?
- Which existing Pulumi-related names are harmless compatibility aliases, and
  which require migration to avoid confusing users?
