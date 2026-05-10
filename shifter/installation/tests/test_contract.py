"""Tests for the backend bundle contract (``installation.contract``)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from installation.contract import (
    SUPPORTED_CONTRACT_VERSIONS,
    BackendBundle,
    BackendCapability,
    BackendMaturity,
    CommandSpec,
    GeneratedOutput,
    HealthCheck,
    OutputDestination,
    OutputKind,
    OutputSensitivity,
    OwnedFiles,
    ProcessRole,
    RequiredSecret,
    RequiredTool,
    ValidationCheck,
)
from installation.errors import InstallationConfigError

_CONTRACT_VERSION = SUPPORTED_CONTRACT_VERSIONS[-1]


def _minimal_bundle(**overrides: object) -> BackendBundle:
    base: dict[str, object] = {
        "contract_version": _CONTRACT_VERSION,
        "name": "example",
        "title": "Example backend",
        "maturity": BackendMaturity.EXPERIMENTAL,
        "description": "A backend used only in tests.",
        "supported_profiles": frozenset({"prod"}),
    }
    base.update(overrides)
    return BackendBundle(**base)  # type: ignore[arg-type]


class TestCommandSpec:
    def test_argv_command_accepted(self):
        spec = CommandSpec(argv=("terraform", "validate"), description="Validate Terraform.")
        assert spec.argv == ("terraform", "validate")

    def test_empty_argv_rejected(self):
        with pytest.raises(ValidationError):
            CommandSpec(argv=(), description="empty")

    @pytest.mark.parametrize("bad_arg", ["", "  ", " leading", "trailing "])
    def test_blank_or_padded_argv_element_rejected(self, bad_arg):
        with pytest.raises(ValidationError):
            CommandSpec(argv=("tool", bad_arg), description="bad element")

    @pytest.mark.parametrize("bad_arg", ["foo;rm -rf /", "a|b", "a&&b", "$(whoami)", "`id`", "a>b", "a<b", "a\nb"])
    def test_shell_metacharacters_rejected(self, bad_arg):
        # Registry command specs are argv arrays executed without a shell; reject any
        # element that would be dangerous if someone ever str.join()'d it into a shell.
        with pytest.raises(ValidationError):
            CommandSpec(argv=("tool", bad_arg), description="shell fragment")

    def test_repo_relative_path_arguments_allowed_in_argv(self):
        # Ordinary repo-relative path arguments (no shell metacharacters, no leading
        # slash, no `..`) are fine.
        spec = CommandSpec(
            argv=("uv", "run", "--project", "shifter/installation", "shifter-config", "validate", "shifter.yaml"),
            description="root config validation",
        )
        assert spec.argv[-1] == "shifter.yaml"

    @pytest.mark.parametrize("bad_arg", ["/etc/passwd", "/usr/bin/terraform", "/abs/path"])
    def test_absolute_host_path_in_argv_rejected(self, bad_arg):
        # Backend metadata must resolve to PATH-resolved executables and repo-relative
        # path arguments — never absolute host paths.
        with pytest.raises(ValidationError):
            CommandSpec(argv=("tool", bad_arg), description="absolute path")

    @pytest.mark.parametrize("bad_arg", ["../scripts/check", "platform/../../escape", ".."])
    def test_path_traversal_in_argv_rejected(self, bad_arg):
        with pytest.raises(ValidationError):
            CommandSpec(argv=("tool", bad_arg), description="path traversal")

    @pytest.mark.parametrize("argv", [("terraform validate",), ("sh -c",), ("tool", "two words"), ("tool", "a\tb")])
    def test_internal_whitespace_in_argv_rejected(self, argv):
        # An argv element with internal whitespace is a shell fragment, not a token.
        with pytest.raises(ValidationError):
            CommandSpec(argv=argv, description="shell-like command string")

    @pytest.mark.parametrize("bad_exe", ["-flag", ".hidden", "with-./slash/x", "/abs", "weird@name"])
    def test_argv0_must_be_a_bare_executable_name(self, bad_exe):
        with pytest.raises(ValidationError):
            CommandSpec(argv=(bad_exe, "arg"), description="bad executable")

    @pytest.mark.parametrize("exe", ["terraform", "uv", "python3", "kube-linter", "go_tool", "Tool2"])
    def test_argv0_accepts_ordinary_executable_names(self, exe):
        assert CommandSpec(argv=(exe, "x"), description="d").argv[0] == exe

    def test_frozen(self):
        spec = CommandSpec(argv=("terraform", "validate"), description="x")
        with pytest.raises(ValidationError):
            spec.argv = ("other",)  # type: ignore[misc]


class TestRequiredTool:
    @pytest.mark.parametrize("name", ["terraform", "uv", "python3", "kube-linter", "Tool2", "go_tool"])
    def test_valid_tool_names(self, name):
        assert RequiredTool(name=name, purpose="p").name == name

    @pytest.mark.parametrize("name", ["terraform validate", "-flag", ".hidden", "with/slash", "weird@name", ""])
    def test_invalid_tool_names_rejected(self, name):
        with pytest.raises(ValidationError):
            RequiredTool(name=name, purpose="p")


class TestRequiredSecret:
    @pytest.mark.parametrize("name", ["django_secret_key", "db_password", "x"])
    def test_valid_logical_names(self, name):
        secret = RequiredSecret(logical_name=name, purpose="p", reference_grammar="g")
        assert secret.logical_name == name
        # The reference pattern is optional (provisional entries leave it unset).
        assert secret.reference_pattern is None
        assert secret.matches_reference("anything") is None

    @pytest.mark.parametrize("name", ["Django", "1secret", "db-password", "db password", ""])
    def test_invalid_logical_names_rejected(self, name):
        # Same grammar as ``RootConfig.secrets`` keys, so a required secret can be matched
        # against what the user supplied.
        with pytest.raises(ValidationError):
            RequiredSecret(logical_name=name, purpose="p", reference_grammar="g")

    def test_reference_pattern_matches_full_string(self):
        secret = RequiredSecret(
            logical_name="api_key",
            purpose="p",
            reference_grammar="g",
            reference_pattern=r"projects/[^/]+/secrets/[^/]+",
        )
        assert secret.matches_reference("projects/acme/secrets/api-key") is True
        assert secret.matches_reference("projects/acme/secrets/api-key/extra") is False  # fullmatch, not search
        assert secret.matches_reference("not-a-resource-path") is False

    @pytest.mark.parametrize("bad_pattern", ["", "(unclosed", "[a-z"])
    def test_invalid_reference_pattern_rejected(self, bad_pattern):
        with pytest.raises(ValidationError):
            RequiredSecret(logical_name="k", purpose="p", reference_grammar="g", reference_pattern=bad_pattern)

    def test_explicit_none_reference_pattern_is_allowed(self):
        secret = RequiredSecret(logical_name="k", purpose="p", reference_grammar="g", reference_pattern=None)
        assert secret.reference_pattern is None
        assert secret.matches_reference("anything") is None


class TestRepoRelativePaths:
    def test_owned_files_accepts_repo_relative_paths(self):
        owned = OwnedFiles(infrastructure=("platform/terraform/modules",), docs=("docs/x.md",))
        assert owned.infrastructure == ("platform/terraform/modules",)

    @pytest.mark.parametrize("bad_path", ["/etc/passwd", "/abs/path", "../escape", "platform/../../escape", "  ", ""])
    def test_owned_files_rejects_absolute_or_traversal_paths(self, bad_path):
        with pytest.raises(ValidationError):
            OwnedFiles(scripts=(bad_path,))

    @pytest.mark.parametrize("bad_path", ["/abs", "../up"])
    def test_bundle_docs_reject_absolute_or_traversal_paths(self, bad_path):
        with pytest.raises(ValidationError):
            _minimal_bundle(docs=(bad_path,))


class TestHealthCheck:
    def test_valid_health_check(self):
        hc = HealthCheck(
            name="portal", target="https://x/health/", requires_credentials=False, timeout_seconds=10, description="d"
        )
        assert hc.timeout_seconds == 10

    @pytest.mark.parametrize("timeout", [0, -1, -30])
    def test_non_positive_timeout_rejected(self, timeout):
        with pytest.raises(ValidationError):
            HealthCheck(name="x", target="t", requires_credentials=False, timeout_seconds=timeout, description="d")


def _output(**overrides: object) -> GeneratedOutput:
    base: dict[str, object] = {
        "name": "CLOUD_PROVIDER",
        "kind": OutputKind.RUNTIME_ENV,
        "owner": "renderer",
        "source": "render_runtime_env.py",
        "destination": OutputDestination.RUNTIME_ENV,
        "sensitivity": OutputSensitivity.PUBLIC,
        "description": "d",
    }
    base.update(overrides)
    return GeneratedOutput(**base)  # type: ignore[arg-type]


class TestGeneratedOutput:
    def test_valid_output(self):
        out = _output(process_roles=(ProcessRole.PORTAL, ProcessRole.WORKER))
        assert out.sensitivity is OutputSensitivity.PUBLIC
        assert out.destination is OutputDestination.RUNTIME_ENV

    def test_secret_value_must_go_to_a_secret_store(self):
        # A resolved secret value may only land in a Kubernetes Secret or a provider secret
        # store — never a ConfigMap (runtime-env), Terraform vars, Helm values, etc.
        ok = _output(
            name="DJANGO_SECRET_KEY",
            sensitivity=OutputSensitivity.SECRET_VALUE,
            destination=OutputDestination.KUBERNETES_SECRET,
        )
        assert ok.destination is OutputDestination.KUBERNETES_SECRET
        for bad_dest in (
            OutputDestination.RUNTIME_ENV,
            OutputDestination.HELM_VALUES,
            OutputDestination.TERRAFORM_VARIABLES,
            OutputDestination.GENERATED_FILE,
        ):
            with pytest.raises(ValidationError):
                _output(sensitivity=OutputSensitivity.SECRET_VALUE, destination=bad_dest)

    def test_secret_reference_may_land_anywhere(self):
        # A reference (a pointer) is not the secret itself, so it can go in a ConfigMap.
        out = _output(name="APP_SECRET_ID", sensitivity=OutputSensitivity.SECRET_REFERENCE)
        assert out.sensitivity is OutputSensitivity.SECRET_REFERENCE

    @pytest.mark.parametrize("field", ["name", "owner", "source", "description"])
    def test_blank_string_fields_rejected(self, field):
        with pytest.raises(ValidationError):
            _output(**{field: "  "})

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValidationError):
            _output(kind="not-a-kind")

    def test_unknown_destination_rejected(self):
        with pytest.raises(ValidationError):
            _output(destination="ConfigMap")


class TestBackendBundle:
    def test_minimal_bundle_parses(self):
        bundle = _minimal_bundle()
        assert bundle.name == "example"
        assert bundle.supports_profile("prod")
        assert not bundle.supports_profile("dev")
        # Optional collections default to empty.
        assert bundle.required_tools == ()
        assert bundle.generated_outputs == ()
        assert bundle.capabilities == frozenset()
        assert bundle.settings_model is None

    def test_full_bundle_parses(self):
        bundle = _minimal_bundle(
            required_tools=(RequiredTool(name="terraform", purpose="provision"),),
            required_secrets=(RequiredSecret(logical_name="django_secret_key", purpose="p", reference_grammar="g"),),
            generated_outputs=(_output(),),
            validation_checks=(
                ValidationCheck(
                    name="tf", command=CommandSpec(argv=("terraform", "validate"), description="d"), description="d"
                ),
            ),
            health_checks=(
                HealthCheck(name="h", target="t", requires_credentials=True, timeout_seconds=5, description="d"),
            ),
            capabilities=frozenset({BackendCapability.STORAGE, BackendCapability.TASK_RUNNER}),
            owned_files=OwnedFiles(infrastructure=("platform/terraform/modules",)),
            docs=("docs/architecture/root-configured-backend-bundles.md",),
        )
        assert BackendCapability.STORAGE in bundle.capabilities
        assert bundle.validation_checks[0].command.argv == ("terraform", "validate")
        assert bundle.validation_checks[0].blocking is True

    @pytest.mark.parametrize("bad_name", ["AWS", "1aws", "aws_backend", "aws backend", "", "-aws"])
    def test_invalid_backend_name_rejected(self, bad_name):
        with pytest.raises(ValidationError):
            _minimal_bundle(name=bad_name)

    def test_empty_supported_profiles_rejected(self):
        with pytest.raises(ValidationError):
            _minimal_bundle(supported_profiles=frozenset())

    @pytest.mark.parametrize("bad_profile", ["PROD", "prod stage", "1dev"])
    def test_invalid_profile_in_supported_profiles_rejected(self, bad_profile):
        with pytest.raises(ValidationError):
            _minimal_bundle(supported_profiles=frozenset({bad_profile}))

    @pytest.mark.parametrize("bad_version", [0, 2, 99, True, "1", 1.0, None])
    def test_unsupported_contract_version_fails_closed(self, bad_version):
        with pytest.raises(ValidationError):
            _minimal_bundle(contract_version=bad_version)

    def test_unknown_top_level_field_rejected(self):
        with pytest.raises(ValidationError):
            _minimal_bundle(provider="aws")  # type: ignore[call-arg]

    def test_unknown_maturity_rejected(self):
        with pytest.raises(ValidationError):
            _minimal_bundle(maturity="ancient")

    def test_unknown_capability_rejected(self):
        with pytest.raises(ValidationError):
            _minimal_bundle(capabilities=frozenset({"warp-drive"}))

    def test_validation_check_executable_must_be_a_declared_required_tool(self):
        # A check whose executable is not in required_tools is rejected — a setup/doctor
        # preflight of required_tools must not pass and then fail on the first check.
        check = ValidationCheck(
            name="tf", command=CommandSpec(argv=("terraform", "validate"), description="d"), description="d"
        )
        with pytest.raises(ValidationError):
            _minimal_bundle(validation_checks=(check,))  # terraform not declared
        # Declaring the tool makes it valid.
        ok = _minimal_bundle(required_tools=(RequiredTool(name="terraform", purpose="p"),), validation_checks=(check,))
        assert ok.validation_checks[0].command.argv[0] == "terraform"

    def test_settings_model_must_forbid_extras(self):
        class _Permissive(BaseModel):  # no extra="forbid"
            region: str

        with pytest.raises(ValidationError):
            _minimal_bundle(settings_model=_Permissive)

        class _Ignore(BaseModel):
            model_config = ConfigDict(extra="ignore")

            region: str

        with pytest.raises(ValidationError):
            _minimal_bundle(settings_model=_Ignore)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"required_tools": (RequiredTool(name="t", purpose="p"), RequiredTool(name="t", purpose="q"))},
            {
                "required_secrets": (
                    RequiredSecret(logical_name="k", purpose="p", reference_grammar="g"),
                    RequiredSecret(logical_name="k", purpose="q", reference_grammar="g"),
                )
            },
            {"generated_outputs": (_output(name="X"), _output(name="X"))},
            {
                "required_tools": (RequiredTool(name="t", purpose="p"),),
                "validation_checks": (
                    ValidationCheck(name="c", command=CommandSpec(argv=("t",), description="d"), description="d"),
                    ValidationCheck(name="c", command=CommandSpec(argv=("t",), description="d"), description="d"),
                ),
            },
            {
                "health_checks": (
                    HealthCheck(name="h", target="t", requires_credentials=False, timeout_seconds=1, description="d"),
                    HealthCheck(name="h", target="u", requires_credentials=False, timeout_seconds=1, description="d"),
                )
            },
        ],
    )
    def test_duplicate_named_records_rejected(self, kwargs):
        with pytest.raises(ValidationError):
            _minimal_bundle(**kwargs)

    def test_frozen(self):
        bundle = _minimal_bundle()
        with pytest.raises(ValidationError):
            bundle.name = "other"  # type: ignore[misc]


class _StrictSettings(BaseModel):
    """A backend settings model used to exercise the dispatch path in tests."""

    model_config = ConfigDict(extra="forbid")

    region: str


class TestValidateSettings:
    def test_no_settings_model_accepts_any_mapping_and_returns_a_copy(self):
        bundle = _minimal_bundle()
        original = {"region": "us-east-2", "nested": {"a": 1}}
        result = bundle.validate_settings(original)
        assert result == original
        result["region"] = "changed"
        assert original["region"] == "us-east-2", "validate_settings must not return the caller's dict"

    def test_settings_model_validates_and_normalizes(self):
        bundle = _minimal_bundle(settings_model=_StrictSettings)
        assert bundle.validate_settings({"region": "us-east-2"}) == {"region": "us-east-2"}

    @pytest.mark.parametrize("bad_settings", [{"region": "us-east-2", "bogus": True}, {}, {"region": 5}])
    def test_settings_model_rejects_invalid_settings(self, bad_settings):
        bundle = _minimal_bundle(settings_model=_StrictSettings)
        with pytest.raises(InstallationConfigError) as exc:
            bundle.validate_settings(bad_settings)
        assert all(issue.path.startswith("settings") for issue in exc.value.issues)

    def test_validate_settings_failure_does_not_echo_a_custom_validator_value(self):
        sensitive = "AKIAEXAMPLEdefinitely-not-a-region"

        class _Picky(BaseModel):
            model_config = ConfigDict(extra="forbid")

            region: str

            @field_validator("region")
            @classmethod
            def _reject(cls, v: str) -> str:
                raise ValueError(f"the value {v!r} is unacceptable")

        bundle = _minimal_bundle(settings_model=_Picky)
        with pytest.raises(InstallationConfigError) as exc:
            bundle.validate_settings({"region": sensitive})
        rendered = "\n".join(issue.render() for issue in exc.value.issues)
        assert sensitive not in rendered


class TestSettingsIssues:
    def test_no_settings_model_reports_no_issues(self):
        assert _minimal_bundle().settings_issues({"anything": 1, "nested": {"a": 1}}) == []

    def test_valid_settings_report_no_issues(self):
        assert _minimal_bundle(settings_model=_StrictSettings).settings_issues({"region": "us-east-2"}) == []

    def test_issues_are_anchored_under_settings_and_do_not_echo_the_value(self):
        bundle = _minimal_bundle(settings_model=_StrictSettings)
        sensitive = "AKIAEXAMPLEdefinitely-not-a-region"
        issues = bundle.settings_issues({"region": "us-east-2", "leaked": sensitive})
        assert issues
        assert all(issue.path.startswith("settings") for issue in issues)
        assert any(issue.path == "settings.leaked" for issue in issues)
        assert all(sensitive not in issue.render() for issue in issues)

    def test_missing_required_setting_is_reported_at_its_path(self):
        issues = _minimal_bundle(settings_model=_StrictSettings).settings_issues({})
        assert [issue.path for issue in issues] == ["settings.region"]


def _bundle_with_secrets(*secrets: RequiredSecret) -> BackendBundle:
    return _minimal_bundle(required_secrets=secrets)


_API_KEY = RequiredSecret(logical_name="api_key", purpose="p", reference_grammar="g")
_API_KEY_WITH_PATTERN = RequiredSecret(
    logical_name="api_key",
    purpose="p",
    reference_grammar="a projects/<project>/secrets/<name> resource path",
    reference_pattern=r"projects/[^/]+/secrets/[^/]+",
)


class TestSecretReferenceIssues:
    def test_present_secret_with_no_pattern_is_accepted(self):
        assert _bundle_with_secrets(_API_KEY).secret_reference_issues({"api_key": "literally-anything"}) == []

    def test_missing_required_secret_is_reported_at_its_path(self):
        issues = _bundle_with_secrets(_API_KEY).secret_reference_issues({})
        assert [issue.path for issue in issues] == ["secrets.api_key"]
        # The message names the path and the grammar, not a value (there is none).
        assert "required" in issues[0].message

    def test_unknown_supplied_secret_is_reported_at_its_path(self):
        # A typo: the bundle declares ``api_key``, the user supplied ``api_keys``.
        bundle = _bundle_with_secrets(_API_KEY)
        issues = bundle.secret_reference_issues({"api_key": "x", "api_keys": "y"})
        assert [issue.path for issue in issues] == ["secrets.api_keys"]

    def test_bundle_with_no_required_secrets_rejects_every_supplied_key(self):
        # A backend that needs no secret should not have any in shifter.yaml.
        issues = _minimal_bundle().secret_reference_issues({"anything": "x"})
        assert [issue.path for issue in issues] == ["secrets.anything"]

    def test_pattern_mismatch_is_reported_without_echoing_the_value(self):
        bundle = _bundle_with_secrets(_API_KEY_WITH_PATTERN)
        assert bundle.secret_reference_issues({"api_key": "projects/acme/secrets/api-key"}) == []
        issues = bundle.secret_reference_issues({"api_key": "not-a-resource-path"})
        assert [issue.path for issue in issues] == ["secrets.api_key"]
        assert all("not-a-resource-path" not in issue.render() for issue in issues)

    def test_prompt_is_a_universally_valid_reference(self):
        # ``prompt`` declares the secret while deferring the concrete reference; it is
        # accepted even against a strict pattern.
        assert _bundle_with_secrets(_API_KEY_WITH_PATTERN).secret_reference_issues({"api_key": "prompt"}) == []

    def test_non_string_value_is_left_for_the_root_schema(self):
        # The root schema already rejects a non-string secret value; the bundle does not
        # double-report it (the key is still "present", so no missing-required issue).
        assert _bundle_with_secrets(_API_KEY_WITH_PATTERN).secret_reference_issues({"api_key": 1234}) == []


def test_supported_contract_versions_is_a_nonempty_tuple_of_ints():
    assert SUPPORTED_CONTRACT_VERSIONS
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in SUPPORTED_CONTRACT_VERSIONS)
