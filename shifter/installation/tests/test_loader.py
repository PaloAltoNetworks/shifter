"""Tests for ``installation.loader`` — file loading and fail-fast validation."""

from __future__ import annotations

import pytest

from installation import ConfigIssue, InstallationConfigError
from installation.loader import load_root_config, validate_root_config_file
from installation.schema import RootConfig


class TestLoadRootConfig:
    def test_valid_file_returns_root_config(self, write_config, aws_config):
        cfg = load_root_config(write_config(aws_config))
        assert isinstance(cfg, RootConfig)
        assert cfg.backend == "aws"

    def test_accepts_str_path(self, write_config, aws_config):
        cfg = load_root_config(str(write_config(aws_config)))
        assert cfg.backend == "aws"

    def test_returns_config_when_backend_bundle_unexpectedly_missing(self, write_config, aws_config, monkeypatch):
        # Defensive branch: a validated backend always resolves to a bundle in
        # practice, but load_root_config returns the validated config rather
        # than crashing if the registry unexpectedly yields None.
        monkeypatch.setattr("installation.loader.registry.get_backend_bundle", lambda name: None)
        cfg = load_root_config(write_config(aws_config))
        assert isinstance(cfg, RootConfig)
        assert cfg.backend == "aws"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(tmp_path / "shifter.yaml")
        assert exc.value.issues
        assert "shifter.yaml" in str(exc.value)

    def test_invalid_yaml_raises(self, write_config):
        path = write_config(raw="backend: [unterminated\n")
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        assert exc.value.issues
        assert "yaml" in str(exc.value).lower()

    @pytest.mark.parametrize("raw", ["- a\n- b\n", "just a string\n", ""])
    def test_non_mapping_top_level_raises(self, write_config, raw):
        path = write_config(raw=raw)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        assert "mapping" in str(exc.value).lower()

    def test_duplicate_top_level_key_raises(self, write_config):
        raw = "backend: aws\ndeployment:\n  name: shifter\n  domain: shifter.example.com\nbackend: gcp\n"
        path = write_config(raw=raw)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        rendered = str(exc.value).lower()
        assert "duplicate" in rendered and "backend" in rendered

    def test_duplicate_nested_key_raises(self, write_config):
        raw = "backend: aws\ndeployment:\n  name: shifter\n  name: other\n  domain: shifter.example.com\n"
        path = write_config(raw=raw)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        assert "duplicate" in str(exc.value).lower()

    @pytest.mark.parametrize(
        "raw",
        [
            # Inline merge key.
            "backend: aws\ndeployment:\n  <<: {name: shifter, domain: shifter.example.com}\n  name: other\n",
            # Merge key via an anchor/alias — this is the case that would otherwise let a
            # "merged" key and an explicit key of the same name coexist undetected.
            (
                "anchored: &base\n  name: shifter\n  domain: shifter.example.com\n"
                "backend: aws\ndeployment:\n  <<: *base\n  name: other\n"
            ),
        ],
    )
    def test_yaml_merge_keys_rejected(self, write_config, raw):
        path = write_config(raw=raw)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        assert "merge" in str(exc.value).lower()

    def test_recursive_alias_graph_does_not_recurse_forever(self, write_config):
        # A self-referential alias graph must not blow the stack while scanning for
        # duplicate keys; it surfaces as a normal validation failure instead.
        path = write_config(raw="backend: &a\n  x: *a\n")
        with pytest.raises(InstallationConfigError):
            load_root_config(path)

    def test_aggregates_all_problems(self, write_config):
        bad = {"backend": "azure", "deployment": {"name": "Bad Name", "domain": "localhost"}}
        path = write_config(bad)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        paths = {issue.path for issue in exc.value.issues}
        assert "backend" in paths
        assert "deployment.name" in paths
        assert "deployment.domain" in paths

    @pytest.mark.parametrize(
        "raw_value",
        [
            "SUPERSECRETMARKER\nMORE SECRET DATA ON A SECOND LINE",  # pasted multi-line key body
            "SUPERSECRETMARKER-" + "ab12" * 300,  # implausibly long for a reference
        ],
    )
    def test_error_message_does_not_leak_raw_secret_values(self, write_config, raw_value):
        # A user who pastes a raw secret into the config gets a validation error,
        # and the error surface (exception message and every ConfigIssue) must not
        # echo the raw value back.
        bad = {
            "backend": "aws",
            "deployment": {"name": "shifter", "domain": "shifter.example.com"},
            "secrets": {"db_password": raw_value, "django_secret_key": "prompt"},
        }
        path = write_config(bad)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        rendered = str(exc.value)
        assert raw_value not in rendered
        assert "SUPERSECRETMARKER" not in rendered
        for issue in exc.value.issues:
            assert raw_value not in issue.message
            assert raw_value not in issue.path
            assert "SUPERSECRETMARKER" not in issue.message


class TestBackendSpecificValidation:
    """The loader runs the *selected backend bundle's* settings / secret-reference checks."""

    @pytest.fixture
    def strict_aws(self, monkeypatch):
        """Replace the registry's ``aws`` bundle with one that strictly validates settings
        and one secret reference, so the dispatch path is exercised. It keeps both secrets
        the real ``aws`` bundle requires (``django_secret_key``, with a pattern, and
        ``db_password``, without one)."""
        from pydantic import BaseModel, ConfigDict

        from installation import registry as registry_mod
        from installation.contract import RequiredSecret

        class _StrictAwsSettings(BaseModel):
            model_config = ConfigDict(extra="forbid")

            region: str

        base = registry_mod.BACKEND_BUNDLES["aws"]
        strict = base.model_copy(
            update={
                "settings_model": _StrictAwsSettings,
                "required_secrets": (
                    RequiredSecret(
                        logical_name="django_secret_key",
                        purpose="p",
                        reference_grammar="a projects/<project>/secrets/<name> resource path",
                        reference_pattern=r"projects/[^/]+/secrets/[^/]+",
                    ),
                    RequiredSecret(logical_name="db_password", purpose="p", reference_grammar="a reference"),
                ),
            }
        )
        monkeypatch.setitem(registry_mod.BACKEND_BUNDLES, "aws", strict)
        return strict

    def _aws_config(self, **extra):
        # A complete aws config that satisfies both the real aws bundle and ``strict_aws``:
        # ``django_secret_key`` uses a ``projects/...`` reference (matching strict_aws's
        # pattern), ``db_password`` uses ``prompt``, and ``settings`` carries the ``region``
        # strict_aws's settings model requires. Tests override ``secrets`` / ``settings``
        # via ``extra`` to exercise the failure paths.
        base = {
            "backend": "aws",
            "deployment": {"name": "shifter", "domain": "shifter.example.com"},
            "secrets": {"django_secret_key": "projects/acme/secrets/django", "db_password": "prompt"},
            "settings": {"region": "us-east-2"},
        }
        base.update(extra)
        return base

    def test_real_aws_bundle_rejects_unknown_settings(self, write_config):
        # #728: the shipped aws bundle now has a closed settings_model, so an unknown key is
        # rejected — no longer the provisional "accept any mapping" behavior.
        path = write_config(self._aws_config(settings={"region": "us-east-2", "anything": True}))
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        assert "settings.anything" in {issue.path for issue in exc.value.issues}

    def test_real_aws_bundle_requires_region(self, write_config):
        # region is required operator intent for AWS (#728); an empty settings block fails.
        path = write_config(self._aws_config(settings={}))
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        assert "settings.region" in {issue.path for issue in exc.value.issues}

    def test_real_aws_bundle_rejects_a_malformed_region(self, write_config):
        path = write_config(self._aws_config(settings={"region": "US_EAST_2"}))
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        assert "settings.region" in {issue.path for issue in exc.value.issues}

    def test_real_aws_bundle_enforces_the_secret_reference_pattern(self, write_config):
        # The real aws django_secret_key now carries a reference_pattern; a value that is
        # not a valid reference is reported at its path and never echoed. ``%`` is outside
        # the AWS reference grammar (and this token is not a substring of any message).
        bad = self._aws_config(secrets={"django_secret_key": "BADREF%%%", "db_password": "prompt"})
        path = write_config(bad)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        assert "secrets.django_secret_key" in {issue.path for issue in exc.value.issues}
        for issue in exc.value.issues:
            assert "BADREF%%%" not in issue.render()

    def test_real_aws_bundle_accepts_a_secrets_manager_reference(self, write_config):
        cfg = load_root_config(
            write_config(
                self._aws_config(
                    secrets={"django_secret_key": "shifter/prod/django-secret-key", "db_password": "prompt"}
                )
            )
        )
        assert cfg.secrets["django_secret_key"] == "shifter/prod/django-secret-key"

    def test_real_aws_bundle_accepts_the_proof_profile(self, write_config):
        cfg = load_root_config(
            write_config(
                self._aws_config(deployment={"name": "shifter", "domain": "shifter.example.com", "profile": "proof"})
            )
        )
        assert cfg.deployment.profile == "proof"

    def test_real_aws_bundle_still_validates_range_egress_with_verbatim_cidr_errors(self, write_config):
        # range_egress stays owned by installation.range_egress even with a closed AWS
        # settings_model: an invalid CIDR is surfaced at its settings.range_egress path with
        # the verbatim (non-secret, #775) message, not sanitized by the settings-model path.
        bad = self._aws_config(
            settings={"region": "us-east-2", "range_egress": {"mode": "allowlist", "allowed_cidrs": ["not-a-cidr"]}}
        )
        path = write_config(bad)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        cidr_issues = [i for i in exc.value.issues if i.path.startswith("settings.range_egress.allowed_cidrs")]
        assert cidr_issues
        # Verbatim message (range_egress owns it), not the settings-model sanitized text.
        assert any("prefix length" in i.message for i in cidr_issues)
        assert all("failed a backend-specific validation check" not in i.message for i in cidr_issues)

    def _gcp_config(self, settings: dict) -> dict:
        return {
            "backend": "gcp",
            "deployment": {"name": "shifter", "domain": "shifter.example.com"},
            "secrets": {"django_secret_key": "prompt"},
            "settings": settings,
        }

    def test_real_gcp_bundle_rejects_unknown_settings(self, write_config):
        # #729: the shipped gcp bundle now has a closed settings_model, so an unknown key is
        # rejected — no longer the provisional "accept any mapping" behavior.
        path = write_config(self._gcp_config({"project_id": "acme-shifter", "region": "us-central1", "anything": True}))
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        assert "settings.anything" in {issue.path for issue in exc.value.issues}

    def test_real_gcp_bundle_requires_project_id_and_region(self, write_config):
        path = write_config(self._gcp_config({}))
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        paths = {issue.path for issue in exc.value.issues}
        assert {"settings.project_id", "settings.region"} <= paths

    def test_real_gcp_bundle_still_validates_range_egress_with_verbatim_cidr_errors(self, write_config):
        # range_egress stays owned by installation.range_egress even with a closed GCP
        # settings_model (mirrors AWS): an invalid CIDR is surfaced with the verbatim,
        # non-secret (#775) message at its settings.range_egress path, not sanitized by the
        # settings-model path.
        path = write_config(
            self._gcp_config(
                {
                    "project_id": "acme-shifter",
                    "region": "us-central1",
                    "range_egress": {"mode": "allowlist", "allowed_cidrs": ["not-a-cidr"]},
                }
            )
        )
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        cidr_issues = [i for i in exc.value.issues if i.path.startswith("settings.range_egress.allowed_cidrs")]
        assert cidr_issues
        assert any("prefix length" in i.message for i in cidr_issues)
        assert all("failed a backend-specific validation check" not in i.message for i in cidr_issues)

    def test_backend_settings_problem_is_reported_at_its_settings_path(self, write_config, strict_aws):
        path = write_config(self._aws_config(settings={"region": "us-east-2", "bogus": True}))
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        paths = {issue.path for issue in exc.value.issues}
        assert "settings.bogus" in paths

    def test_missing_required_backend_setting_is_reported(self, write_config, strict_aws):
        path = write_config(self._aws_config(settings={}))
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        assert {issue.path for issue in exc.value.issues} == {"settings.region"}

    def test_backend_settings_error_does_not_echo_the_rejected_value(self, write_config, strict_aws):
        sensitive = "AKIAEXAMPLEdefinitely-not-a-region"
        path = write_config(self._aws_config(settings={"region": "us-east-2", "leaked": sensitive}))
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        rendered = str(exc.value)
        assert sensitive not in rendered
        for issue in exc.value.issues:
            assert sensitive not in issue.render()

    def test_bad_secret_reference_for_backend_is_reported(self, write_config, strict_aws):
        bad = self._aws_config(secrets={"django_secret_key": "not-a-resource-path", "db_password": "prompt"})
        path = write_config(bad)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        paths = {issue.path for issue in exc.value.issues}
        assert "secrets.django_secret_key" in paths
        # The rejected reference value must not be echoed (it could be sensitive).
        for issue in exc.value.issues:
            assert "not-a-resource-path" not in issue.render()

    def test_prompt_secret_reference_is_always_accepted(self, write_config, strict_aws):
        # ``prompt`` declares the secret while deferring the concrete reference to deploy
        # time — accepted even when the backend has a strict reference pattern.
        cfg = load_root_config(
            write_config(self._aws_config(secrets={"django_secret_key": "prompt", "db_password": "prompt"}))
        )
        assert cfg.secrets["django_secret_key"] == "prompt"

    def test_missing_required_secret_is_reported(self, write_config):
        # The real aws bundle requires django_secret_key and db_password.
        bad = self._aws_config(secrets={"django_secret_key": "prompt"})  # db_password missing
        path = write_config(bad)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        assert "secrets.db_password" in {issue.path for issue in exc.value.issues}

    def test_unknown_supplied_secret_is_reported(self, write_config):
        # A typo'd secret key must be caught here, not silently fail at render/deploy time.
        bad = self._aws_config(secrets={"django_secret_key": "prompt", "db_password": "prompt", "django_secret": "x"})
        path = write_config(bad)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        assert "secrets.django_secret" in {issue.path for issue in exc.value.issues}

    def test_settings_and_secret_problems_are_reported_together(self, write_config, strict_aws):
        bad = self._aws_config(
            settings={"region": "us-east-2", "bogus": True},
            secrets={"django_secret_key": "not-a-resource-path", "db_password": "prompt"},
        )
        path = write_config(bad)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        paths = {issue.path for issue in exc.value.issues}
        assert {"settings.bogus", "secrets.django_secret_key"} <= paths

    def test_root_schema_and_backend_problems_are_reported_together(self, write_config, strict_aws):
        # A bad root field plus backend settings/secret problems: all surface in one error
        # so the user fixes everything at once.
        bad = {
            "backend": "aws",
            "deployment": {"name": "shifter", "domain": "localhost"},  # invalid domain (root schema)
            "settings": {"bogus": True},  # invalid backend setting + missing required 'region'
            # no secrets: -> both required secrets are missing
        }
        path = write_config(bad)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(path)
        paths = {issue.path for issue in exc.value.issues}
        assert "deployment.domain" in paths  # root-schema problem
        assert {"settings.bogus", "settings.region", "secrets.django_secret_key", "secrets.db_password"} <= paths

    def test_good_secret_reference_for_backend_passes(self, write_config, strict_aws):
        cfg = load_root_config(write_config(self._aws_config()))
        assert cfg.secrets["django_secret_key"] == "projects/acme/secrets/django"

    def test_loader_returns_the_backend_normalized_settings(self, write_config, monkeypatch):
        # When a backend supplies a settings_model, load_root_config returns the model's
        # normalized output (defaults filled in), so downstream consumers see one parsed
        # shape rather than raw user input.
        from pydantic import BaseModel, ConfigDict

        from installation import registry as registry_mod

        class _AwsSettingsWithDefault(BaseModel):
            model_config = ConfigDict(extra="forbid")

            region: str = "us-east-2"

        strict = registry_mod.BACKEND_BUNDLES["aws"].model_copy(update={"settings_model": _AwsSettingsWithDefault})
        monkeypatch.setitem(registry_mod.BACKEND_BUNDLES, "aws", strict)

        cfg = load_root_config(write_config(self._aws_config(settings={})))
        assert cfg.settings == {"region": "us-east-2"}

    def test_settings_model_none_returns_settings_unchanged(self, write_config, monkeypatch):
        # A backend with no settings_model leaves the settings as the user wrote them (a
        # shallow copy) — important for #1112 configs that pass arbitrary settings. Both
        # shipped backends now have closed models (aws #728, gcp #729), so exercise the
        # provisional passthrough via a bundle whose settings_model is temporarily None.
        from installation import registry as registry_mod

        provisional = registry_mod.BACKEND_BUNDLES["aws"].model_copy(update={"settings_model": None})
        monkeypatch.setitem(registry_mod.BACKEND_BUNDLES, "aws", provisional)
        original = {"region": "us-east-2", "anything": True}
        cfg = load_root_config(
            write_config(
                {
                    "backend": "aws",
                    "deployment": {"name": "shifter", "domain": "shifter.example.com"},
                    "secrets": {"django_secret_key": "prompt", "db_password": "prompt"},
                    "settings": original,
                }
            )
        )
        assert cfg.settings == original


class TestValidateRootConfigFile:
    def test_valid_file_returns_empty_list(self, write_config, aws_config):
        assert validate_root_config_file(write_config(aws_config)) == []

    def test_backend_settings_problem_surfaces_through_validate_without_raising(
        self, write_config, aws_config, monkeypatch
    ):
        from pydantic import BaseModel, ConfigDict

        from installation import registry as registry_mod

        class _StrictAwsSettings(BaseModel):
            model_config = ConfigDict(extra="forbid")

            region: str

        strict = registry_mod.BACKEND_BUNDLES["aws"].model_copy(update={"settings_model": _StrictAwsSettings})
        monkeypatch.setitem(registry_mod.BACKEND_BUNDLES, "aws", strict)

        # aws_config declares the required secrets; strip its settings so the only problem
        # is the missing ``region`` the strict settings model requires.
        issues = validate_root_config_file(write_config({**aws_config, "settings": {}}))
        assert {issue.path for issue in issues} == {"settings.region"}

    def test_range_egress_validation_runs_in_loader(self, write_config):
        # PLAT-220: range_egress is validated cross-backend by the loader alongside the
        # bundle's own settings validation. An invalid CIDR is surfaced by the loader at its
        # settings.range_egress path, even with a closed backend settings model (#729).
        issues = validate_root_config_file(
            write_config(
                {
                    "backend": "gcp",
                    "deployment": {"name": "shifter", "domain": "shifter.example.com"},
                    "secrets": {"django_secret_key": "prompt"},
                    "settings": {
                        "project_id": "acme-shifter",
                        "region": "us-central1",
                        "range_egress": {"mode": "allowlist", "allowed_cidrs": ["not-a-cidr"]},
                    },
                }
            )
        )
        assert any(issue.path.startswith("settings.range_egress.allowed_cidrs") for issue in issues)

    def test_valid_range_egress_normalized_in_loader(self, write_config):
        # PLAT-220: the normalized form is stored back onto config.settings so
        # downstream consumers (renderers, terraform tfvars writers) get canonical
        # CIDRs and an explicit mode.
        cfg = load_root_config(
            write_config(
                {
                    "backend": "aws",
                    "deployment": {"name": "shifter", "domain": "shifter.example.com"},
                    "secrets": {"django_secret_key": "prompt", "db_password": "prompt"},
                    "settings": {
                        "region": "us-east-2",
                        "range_egress": {
                            "mode": "allowlist",
                            "allowed_cidrs": ["203.0.113.0/24"],
                        },
                    },
                }
            )
        )
        assert cfg.settings["range_egress"] == {
            "mode": "allowlist",
            "allowed_cidrs": ["203.0.113.0/24"],
        }

    def test_invalid_file_returns_issue_list_without_raising(self, write_config):
        issues = validate_root_config_file(write_config({"deployment": {"name": "x"}}))
        assert issues
        assert all(isinstance(i, ConfigIssue) for i in issues)

    def test_missing_file_returns_issue_list_without_raising(self, tmp_path):
        issues = validate_root_config_file(tmp_path / "shifter.yaml")
        assert issues
        assert all(isinstance(i, ConfigIssue) for i in issues)
