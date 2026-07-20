"""Tests for bootstrap_core helpers not covered by module-specific suites.

Currently focuses on ``run_cmd_secret_stdin`` (issue #1546): the secret-stdin
subprocess path used to hand a single-use GitHub registration token to an
interactive ``config.sh`` over ``gcloud compute ssh`` without the token ever
reaching argv, the operator log, or a verbatim child-output dump.
"""

import pytest


class TestRunCmdSecretStdin:
    """The secret-stdin path never renders the secret or raw child output."""

    def test_secret_stdin_is_never_logged(self, capsys):
        from bootstrap_core import run_cmd_secret_stdin

        # `cat` echoes stdin to stdout, but the helper captures/discards child
        # output, so the token piped over stdin must not reach the operator log.
        rc = run_cmd_secret_stdin(["cat"], secret_stdin="SUPERSECRETTOKEN\n")

        assert rc == 0
        out = capsys.readouterr().out
        assert "SUPERSECRETTOKEN" not in out
        # The non-secret argv is still logged for auditability.
        assert "cat" in out

    def test_secret_present_in_argv_is_rejected(self):
        from bootstrap_core import run_cmd_secret_stdin

        # A caller must never put the token on the command line; the helper
        # fails closed rather than silently leaking it via /proc/<pid>/cmdline.
        with pytest.raises(ValueError):
            run_cmd_secret_stdin(["echo", "REGTOKEN"], secret_stdin="REGTOKEN\n")

    def test_nonzero_exit_is_returned_without_dumping_child_output(self, capsys):
        from bootstrap_core import run_cmd_secret_stdin

        # The child echoes its stdin (the secret) to stderr and fails. run_cmd's
        # verbatim-stderr dump would leak it; this path must suppress it and
        # still surface the exit code so the caller can fail closed.
        rc = run_cmd_secret_stdin(["sh", "-c", "cat 1>&2; exit 3"], secret_stdin="LEAKYTOKEN\n")

        assert rc == 3
        out = capsys.readouterr().out
        assert "LEAKYTOKEN" not in out

    def test_dry_run_does_not_execute_or_log_secret(self, capsys):
        from bootstrap_core import run_cmd_secret_stdin

        rc = run_cmd_secret_stdin(["cat"], secret_stdin="tok\n", dry_run=True)

        assert rc == 0
        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "tok" not in out


class TestConfirmAssumeYes:
    """Non-interactive proceed for confirm() via --yes/assume-yes (issue #1639)."""

    @pytest.fixture(autouse=True)
    def _reset_assume_yes(self):
        # Module-level assume-yes state must not leak between tests.
        import bootstrap_core

        bootstrap_core.set_assume_yes(False)
        yield
        bootstrap_core.set_assume_yes(False)

    def test_non_interactive_uses_default_without_assume_yes(self, monkeypatch):
        import bootstrap_core

        monkeypatch.setattr(bootstrap_core.sys.stdin, "isatty", lambda: False)
        # Without assume-yes, a non-TTY confirm() falls back to default_yes: the
        # original auto-abort behavior for prompts that default to "no".
        assert bootstrap_core.confirm("proceed?", default_yes=False) is False
        assert bootstrap_core.confirm("proceed?", default_yes=True) is True

    def test_non_interactive_proceeds_under_assume_yes(self, monkeypatch):
        import bootstrap_core

        monkeypatch.setattr(bootstrap_core.sys.stdin, "isatty", lambda: False)
        bootstrap_core.set_assume_yes(True)
        assert bootstrap_core.assume_yes_enabled() is True
        # --yes makes routine confirm() prompts proceed without a TTY instead of
        # auto-aborting on the default_yes=False fallback.
        assert bootstrap_core.confirm("proceed?", default_yes=False) is True


class TestSubprocessPagerSuppression:
    """run_cmd forces AWS_PAGER="" so aws v2 never blocks on its pager (issue #1639)."""

    def test_subprocess_env_forces_empty_aws_pager(self):
        from bootstrap_core import _subprocess_env

        assert _subprocess_env()["AWS_PAGER"] == ""

    def test_run_cmd_sets_empty_aws_pager_in_child_env(self):
        from bootstrap_core import run_cmd

        # ${AWS_PAGER+set} -> "set" when present (even empty); ${AWS_PAGER-UNSET}
        # -> the value ("") when set, else "UNSET". "set:" proves present-and-empty,
        # distinguishing a forced empty value from an unset variable.
        result = run_cmd(
            ["sh", "-c", 'printf %s "${AWS_PAGER+set}:${AWS_PAGER-UNSET}"'],
            capture=True,
        )

        assert result is not None
        assert result.stdout == "set:"
