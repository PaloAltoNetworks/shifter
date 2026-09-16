---
id: PLAT-003
title: "GCP Range Provisioning"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 1
created_at: 2026-03-19T02:57:48.879958Z
updated_at: 2026-05-09T05:11:30.415479Z
---

# PLAT-003: GCP Range Provisioning

## Statement

The range provisioning engine shall support creating, managing, and destroying range instances on GCP. This includes: provisioning compute instances (Compute Engine), configuring networking (VPC, firewall rules, Cloud NAT), providing remote access to range VMs (for example, via Apache Guacamole or equivalent), and managing range lifecycle (start, stop, restart, destroy). GCP range provisioning shall support the same scenario templates and range configurations as the AWS provisioning path.

## Rationale

Ranges are the core infrastructure product of Shifter. If the platform deploys on GCP, ranges must also run on GCP, participants cannot access AWS VMs from a GCP-hosted platform without cross-cloud networking complexity. Same-cloud range provisioning keeps the architecture simple and latency low.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/stacks/range_stack.py` (Range stack - Pulumi composition using AWS EC2/VPC/SG, no GCP compute equivalent)
- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/components/instance.py` (Instance component - creates AWS EC2 instances with AMIs, no GCP Compute Engine support)
- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/components/network.py` (Network component - creates AWS VPC subnets/security groups/route tables)
- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/executors/ssm_executor.py` (SSM Executor - uses AWS SSM for remote command execution on range VMs)
- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/config.py` (Provisioner config - RangeConfig uses AWS-specific fields (AMI IDs, VPC ID, instance profiles))
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#672` (PLAT-003: GCP Range Provisioning)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/networking.md` (Networking architecture - GCP platform and range connectivity)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/gdc-provisioning.md` (GDC provisioning architecture - runtime primitives and range networking)
- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/range_terraform_runner.py` (Provider-routed range Terraform runner)
- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/range_ops.py` (Provider-routed range lifecycle operations)
- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/main.py` (GCP-aware range provisioning state persistence)
- IMPLEMENTS → CONFIG `platform/terraform/gcp/environments/gcp-dev/main.tf` (GCP range/platform environment)
- TESTS → TEST `shifter/shifter_platform/tests/engine/ecs/test_start_ecs_task_gcp.py` (GCP task runner tests)
- CONSTRAINS → ADR `ADR-005` (Cloud expansion must preserve provider seams and AWS continuity)
