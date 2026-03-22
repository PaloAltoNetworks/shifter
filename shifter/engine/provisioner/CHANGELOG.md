# Changelog

All notable changes to the Shifter Engine Provisioner will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
