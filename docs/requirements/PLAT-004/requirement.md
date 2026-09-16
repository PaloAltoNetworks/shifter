---
id: PLAT-004
title: "Independent Multi-Deployment"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 1
created_at: 2026-03-19T02:57:48.930387Z
updated_at: 2026-05-09T05:11:30.442691Z
---

# PLAT-004: Independent Multi-Deployment

## Statement

The system shall support multiple independent deployments of the Shifter platform. Each deployment shall operate as a fully isolated instance with its own application services, database, users, content, and range infrastructure. Deployments shall share no runtime state, data, or infrastructure with other deployments. Each deployment shall be independently upgradeable, configurable, and operable.

## Rationale

Multiple independent deployments enable Shifter to serve different organizations, regions, or security boundaries without co-tenancy risk. Each deployment can be sized, configured, and managed according to its specific operational requirements. Isolation ensures that an outage, misconfiguration, or security incident in one deployment cannot affect another.

## Traceability

- IMPLEMENTS → CONFIG `shifter/shifter_platform/config/settings.py` (Django settings - single deployment config, no deployment ID or isolation mechanism)
- IMPLEMENTS → CONFIG `platform/terraform/environments/` (Terraform environments - dev/prod exist but single-account AWS only, no multi-deployment isolation)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#673` (PLAT-004: Independent Multi-Deployment)
- IMPLEMENTS → CONFIG `platform/terraform/environments/dev/main.tf` (Independent AWS dev deployment environment)
- IMPLEMENTS → CONFIG `platform/terraform/environments/prod/main.tf` (Independent AWS prod deployment environment)
- IMPLEMENTS → CONFIG `platform/terraform/gcp/environments/gcp-dev/main.tf` (Independent GCP dev deployment environment)
