# Changelog

All notable changes to the Shifter Engine Provisioner will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- Provisioner container now runs as non-root `appuser:1000 / appgroup:1000`
  (numeric `USER 1000:1000` so Kubernetes `runAsNonRoot` admission can
  verify it) instead of root (#950). Terraform/Pulumi installs and
  `pip install` still run as root during build, then the runtime drops
  privileges before `ENTRYPOINT`. `HOME` / `TF_PLUGIN_CACHE_DIR` /
  `PULUMI_HOME` are set explicitly and the matching cache directories
  under `/home/appuser` are pre-created so Terraform/Pulumi can write
  under the non-root identity. `/app` is chowned to `appuser:appgroup`
  so Terraform can write `.terraform/` and `terraform.tfvars.json`
  inside module working directories. This reduces the blast radius of a
  container compromise but does not eliminate the risk of host root via
  a kernel-level container escape. Added `tests/test_dockerfile.py` as
  a structural regression gate plus an opt-in (`RUN_DOCKER_TESTS=1`)
  Docker smoke test that verifies the running container's UID, HOME,
  and writable cache paths.

## [3.31.0] - 2026-03-22

### Removed
- Dead Pulumi IaC code (~4,500 lines): `RangeStack`, `NetworkComponent` class, `InstanceComponent` class, and all orchestration functions (`run_pulumi`, `_run_provision`, `_run_destroy`, `_select_or_create_stack`, `_set_stack_config`, `_get_pulumi_path`, `_validate_pulumi_output_schema`)
- Dead `load_config()` function and its helper builders (`_build_instance_config`, `_build_subnet_configs`) from `config.py` — these loaded config via `pulumi.Config()` which is no longer used
- `stacks/` directory (`RangeStack`, `__init__.py`)
- `Pulumi.yaml` project config and mock `pulumi` CLI script
- `pulumi` and `pulumi_aws` dependencies from `pyproject.toml`
- Pulumi test infrastructure: `PulumiMocks` class, `pulumi_mocks` fixture, `mock_pulumi_executable` autouse fixture, `mock_pulumi_config` fixture
- Dead test files and test classes for removed code

### Changed
- `ManagedBy` tag value from `"pulumi"` to `"terraform"` in `components/tags.py`
- `components/instance.py` now contains only utility functions (`validate_s3_path`, `sanitize_hostname`)
- `components/network.py` now contains only subnet allocation/deallocation functions
- `components/__init__.py` exports only `build_common_tags`
