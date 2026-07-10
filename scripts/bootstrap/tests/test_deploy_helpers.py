"""Unit tests for pure helper functions in deploy.py (issue #779 burndown)."""

import os
import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest

import deploy


class TestValidateArgv:
    def test_accepts_normal_argv(self):
        deploy._validate_argv(["aws", "s3", "ls", "--profile", "x"])

    def test_rejects_non_string_token(self):
        with pytest.raises(ValueError, match="must be a string"):
            deploy._validate_argv(["aws", 5])

    def test_rejects_nul_byte(self):
        with pytest.raises(ValueError, match="NUL byte"):
            deploy._validate_argv(["aws", "a\x00b"])


class TestRedactArgvForLog:
    def test_passes_through_plain_args(self):
        assert deploy._redact_argv_for_log(["terraform", "apply", "-auto-approve"]) == "terraform apply -auto-approve"

    def test_masks_value_after_sensitive_flag(self):
        out = deploy._redact_argv_for_log(["gcloud", "--password", "SuperSecret123!"])
        assert out == "gcloud --password ***"

    def test_masks_inline_json_document(self):
        out = deploy._redact_argv_for_log(["aws", "iam", "--policy-document", '{"Version":"2012"}'])
        assert out == "aws iam --policy-document ***"

    def test_masks_long_opaque_token(self):
        long_token = "A" * 50
        assert deploy._redact_argv_for_log(["gh", "secret", long_token]) == "gh secret ***"

    def test_keeps_arn_with_colons(self):
        arn = "arn:aws:iam::123456789012:role/github-actions"
        assert deploy._redact_argv_for_log(["aws", "x", arn]) == f"aws x {arn}"


class TestLooksLikeInlineSecret:
    def test_json_object(self):
        assert deploy._looks_like_inline_secret("{secret}")

    def test_json_array(self):
        assert deploy._looks_like_inline_secret("[1,2]")

    def test_long_opaque(self):
        assert deploy._looks_like_inline_secret("z" * 40)

    def test_short_plain_is_safe(self):
        assert not deploy._looks_like_inline_secret("ubuntu")

    def test_path_is_safe(self):
        assert not deploy._looks_like_inline_secret("/very/long/path/" + "a" * 40)


class TestResolveOperatorEmailDomain:
    def test_terraform_output_wins(self):
        outputs = {"identity_allowed_email_domain": {"value": "Example.COM"}}
        domain, source = deploy._resolve_operator_email_domain(outputs)
        assert domain == "example.com"
        assert "Terraform output" in source

    def test_env_fallback(self):
        with mock.patch.dict(os.environ, {"SHIFTER_GCP_OPERATOR_EMAIL_DOMAIN": "Foo.Org"}, clear=False):
            domain, source = deploy._resolve_operator_email_domain(None)
        assert domain == "foo.org"
        assert source == "SHIFTER_GCP_OPERATOR_EMAIL_DOMAIN"

    def test_no_constraint(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHIFTER_GCP_OPERATOR_EMAIL_DOMAIN", None)
            assert deploy._resolve_operator_email_domain(None) == ("", "")


class TestMissingDependencyLines:
    # Use real PATH lookups (the function's process boundary) rather than mocking
    # the first-party shutil seam (ADR-019). "sh" exists on every POSIX runner;
    # a random name never does.
    _MISSING = "shifter-nonexistent-tool-zzz"

    def test_reports_missing(self):
        lines = deploy._missing_dependency_lines({"sh": "POSIX shell", self._MISSING: "Gone tool"})
        assert lines == [f"  - {self._MISSING}: Gone tool"]

    def test_all_present(self):
        assert deploy._missing_dependency_lines({"sh": "POSIX shell"}) == []


class TestTerraformHelpersFailurePaths:
    # Mock subprocess (a process boundary, allowed by ADR-019) so the helpers'
    # failure/exit branches run without a real terraform invocation.
    def test_apply_iam_exits_when_apply_fails(self):
        cfg = SimpleNamespace(env="prod")
        with (
            mock.patch.object(deploy.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)),
            pytest.raises(SystemExit),
        ):
            deploy._terraform_apply_iam(cfg, dry_run=False)

    def test_role_arn_exits_when_output_fails(self):
        cfg = SimpleNamespace(role_name="github-actions")
        with (
            mock.patch.object(deploy.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, stdout="")),
            pytest.raises(SystemExit),
        ):
            deploy._terraform_iam_role_arn(cfg, "123456789012", dry_run=False)

    def test_role_arn_dry_run_is_synthetic(self):
        cfg = SimpleNamespace(role_name="github-actions")
        arn = deploy._terraform_iam_role_arn(cfg, "123456789012", dry_run=True)
        assert arn == "arn:aws:iam::123456789012:role/github-actions"
