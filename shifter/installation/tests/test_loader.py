"""Tests for ``installation.loader`` — file loading and fail-fast validation."""

from __future__ import annotations

import pytest

from installation import ConfigIssue, InstallationConfigError
from installation.loader import load_root_config, validate_root_config_file
from installation.schema import RootConfig


class TestLoadRootConfig:
    def test_valid_file_returns_root_config(self, write_config, minimal_config):
        cfg = load_root_config(write_config(minimal_config))
        assert isinstance(cfg, RootConfig)
        assert cfg.backend == "aws"

    def test_accepts_str_path(self, write_config, minimal_config):
        cfg = load_root_config(str(write_config(minimal_config)))
        assert cfg.backend == "aws"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(tmp_path / "shifter.yaml")
        assert exc.value.issues
        assert "shifter.yaml" in str(exc.value)

    def test_invalid_yaml_raises(self, write_config):
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(write_config(raw="backend: [unterminated\n"))
        assert exc.value.issues
        assert "yaml" in str(exc.value).lower()

    @pytest.mark.parametrize("raw", ["- a\n- b\n", "just a string\n", ""])
    def test_non_mapping_top_level_raises(self, write_config, raw):
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(write_config(raw=raw))
        assert "mapping" in str(exc.value).lower()

    def test_duplicate_top_level_key_raises(self, write_config):
        raw = "backend: aws\ndeployment:\n  name: shifter\n  domain: shifter.example.com\nbackend: gcp\n"
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(write_config(raw=raw))
        rendered = str(exc.value).lower()
        assert "duplicate" in rendered and "backend" in rendered

    def test_duplicate_nested_key_raises(self, write_config):
        raw = "backend: aws\ndeployment:\n  name: shifter\n  name: other\n  domain: shifter.example.com\n"
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(write_config(raw=raw))
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
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(write_config(raw=raw))
        assert "merge" in str(exc.value).lower()

    def test_recursive_alias_graph_does_not_recurse_forever(self, write_config):
        # A self-referential alias graph must not blow the stack while scanning for
        # duplicate keys; it surfaces as a normal validation failure instead.
        with pytest.raises(InstallationConfigError):
            load_root_config(write_config(raw="backend: &a\n  x: *a\n"))

    def test_aggregates_all_problems(self, write_config):
        bad = {"backend": "azure", "deployment": {"name": "Bad Name", "domain": "localhost"}}
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(write_config(bad))
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
            "secrets": {"db_password": raw_value},
        }
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(write_config(bad))
        rendered = str(exc.value)
        assert raw_value not in rendered
        assert "SUPERSECRETMARKER" not in rendered
        for issue in exc.value.issues:
            assert raw_value not in issue.message
            assert raw_value not in issue.path
            assert "SUPERSECRETMARKER" not in issue.message


class TestValidateRootConfigFile:
    def test_valid_file_returns_empty_list(self, write_config, minimal_config):
        assert validate_root_config_file(write_config(minimal_config)) == []

    def test_invalid_file_returns_issue_list_without_raising(self, write_config):
        issues = validate_root_config_file(write_config({"deployment": {"name": "x"}}))
        assert issues
        assert all(isinstance(i, ConfigIssue) for i in issues)

    def test_missing_file_returns_issue_list_without_raising(self, tmp_path):
        issues = validate_root_config_file(tmp_path / "shifter.yaml")
        assert issues
        assert all(isinstance(i, ConfigIssue) for i in issues)
