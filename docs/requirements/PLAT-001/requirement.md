---
id: PLAT-001
title: "Cloud Provider Abstraction"
status: ACTIVE
type: CONSTRAINT
priority: MUST
wave: 1
created_at: 2026-03-19T02:57:48.639105Z
updated_at: 2026-05-09T05:11:30.369057Z
---

# PLAT-001: Cloud Provider Abstraction

## Statement

The platform shall abstract all cloud provider dependencies so that the entire system, application services, data stores, object storage, task processing, and range infrastructure, can be deployed on either AWS or GCP as a configurable choice per deployment. No deployment shall require services from more than one cloud provider.

## Rationale

Shifter currently has hard dependencies on AWS services (S3, ECS, SSM, RDS, etc.) throughout the codebase. To support GCP as a deployment target and enable multiple independent deployments across cloud providers, the platform must decouple business logic from cloud-specific APIs. This abstraction is the foundational requirement that enables all other GCP and multi-deployment capabilities.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/engine/ecs.py` (ECS Fargate task orchestration - direct boto3/AWS coupling, no provider abstraction)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/assets/s3.py` (S3 storage service - direct boto3 S3 client, no storage abstraction)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/engine/secrets.py` (AWS Secrets Manager service - direct boto3 coupling, no secrets abstraction)
- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/executors/aws_executor.py` (AWS Executor - boto3 API wrapper for EC2/VPC, no GCP equivalent exists)
- IMPLEMENTS → CONFIG `shifter/shifter_platform/config/settings.py` (Django settings - AWS-specific config (S3, ECS, SNS, SES, SQS) with no cloud provider switch)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#487` (PLAT-001: Cloud Provider Abstraction)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#488` (PLAT-001a: Platform cloud abstraction foundation)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#490` (PLAT-001c: AWS Secret Storage adapter (Platform))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#491` (`PLAT-001d`: AWS Message Queue adapter (Platform))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#492` (PLAT-001e: AWS Container Runner adapter (Platform))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#493` (PLAT-001f: Provisioner cloud abstraction foundation + AWS implementations)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#494` (PLAT-001g: Migrate provisioner call sites to cloud abstractions)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/cloud/gcp/storage.py` (GCP object storage adapter)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/cloud/aws/task_runner.py` (AWS task runner adapter)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/cloud/gcp/task_runner.py` (GCP task runner adapter)
- TESTS → TEST `shifter/shifter_platform/tests/shared/cloud/test_factory.py` (Cloud factory tests)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/cloud/__init__.py` (Cloud provider abstraction factories)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/cloud/aws/storage.py` (AWS object storage adapter)
- CONSTRAINS → ADR `ADR-005` (Cloud expansion must preserve provider seams and AWS continuity)
- IMPLEMENTS → CODE_FILE `shifter/packer/gcp/ubuntu.pkr.hcl` (GCE guest-image Packer builders (googlecompute) - the GCP image-bake side of cloud-provider deployability (PLAT-001.10))
- IMPLEMENTS → CONFIG `.github/workflows/packer-gcp.yml` (GCP GCE image build CI (ubuntu-latest + Workload Identity Federation); promote via packer-gcp-promote.yml (PLAT-001.10))
- IMPLEMENTS → CONFIG `.github/workflows/packer-gcp-validate.yml` (Protected exact-image validation and guest-SBOM evidence)
- IMPLEMENTS → CONFIG `.github/workflows/packer-gcp-promote.yml` (Evidence-bound GCE image promotion)
- IMPLEMENTS → CODE_FILE `mcp/ops/index.js` (MCP ops GCP image tools build_gce_image / promote_gce_image (infra_mutation), parallel to build_ami / promote_ami (PLAT-001.10))
- TESTS → TEST `shifter/packer/tests/test_packer_gcp.py` (GCE Packer template tests (builder type, sysprep, AWS-unaffected guard, live packer validate) (PLAT-001.10))
- TESTS → TEST `mcp/ops/tool-surface.test.js` (MCP ops tool-surface tests covering build_gce_image / promote_gce_image registration (PLAT-001.10))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#505` (PLAT-001.10: CI/CD + Packer for GCP)
