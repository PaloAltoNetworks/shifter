---
id: PLAT-202
title: "Per-Range LLM Access Management"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-04-16T22:49:32.549002Z
updated_at: 2026-09-12T00:00:00Z
---

# PLAT-202: Per-Range LLM Access Management

## Statement

The platform shall provision per-range access to external LLM and agentic-tool APIs, with shardable allocation across models, clouds, and accounts. Shard assignment, credential plumbing, and endpoint routing shall be a first-class platform capability rather than an out-of-band operator script. Shard strategy shall be configurable per scenario or per event, informed by event capacity declarations (CTF-908) and planned by capacity-aware provisioning (PLAT-201).

## Rationale

Scenarios increasingly assume agentic tooling inside participant ranges (for example Claude Code inside Kali). At Ottawa BSides this was handled by an SSM fan-out script (scripts/polaris-aws-range/apply_kali_bedrock_shard.py) that sharded credentials across AWS accounts and Bedrock inference profiles based on user_id % 8. That pattern is brittle: every capacity shift, model availability change, or account reshuffle requires a new bespoke script. Moving the capability into the platform lets scenario authors express "this range needs agentic-model access" and have the platform handle allocation.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#681` (PLAT-202: Per-Range LLM Access Management)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#2118` (Policy catalog and shared access contracts)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#2139` (Persist sharing bindings and resolve overlapping policies)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#2140` (Project sharing membership and fence authority changes)
- IMPLEMENTS → DOCUMENTATION `docs/architecture/model-access/architecture.md`
- IMPLEMENTS → DOCUMENTATION `docs/architecture/model-access/canonical-json-v1-vector.json`
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/models.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/core_models.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/sharing_models.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/catalog.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/allocation.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/policy.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/provider.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/effective_policy.py`
- IMPLEMENTS → CODE `shifter/installation/model_access.py`
- IMPLEMENTS → CONFIG `shifter/installation/pyproject.toml`
- IMPLEMENTS → CODE `shifter/installation/loader.py`
- IMPLEMENTS → CODE `shifter/installation/render.py`
- IMPLEMENTS → CONFIG `shifter/installation/published_contract/model-access-policy.v1.schema.json`
- IMPLEMENTS → CONFIG `shifter/shifter_platform/config/_model_access_settings.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/models/_sharing.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/services/_sharing.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/authority.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/authority_port.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/cms/services/_model_access_sharing.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/ctf/services/model_access_sharing.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/config/model_access_sharing.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/workspaces/services/_model_access.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/management/services.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/signals.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/ctf/signals.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/migrations/0057_model_access_sharing.py`
- IMPLEMENTS → CODE `scripts/gcp/render_runtime_env.py`
- IMPLEMENTS → CODE `scripts/bootstrap/aws_eks.py`
- TESTS → TEST `shifter/shifter_platform/tests/shared/model_access/test_contract.py`
- TESTS → TEST `shifter/shifter_platform/tests/shared/model_access/test_effective_policy.py`
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_sharing.py`
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_model_access_authority_postgres.py`
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_model_access_range_pagination.py`
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_sharing_authority_invalidation.py`
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_model_access_sharing.py`
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_model_access_sharing.py`
- TESTS → TEST `shifter/shifter_platform/tests/config/test_model_access_sharing.py`
- TESTS → TEST `shifter/shifter_platform/tests/management/test_model_access_authority.py`
- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_services.py`
- TESTS → TEST `shifter/shifter_platform/tests/shared/model_access/test_allocation.py`
- TESTS → TEST `shifter/shifter_platform/tests/shared/model_access/test_provider.py`
- TESTS → TEST `shifter/shifter_platform/tests/shared/model_access/test_schema_publication.py`
- TESTS → TEST `shifter/shifter_platform/tests/config/test_model_access_settings.py`
- TESTS → TEST `shifter/installation/tests/test_model_access.py`
- TESTS → TEST `scripts/gcp/tests/test_render_runtime_env.py`

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#2123` (M06 disabled GCP broker deployment package)
- IMPLEMENTS → CODE `shifter/installation/gcp_model_broker.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/runtime.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/network.py`
- IMPLEMENTS → CODE `shifter/engine/provisioner/gcp_range_cell_firewall.py`
- IMPLEMENTS → CODE `scripts/gcp/render_model_broker.py`
- IMPLEMENTS → CODE `scripts/gcp/probe_model_broker.py`
- IMPLEMENTS → CODE `scripts/gcp/verify_running_image_ids.py`
- IMPLEMENTS → CODE `scripts/check_tf_gcp_iam_resource_scope/check_tf_gcp_iam_resource_scope.py`
- IMPLEMENTS → CONFIG `platform/terraform/gcp/modules/portal/iam/model_broker.tf`
- IMPLEMENTS → CONFIG `platform/terraform/gcp/modules/platform-core/model_broker.tf`
- IMPLEMENTS → CONFIG `platform/charts/shifter/templates/model-broker.yaml`
- IMPLEMENTS → CONFIG `platform/charts/shifter/templates/model-broker-network.yaml`
- IMPLEMENTS → CONFIG `platform/charts/shifter/templates/model-access-control.yaml`
- IMPLEMENTS → CONFIG `.github/workflows/_gcp-dev.yml`
- IMPLEMENTS → DOCUMENTATION `docs/architecture/model-access/gcp-packaging.md`
- IMPLEMENTS → DOCUMENTATION `docs/ops/model-access-gcp-probes.md`
- TESTS → TEST `shifter/installation/tests/test_gcp_model_broker.py`
- TESTS → TEST `shifter/installation/tests/test_broker_runtime.py`
- TESTS → TEST `shifter/engine/provisioner/tests/test_model_broker_egress.py`
- TESTS → TEST `platform/charts/shifter/tests/test_model_broker.py`
- TESTS → TEST `scripts/check_tf_gcp_iam_resource_scope/test_model_broker_scope.py`
- TESTS → TEST `scripts/gcp/tests/test_render_model_broker.py`
- TESTS → TEST `scripts/gcp/tests/test_probe_model_broker.py`
- TESTS → TEST `scripts/gcp/tests/test_verify_running_image_ids.py`
- TESTS → TEST `scripts/bootstrap/tests/test_gcp_model_broker_catalog.py`
- IMPLEMENTS → CODE `shifter/engine/provisioner/gcp_range_cell_plan.py`
- IMPLEMENTS → CODE `shifter/engine/provisioner/raes_gcp_plan.py`
- IMPLEMENTS → CODE `shifter/engine/provisioner/gcp_range_cell_types.py`
- IMPLEMENTS → CODE `shifter/engine/provisioner/raes_gcp_apply.py`
- IMPLEMENTS → CODE `shifter/engine/provisioner/gcp_range_cell_model_broker.py`

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#2119` (M02: enforcing scenario/event model admission)
- IMPLEMENTS → CODE `shifter/shifter_platform/shared/model_access/admission.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/cms/models/scenarios.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/cms/scenarios/model_needs.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/cms/migrations/0046_scenariomodelneeds.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/ctf/models/event.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/ctf/migrations/0058_ctfevent_model_demand.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/ctf/services/range/capacity.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/engine/services/_model_admission.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/cms/services/_model_admission.py`
- IMPLEMENTS → CODE `shifter/shifter_platform/cms/services/_raes_range_create.py`
- IMPLEMENTS → DOCUMENTATION `docs/ops/model-access.md`
- IMPLEMENTS → DOCUMENTATION `docs/adr/060-model-access-allocation-accounting.md`
- TESTS → TEST `shifter/shifter_platform/tests/shared/model_access/test_admission.py`
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_scenario_model_needs.py`
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_model_demand_declaration.py`
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_model_admission.py`
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_launch_model_admission.py`
