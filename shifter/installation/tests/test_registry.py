"""Tests for the backend bundle registry (``installation.registry``)."""

from __future__ import annotations

import pytest

from installation.contract import (
    SUPPORTED_CONTRACT_VERSIONS,
    BackendBundle,
    OutputKind,
    OutputSensitivity,
)
from installation.registry import (
    ALLOWED_PROFILES,
    BACKEND_BUNDLES,
    KNOWN_BACKENDS,
    KNOWN_PROFILES,
    get_backend_bundle,
)

# What the provisional registry must keep accepting (carried over unchanged from the
# pre-#1113 ``installation.backends`` data, which the registry supersedes).
_EXPECTED_PROFILES: dict[str, frozenset[str]] = {
    "aws": frozenset({"prod", "dev"}),
    "gcp": frozenset({"prod", "dev"}),
}


def test_registry_has_the_currently_supported_backends():
    assert set(BACKEND_BUNDLES) == set(_EXPECTED_PROFILES)


def test_local_backend_is_not_registered_yet():
    # The ``local`` backend is a separate issue (#1119); it must not silently appear.
    assert "local" not in BACKEND_BUNDLES
    assert get_backend_bundle("local") is None


@pytest.mark.parametrize("name", sorted(_EXPECTED_PROFILES))
def test_each_bundle_is_a_well_formed_backend_bundle(name):
    bundle = BACKEND_BUNDLES[name]
    assert isinstance(bundle, BackendBundle)
    assert bundle.name == name
    assert bundle.contract_version in SUPPORTED_CONTRACT_VERSIONS
    assert bundle.supported_profiles == _EXPECTED_PROFILES[name]
    # Provisional entries: per-backend settings / secret-reference enforcement lands with
    # the migration issues, so the schema accepts any settings mapping and references for
    # now.
    assert bundle.settings_model is None
    assert all(secret.reference_pattern is None for secret in bundle.required_secrets)
    # A backend that ships today still declares the tools, secrets, checks, outputs, owned
    # files, and capabilities it needs — the contract is machine-readable enough for
    # validation and docs generation.
    assert bundle.required_tools
    assert bundle.required_secrets
    assert bundle.validation_checks
    assert bundle.health_checks
    assert bundle.capabilities
    assert bundle.generated_outputs
    assert bundle.owned_files.infrastructure


def test_get_backend_bundle_round_trips():
    assert get_backend_bundle("aws") is BACKEND_BUNDLES["aws"]
    assert get_backend_bundle("gcp") is BACKEND_BUNDLES["gcp"]
    assert get_backend_bundle("azure") is None
    assert get_backend_bundle("") is None


def test_registry_is_the_single_source_of_truth_for_derived_constants():
    # Adding a backend or a profile is a registry entry; the derived constants follow.
    assert frozenset(BACKEND_BUNDLES) == KNOWN_BACKENDS
    assert {name: bundle.supported_profiles for name, bundle in BACKEND_BUNDLES.items()} == ALLOWED_PROFILES
    assert frozenset().union(*(bundle.supported_profiles for bundle in BACKEND_BUNDLES.values())) == KNOWN_PROFILES


def test_owned_files_and_docs_are_repository_relative():
    for bundle in BACKEND_BUNDLES.values():
        owned = bundle.owned_files
        groups = (
            owned.infrastructure,
            owned.kubernetes,
            owned.scripts,
            owned.workflows,
            owned.examples,
            owned.docs,
        )
        for path in (*[p for group in groups for p in group], *bundle.docs):
            assert path and not path.startswith("/"), path
            assert ".." not in path.split("/"), path
        # A backend that exists in the repo points at its own worked example.
        assert owned.examples == (f"shifter/installation/examples/{bundle.name}.yaml",)


def test_validation_check_commands_are_repo_relative_argv_arrays():
    for bundle in BACKEND_BUNDLES.values():
        for check in bundle.validation_checks:
            argv = check.command.argv
            assert argv, f"{bundle.name}/{check.name}: empty argv"
            assert all(isinstance(arg, str) and arg.strip() for arg in argv)
            assert not any(arg.startswith("/") for arg in argv), f"{bundle.name}/{check.name}: absolute path in argv"
        # The root-config validator is the first thing every backend should run.
        assert any(check.name == "root-config" for check in bundle.validation_checks)


def test_every_validation_check_executable_is_a_declared_required_tool():
    # A setup/doctor flow preflights required_tools and then runs validation_checks; the
    # executables must be in sync (also enforced structurally by BackendBundle).
    for bundle in BACKEND_BUNDLES.values():
        tool_names = {tool.name for tool in bundle.required_tools}
        for check in bundle.validation_checks:
            assert check.command.argv[0] in tool_names, f"{bundle.name}/{check.name}: {check.command.argv[0]!r}"


def test_aws_bundle_is_a_terraform_ecs_backend_not_a_kubernetes_one():
    # AWS deploys Terraform/ECS components — it does not use Helm or kubectl, so the
    # bundle must not require those tools or claim Kubernetes/Helm roots.
    aws = BACKEND_BUNDLES["aws"]
    tool_names = {tool.name for tool in aws.required_tools}
    assert "terraform" in tool_names
    assert not ({"helm", "kubectl"} & tool_names)
    assert aws.owned_files.kubernetes == ()


def test_gcp_bundle_is_a_kubernetes_backend():
    gcp = BACKEND_BUNDLES["gcp"]
    tool_names = {tool.name for tool in gcp.required_tools}
    assert {"terraform", "gcloud", "helm", "kubectl"} <= tool_names
    assert gcp.owned_files.kubernetes  # GKE overlays plus the shared chart


_EXPECTED_SECRET_OUTPUTS: dict[str, tuple[str, str, OutputKind]] = {
    # backend -> (app secret env key, db secret env key, kind)
    # GCP emits the canonical *_SECRET_ID names; AWS emits the *_SECRET_ARN aliases that
    # entrypoint.sh normalizes.
    "gcp": ("APP_SECRET_ID", "DB_SECRET_ID", OutputKind.RUNTIME_ENV),
    "aws": ("APP_SECRET_ARN", "DB_SECRET_ARN", OutputKind.COMPAT_ALIAS),
}


@pytest.mark.parametrize("name", sorted(_EXPECTED_SECRET_OUTPUTS))
def test_generated_outputs_match_the_platforms_actual_runtime_contract(name):
    # The platform reads CLOUD_PROVIDER (config.settings) to pick the adapter family and,
    # at startup (entrypoint.sh), fetches the app *and* database secret bundles — and only
    # does so when both references are present. The resolved DJANGO_SECRET_KEY is derived
    # in-process, not a backend-generated deploy output.
    bundle = BACKEND_BUNDLES[name]
    outputs = {output.name: output for output in bundle.generated_outputs}
    assert outputs["CLOUD_PROVIDER"].sensitivity is OutputSensitivity.PUBLIC
    app_key, db_key, kind = _EXPECTED_SECRET_OUTPUTS[name]
    for key in (app_key, db_key):
        assert outputs[key].sensitivity is OutputSensitivity.SECRET_REFERENCE
        assert outputs[key].kind is kind
    assert "DJANGO_SECRET_KEY" not in outputs
    # No generated output is a raw secret value, so none can land in a ConfigMap.
    assert all(output.sensitivity is not OutputSensitivity.SECRET_VALUE for output in bundle.generated_outputs)


def test_bundle_capabilities_are_explicitly_enumerated_not_the_whole_enum():
    # Both backends are feature-equivalent today, but the set is written out per backend
    # so a new BackendCapability enum member is not auto-claimed by every backend.
    from installation.contract import BackendCapability

    for bundle in BACKEND_BUNDLES.values():
        assert bundle.capabilities <= frozenset(BackendCapability)
        assert BackendCapability.STORAGE in bundle.capabilities
        assert BackendCapability.TASK_RUNNER in bundle.capabilities
