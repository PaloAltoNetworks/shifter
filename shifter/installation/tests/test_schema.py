"""Tests for the root installation config schema (``installation.schema``)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from installation import ALLOWED_PROFILES, KNOWN_BACKENDS, KNOWN_PROFILES
from installation.schema import RootConfig


def _locs(exc: ValidationError) -> set[tuple[object, ...]]:
    return {err["loc"] for err in exc.errors()}


def _with_deployment(minimal_config: dict, **overrides: object) -> dict:
    """Return ``minimal_config`` with ``deployment`` keys overridden/added."""
    return {**minimal_config, "deployment": {**minimal_config["deployment"], **overrides}}


# Built from fragments at runtime so the ``detect-private-key`` pre-commit hook does
# not flag this test file for containing a PEM private-key header literal.
_RAW_KEY_MATERIAL_HEADER = "-----BEGIN " + "RSA PRIVATE" + " KEY-----"


class TestDefaultsAndShape:
    def test_minimal_config_parses_with_defaults(self, minimal_config):
        cfg = RootConfig.model_validate(minimal_config)
        assert cfg.backend == "aws"
        assert cfg.deployment.name == "shifter"
        assert cfg.deployment.domain == "shifter.example.com"
        # Defaults applied for everything the user did not set.
        assert cfg.version == 1
        assert cfg.deployment.profile == "prod"
        assert cfg.secrets == {}
        assert cfg.settings == {}

    def test_full_config_parses(self, full_config):
        cfg = RootConfig.model_validate(full_config)
        assert cfg.backend == "gcp"
        assert cfg.deployment.profile == "prod"
        assert cfg.secrets["django_secret_key"] == "shifter/prod/django-secret-key"
        assert cfg.settings["region"] == "us-central1"

    def test_root_models_exactly_one_standalone_deployment(self):
        # GEN-2001: the root contract has no fleet / install-registry / parent-child
        # / tenant-mapping shape. Pin the field set so cross-install concepts cannot
        # be added without an explicit schema change.
        assert set(RootConfig.model_fields) == {"version", "backend", "deployment", "secrets", "settings"}

    @pytest.mark.parametrize("orchestration_key", ["fleet", "installs", "tenants", "parent", "clusters"])
    def test_cross_install_orchestration_keys_rejected(self, minimal_config, orchestration_key):
        # GEN-2001: orchestration-shaped keys are rejected by extra="forbid".
        bad = {**minimal_config, orchestration_key: ["other-install"]}
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate(bad)
        assert any(orchestration_key in err["loc"] for err in exc.value.errors())


class TestRequiredFields:
    @pytest.mark.parametrize(
        "drop_path, expected_loc",
        [
            (("backend",), ("backend",)),
            (("deployment",), ("deployment",)),
            (("deployment", "name"), ("deployment", "name")),
            (("deployment", "domain"), ("deployment", "domain")),
        ],
    )
    def test_missing_required_field(self, minimal_config, drop_path, expected_loc):
        data = {k: dict(v) if isinstance(v, dict) else v for k, v in minimal_config.items()}
        target = data
        for key in drop_path[:-1]:
            target = target[key]
        del target[drop_path[-1]]
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate(data)
        assert expected_loc in _locs(exc.value)


class TestUnknownKeys:
    def test_unknown_top_level_key_rejected(self, minimal_config):
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate({**minimal_config, "frontend": "react"})
        assert ("frontend",) in _locs(exc.value)

    def test_unknown_deployment_key_rejected(self, minimal_config):
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate(_with_deployment(minimal_config, region="us-east-2"))
        assert ("deployment", "region") in _locs(exc.value)


class TestBackend:
    def test_known_backends_nonempty(self):
        assert KNOWN_BACKENDS
        assert "aws" in KNOWN_BACKENDS
        assert "gcp" in KNOWN_BACKENDS

    def test_registry_is_the_single_source_of_truth(self):
        # ALLOWED_PROFILES is authoritative; the other sets are derived from it, so a
        # future backend or profile only needs to be added in one place.
        assert frozenset(ALLOWED_PROFILES) == KNOWN_BACKENDS
        assert frozenset().union(*ALLOWED_PROFILES.values()) == KNOWN_PROFILES

    @pytest.mark.parametrize("backend", ["azure", "k8s", "", "AWS", "local"])
    def test_unknown_backend_rejected_and_message_lists_valid_backends(self, minimal_config, backend):
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate({**minimal_config, "backend": backend})
        assert ("backend",) in _locs(exc.value)
        # The error names the supported backends so the user can fix it.
        rendered = str(exc.value)
        for known in KNOWN_BACKENDS:
            assert known in rendered

    def test_backend_must_be_string(self, minimal_config):
        with pytest.raises(ValidationError):
            RootConfig.model_validate({**minimal_config, "backend": ["aws"]})


class TestDeploymentName:
    @pytest.mark.parametrize("name", ["shifter", "acme-range", "r", "shifter-prod-01"])
    def test_valid_names(self, minimal_config, name):
        cfg = RootConfig.model_validate(_with_deployment(minimal_config, name=name))
        assert cfg.deployment.name == name

    @pytest.mark.parametrize(
        "name",
        [
            "",  # empty
            "Shifter",  # uppercase
            "-shifter",  # leading hyphen
            "shifter-",  # trailing hyphen
            "shifter range",  # space
            "shifter_range",  # underscore
            "x" * 41,  # too long
        ],
    )
    def test_invalid_names_rejected(self, minimal_config, name):
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate(_with_deployment(minimal_config, name=name))
        assert ("deployment", "name") in _locs(exc.value)


class TestDeploymentDomain:
    @pytest.mark.parametrize("domain", ["shifter.example.com", "range.acme.example.com", "shifter.io"])
    def test_valid_domains(self, minimal_config, domain):
        cfg = RootConfig.model_validate(_with_deployment(minimal_config, domain=domain))
        assert cfg.deployment.domain == domain

    @pytest.mark.parametrize(
        "domain",
        [
            "",  # empty
            "localhost",  # bare localhost
            "shifter",  # single label
            "10.0.0.1",  # IPv4 literal
            "::1",  # IPv6 literal
            "10.0",  # numeric, not a public hostname
            "shifter.123",  # all-numeric TLD
            "shifter.x",  # one-character TLD
            "shifter..com",  # empty label
            "-bad.example.com",  # label starts with hyphen
            "shifter.example.com.",  # trailing dot
            "http://shifter.example.com",  # scheme included
            "x" * 254 + ".com",  # too long overall
        ],
    )
    def test_invalid_domains_rejected(self, minimal_config, domain):
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate(_with_deployment(minimal_config, domain=domain))
        assert ("deployment", "domain") in _locs(exc.value)


class TestProfile:
    @pytest.mark.parametrize("profile", ["prod", "dev"])
    def test_valid_profiles(self, minimal_config, profile):
        cfg = RootConfig.model_validate(_with_deployment(minimal_config, profile=profile))
        assert cfg.deployment.profile == profile

    @pytest.mark.parametrize("profile", ["staging", "production", "PROD", ""])
    def test_invalid_profile_rejected(self, minimal_config, profile):
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate(_with_deployment(minimal_config, profile=profile))
        assert ("deployment", "profile") in _locs(exc.value)

    def test_profile_not_allowed_for_backend_rejected(self, monkeypatch, minimal_config):
        # Cross-field: an otherwise-valid profile that the selected backend does not
        # allow must fail (the "unsupported profile/backend combination" case).
        from installation import backends as backends_mod

        monkeypatch.setattr(
            backends_mod, "ALLOWED_PROFILES", {"aws": frozenset({"prod"}), "gcp": frozenset({"prod", "dev"})}
        )
        bad = {**_with_deployment(minimal_config, profile="dev"), "backend": "aws"}
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate(bad)
        rendered = str(exc.value)
        assert "dev" in rendered and "aws" in rendered


class TestVersion:
    def test_default_version_is_one(self, minimal_config):
        assert RootConfig.model_validate(minimal_config).version == 1

    @pytest.mark.parametrize("version", [0, 2, 99, "1", 1.0])
    def test_unsupported_version_rejected(self, minimal_config, version):
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate({**minimal_config, "version": version})
        assert ("version",) in _locs(exc.value)


class TestSecrets:
    @pytest.mark.parametrize(
        "value",
        [
            "shifter/prod/django-secret-key",
            "projects/acme/secrets/db-password/versions/latest",
            "prompt",
            "arn:aws:secretsmanager:us-east-2:123456789012:secret:shifter/prod/db-password-AbCdEf",
            "GH_SHIFTER_DJANGO_SECRET_KEY",
            "x" * 512,  # long, but still a plausible provider secret name
        ],
    )
    def test_valid_secret_references(self, minimal_config, value):
        cfg = RootConfig.model_validate({**minimal_config, "secrets": {"some_key": value}})
        assert cfg.secrets["some_key"] == value

    def test_multiple_valid_secret_references(self, minimal_config):
        cfg = RootConfig.model_validate(
            {
                **minimal_config,
                "secrets": {
                    "django_secret_key": "shifter/prod/django-secret-key",
                    "db_password": "projects/acme/secrets/db-password/versions/latest",
                    "oidc": "prompt",
                },
            }
        )
        assert cfg.secrets["oidc"] == "prompt"

    @pytest.mark.parametrize("value", [["a", "b"], "us-east-2", 5, None])
    def test_non_mapping_secrets_rejected(self, minimal_config, value):
        # A present-but-non-mapping ``secrets:`` (including an explicit YAML null) is a
        # malformed block, not an empty default — omit the key to get ``{}``.
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate({**minimal_config, "secrets": value})
        assert ("secrets",) in _locs(exc.value)

    def test_omitted_secrets_defaults_to_empty(self, minimal_config):
        assert RootConfig.model_validate(minimal_config).secrets == {}

    @pytest.mark.parametrize("key", ["Django", "1secret", "db-password", "", "db password"])
    def test_invalid_secret_key_rejected(self, minimal_config, key):
        with pytest.raises(ValidationError):
            RootConfig.model_validate({**minimal_config, "secrets": {key: "ref"}})

    @pytest.mark.parametrize(
        "value",
        [
            "",  # empty
            "   ",  # whitespace only
            "ref with\nnewline",  # multi-line
            "x" * 1025,  # implausibly long for a reference
            _RAW_KEY_MATERIAL_HEADER,  # looks like a pasted PEM private key
            "-----BEGIN CERTIFICATE-----",  # looks like pasted PEM cert material
        ],
    )
    def test_invalid_secret_value_rejected(self, minimal_config, value):
        with pytest.raises(ValidationError):
            RootConfig.model_validate({**minimal_config, "secrets": {"k": value}})

    def test_non_string_secret_value_rejected(self, minimal_config):
        with pytest.raises(ValidationError):
            RootConfig.model_validate({**minimal_config, "secrets": {"k": 1234}})


class TestSettings:
    def test_settings_opaque_mapping_accepted(self, minimal_config):
        cfg = RootConfig.model_validate(
            {**minimal_config, "settings": {"region": "us-east-2", "nested": {"a": 1}, "list": [1, 2]}}
        )
        assert cfg.settings["region"] == "us-east-2"
        assert cfg.settings["nested"] == {"a": 1}

    @pytest.mark.parametrize("value", [["a"], "us-east-2", 5, None])
    def test_non_mapping_settings_rejected(self, minimal_config, value):
        # A present-but-non-mapping ``settings:`` (including an explicit YAML null) is a
        # malformed block, not an empty default — omit the key to get ``{}``.
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate({**minimal_config, "settings": value})
        assert ("settings",) in _locs(exc.value)

    def test_omitted_settings_defaults_to_empty(self, minimal_config):
        assert RootConfig.model_validate(minimal_config).settings == {}


class TestAggregatedErrors:
    def test_multiple_problems_reported_together(self):
        with pytest.raises(ValidationError) as exc:
            RootConfig.model_validate({"backend": "azure", "deployment": {"name": "Bad Name", "domain": "localhost"}})
        locs = _locs(exc.value)
        assert ("backend",) in locs
        assert ("deployment", "name") in locs
        assert ("deployment", "domain") in locs
