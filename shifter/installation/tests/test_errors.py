"""Tests for the installation error model (``installation.errors``)."""

from __future__ import annotations

from installation import ConfigIssue, InstallationConfigError


class TestConfigIssue:
    def test_render_without_hint(self):
        assert ConfigIssue("deployment.domain", "must be lowercase").render() == "deployment.domain: must be lowercase"

    def test_render_with_hint(self):
        rendered = ConfigIssue("shifter.yaml", "not found", "copy an example").render()
        assert "shifter.yaml: not found" in rendered
        assert "copy an example" in rendered


class TestInstallationConfigError:
    def test_exposes_issues(self):
        issues = [ConfigIssue("backend", "unknown backend 'azure'")]
        exc = InstallationConfigError(issues)
        assert exc.issues == issues
        # The constructor stores a copy, not the caller's list.
        issues.append(ConfigIssue("x", "y"))
        assert len(exc.issues) == 1

    def test_str_lists_each_issue(self):
        exc = InstallationConfigError(
            [ConfigIssue("backend", "unknown backend 'azure'"), ConfigIssue("deployment.domain", "must be lowercase")]
        )
        text = str(exc)
        assert "2 problems" in text
        assert "backend: unknown backend 'azure'" in text
        assert "deployment.domain: must be lowercase" in text

    def test_str_single_problem_is_singular(self):
        assert "1 problem" in str(InstallationConfigError([ConfigIssue("backend", "bad")]))
        assert "1 problems" not in str(InstallationConfigError([ConfigIssue("backend", "bad")]))

    def test_str_with_no_issues_is_still_meaningful(self):
        assert str(InstallationConfigError([])) == "invalid root installation config"
