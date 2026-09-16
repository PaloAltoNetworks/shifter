---
id: PLAT-238
title: "Workspace-level network egress policy"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
created_at: 2026-08-01T17:37:32.031908Z
updated_at: 2026-08-01T17:41:19.898045Z
---

# PLAT-238: Workspace-level network egress policy

## Statement

The platform shall deliver the zero-egress (no-NAT) range posture (#1171) as a workspace-level policy: an administrator shall set an egress policy on a workspace that the range provisioning path enforces identically on AWS and GCP, and an SPA control shall expose the setting. Enforcement shall use each cloud's native network primitives rather than a hand-rolled egress filter, and the compatibility default shall preserve existing range behavior.

## Rationale

Program #1321 specifies zero-egress (#1171) be delivered as a workspace-level policy so shared-infrastructure operators can enforce it per workspace. It is not yet implemented as workspace policy. Using each cloud's native primitives keeps AWS/GCP parity and avoids a hand-rolled control (PLAT-241).

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `1945`
