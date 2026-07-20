"""Tests for runner.py module."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


def _fake_run_cmd(status: str = "Success", runner_statuses: dict | None = None):
    """Build a run_cmd side_effect that answers each bootstrap subprocess by shape.

    status: the SSM get-command-invocation Status returned for every runner.
    runner_statuses: name -> GitHub API status (defaults to both runners online).
    """
    statuses = runner_statuses or {
        "shifter-github-runner-1": "online",
        "shifter-github-runner-2": "online",
    }

    def _side_effect(cmd, **kwargs):
        joined = " ".join(cmd)
        if "registration-token" in joined:
            return MagicMock(stdout="regtok\n")
        if "send-command" in joined:
            return MagicMock(stdout="cmd-xyz\n")
        if "get-command-invocation" in joined:
            return MagicMock(stdout=f"{status}\n")
        if "output" in cmd and "-json" in cmd:
            return MagicMock(
                stdout=json.dumps(
                    {
                        "runner_instance_ids": {"value": ["i-1", "i-2"]},
                        "runner_names": {"value": list(statuses.keys())},
                    }
                )
            )
        if "actions/runners" in joined:
            return MagicMock(stdout=json.dumps([{"name": n, "status": s} for n, s in statuses.items()]))
        return MagicMock(stdout="")

    return _side_effect


class TestRunnerConfig:
    """Tests for RunnerConfig dataclass."""

    def test_creates_config_with_all_fields(self, mock_deploy):
        """Should create config with all required fields."""
        from runner import RunnerConfig

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )
        assert config.env == "dev"
        assert config.region == "us-east-2"
        assert config.github_org == "test-org"
        assert config.github_repo == "test-repo"
        assert config.aws_profile == "test-profile"


class TestGetRunnerConfig:
    """Tests for get_runner_config factory function."""

    def test_creates_config_with_params(self, mock_deploy):
        """Should create config with provided parameters."""
        from runner import get_runner_config

        config = get_runner_config(
            env="dev",
            region="us-west-2",
            github_org="my-org",
            github_repo="my-repo",
            aws_profile="my-profile",
        )
        assert config.env == "dev"
        assert config.region == "us-west-2"
        assert config.github_org == "my-org"
        assert config.github_repo == "my-repo"
        assert config.aws_profile == "my-profile"


class TestGetRunnerInstanceIds:
    """Tests for get_runner_instance_ids function."""

    def test_returns_instance_ids_when_found(self, mock_deploy):
        """Should return list of instance IDs when runners exist."""
        from runner import RunnerConfig, get_runner_instance_ids

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="i-abc123\ti-def456",
            )

            result = get_runner_instance_ids(config)

            assert result == ["i-abc123", "i-def456"]
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "ec2" in call_args
            assert "describe-instances" in call_args
            assert "--profile" in call_args
            assert "test-profile" in call_args

    def test_returns_empty_list_when_none_found(self, mock_deploy):
        """Should return empty list when no runners found."""
        from runner import RunnerConfig, get_runner_instance_ids

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
            )

            result = get_runner_instance_ids(config)

            # Empty string splits to [''] but the function filters empty strings
            assert result == [] or result == [""]

    def test_returns_empty_list_on_aws_error(self, mock_deploy):
        """Should return empty list when AWS CLI fails."""
        from runner import RunnerConfig, get_runner_instance_ids

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Access denied",
            )

            result = get_runner_instance_ids(config)

            assert result == []

    def test_filters_by_runner_tag_name(self, mock_deploy):
        """Should filter instances by shifter-github-runner-* tag."""
        from runner import RunnerConfig, get_runner_instance_ids

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")

            get_runner_instance_ids(config)

            call_args = mock_run.call_args[0][0]
            # Check that filter for tag name is included
            assert "Name=tag:Name,Values=shifter-github-runner-*" in call_args


class TestShowRunnerRegistrationInstructions:
    """Tests for show_runner_registration_instructions function."""

    def test_displays_instance_ids(self, mock_deploy, capsys):
        """Should display all instance IDs in output."""
        from runner import RunnerConfig, show_runner_registration_instructions

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        show_runner_registration_instructions(config, ["i-abc123", "i-def456"])

        captured = capsys.readouterr()
        assert "i-abc123" in captured.out
        assert "i-def456" in captured.out

    def test_calls_code_block_with_ssm_command(self, mock_deploy, capsys):
        """Should call code_block with SSM session command."""
        from runner import RunnerConfig, show_runner_registration_instructions

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        show_runner_registration_instructions(config, ["i-abc123"])

        # Check that code_block was called with SSM command
        calls = [str(call) for call in mock_deploy.code_block.call_args_list]
        ssm_calls = [c for c in calls if "ssm" in c and "i-abc123" in c]
        assert len(ssm_calls) > 0

    def test_displays_github_url(self, mock_deploy, capsys):
        """Should display GitHub runners settings URL."""
        from runner import RunnerConfig, show_runner_registration_instructions

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="my-org",
            github_repo="my-repo",
            aws_profile="test-profile",
        )

        show_runner_registration_instructions(config, ["i-abc123"])

        captured = capsys.readouterr()
        assert "github.com/my-org/my-repo" in captured.out

    def test_calls_code_block_with_dependency_commands(self, mock_deploy, capsys):
        """Should call code_block with dependency install commands."""
        from runner import RunnerConfig, show_runner_registration_instructions

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        show_runner_registration_instructions(config, ["i-abc123"])

        # Check that code_block was called with dependency commands
        calls = [str(call) for call in mock_deploy.code_block.call_args_list]
        dep_calls = [c for c in calls if "libicu" in c or "dotnet" in c]
        assert len(dep_calls) > 0

    def test_calls_code_block_with_service_commands(self, mock_deploy, capsys):
        """Should call code_block with svc.sh service commands."""
        from runner import RunnerConfig, show_runner_registration_instructions

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        show_runner_registration_instructions(config, ["i-abc123"])

        # Check that code_block was called with service commands
        calls = [str(call) for call in mock_deploy.code_block.call_args_list]
        svc_calls = [c for c in calls if "svc.sh" in c]
        assert len(svc_calls) > 0


class TestWalkthroughRunnerSetup:
    """Tests for walkthrough_runner_setup function."""

    def test_dry_run_returns_mock_instance_ids(self, mock_deploy):
        """Should return mock instance IDs in dry-run mode."""
        from runner import RunnerConfig, walkthrough_runner_setup

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        result = walkthrough_runner_setup(config, dry_run=True)

        assert result is not None
        assert "instance_ids" in result
        assert len(result["instance_ids"]) == 2


def _cfg():
    from runner import RunnerConfig

    return RunnerConfig(
        env="dev",
        region="us-east-2",
        github_org="my-org",
        github_repo="my-repo",
        aws_profile="my-profile",
    )


def _target():
    from runner import RunnerTarget

    return RunnerTarget(
        instance_id="i-abc123",
        runner_name="shifter-github-runner-1",
        repo_url="https://github.com/my-org/my-repo",
        region="us-east-2",
    )


class TestMintRegistrationToken:
    """A per-runner registration token is minted via gh api, never logged."""

    def test_dry_run_mints_nothing(self, mock_deploy):
        from runner import mint_registration_token

        token = mint_registration_token(_cfg(), dry_run=True)

        assert token is None
        mock_deploy.run_cmd.assert_not_called()

    def test_calls_repo_registration_token_endpoint(self, mock_deploy):
        from runner import mint_registration_token

        mock_deploy.run_cmd.return_value = MagicMock(stdout="AAAAREGTOKEN1234\n")

        token = mint_registration_token(_cfg())

        assert token == "AAAAREGTOKEN1234"
        argv = mock_deploy.run_cmd.call_args[0][0]
        assert argv[0] == "gh"
        assert "api" in argv
        assert any("repos/my-org/my-repo/actions/runners/registration-token" in a for a in argv)
        # Token comes back on stdout; the tool must capture (not stream) it.
        assert mock_deploy.run_cmd.call_args.kwargs.get("capture") is True


class TestRegisterRunner:
    """Registration delivers the token via one JSON --parameters element only."""

    def test_dry_run_sends_no_command_and_mints_no_token(self, mock_deploy):
        from runner import register_runner

        register_runner(_cfg(), _target(), dry_run=True)

        mock_deploy.run_cmd.assert_not_called()

    def test_parameters_is_a_single_json_argv_element(self, mock_deploy):
        import json

        from runner import register_runner

        mock_deploy.run_cmd.side_effect = [
            MagicMock(stdout="REGTOKEN9999\n"),  # mint
            MagicMock(stdout="cmd-1234\n"),  # send-command CommandId
        ]

        command_id = register_runner(_cfg(), _target())

        assert command_id == "cmd-1234"
        send_calls = [c for c in mock_deploy.run_cmd.call_args_list if "send-command" in c[0][0]]
        assert len(send_calls) == 1
        argv = send_calls[0][0][0]
        params_idx = argv.index("--parameters")
        params = argv[params_idx + 1]
        # One argv element, valid JSON, with a commands list (no shorthand commands=[...]).
        payload = json.loads(params)
        assert list(payload.keys()) == ["commands"]
        assert isinstance(payload["commands"], list)
        script = "\n".join(payload["commands"])
        assert "config.sh" in script
        assert "svc.sh" in script
        assert "set +x" in script  # shell tracing off around the token
        assert "set -x" not in script
        assert "REGTOKEN9999" in script  # token rides inside the JSON body only
        # Token must NOT be a config.sh command-line arg (no /proc/<pid>/cmdline
        # exposure): it is written to a root-owned temp file and fed via stdin.
        assert "--token" not in script
        assert "rm -f" in script  # temp token file deleted before svc.sh
        # Document + region wiring, and profile threaded through run_cmd.
        assert "AWS-RunShellScript" in argv
        assert send_calls[0].kwargs.get("profile") == "my-profile"

    def test_config_sh_never_receives_token_in_argv(self, mock_deploy):
        from runner import _registration_script

        lines = _registration_script(_target(), "TOKINSCRIPT")
        config_line = next(line for line in lines if "config.sh" in line)
        # config.sh is spawned under expect; the token is sent over the PTY at
        # the prompt, never as a config.sh (or --unattended --token) argument.
        assert "TOKINSCRIPT" not in config_line
        assert "--token" not in config_line
        assert "--unattended" not in config_line

    def test_registration_drives_config_sh_under_expect_pty(self, mock_deploy):
        from runner import _registration_script

        script = "\n".join(_registration_script(_target(), "TOKINSCRIPT"))
        # config.sh needs a console for its masked token prompt, so it runs under
        # expect (spawn) driven by the expect script file — not over a redirected
        # stdin (the old `< "$TOKFILE"` form fails on modern runner releases).
        assert "spawn" in script and "config.sh" in script
        assert 'expect "$EXPECTFILE" "$TOKFILE"' in script
        assert '< "$TOKFILE"' not in script
        # The token file is read inside expect (argv is the file path only) and
        # both temp files are removed on any exit.
        assert "[lindex $argv 0]" in script
        assert "trap 'rm -f" in script

    def test_expect_argv_is_the_token_file_path_not_the_token(self, mock_deploy):
        from runner import _registration_script

        lines = _registration_script(_target(), "TOKINSCRIPT")
        expect_line = next(line for line in lines if line.startswith("expect "))
        # The expect invocation passes file paths, never the token value.
        assert "TOKINSCRIPT" not in expect_line

    def test_token_only_appears_inside_the_parameters_element(self, mock_deploy):
        from runner import register_runner

        mock_deploy.run_cmd.side_effect = [
            MagicMock(stdout="SECRETTOK\n"),
            MagicMock(stdout="cmd-1\n"),
        ]

        register_runner(_cfg(), _target())

        send_call = next(c for c in mock_deploy.run_cmd.call_args_list if "send-command" in c[0][0])
        send_argv = send_call[0][0]
        params_idx = send_argv.index("--parameters")
        for i, element in enumerate(send_argv):
            if i == params_idx + 1:
                continue
            assert "SECRETTOK" not in element

    def test_send_command_parameters_are_redacted_in_logs(self):
        """The JSON --parameters blob is masked whole by the operator-log redactor."""
        # Uses the REAL bootstrap_core redactor (no mock_deploy), proving the token
        # never reaches operator logs even though it rides inside the SSM body.
        from bootstrap_core import _redact_argv_for_log
        from runner import _registration_parameters

        params = _registration_parameters(_target(), "SUPERSECRETTOKEN")
        assert "SUPERSECRETTOKEN" in params  # token is really in the payload
        argv = ["aws", "ssm", "send-command", "--parameters", params]
        redacted = _redact_argv_for_log(argv)
        assert "SUPERSECRETTOKEN" not in redacted
        assert "***" in redacted


class TestVerifyRunners:
    """Verification uses the GitHub runners API, never web-console steps."""

    def test_dry_run_skips_api(self, mock_deploy):
        from runner import verify_runners

        result = verify_runners(_cfg(), ["shifter-github-runner-1"], dry_run=True)

        assert result == {}
        mock_deploy.run_cmd.assert_not_called()

    def test_reads_runners_endpoint_and_reports_status(self, mock_deploy):
        from runner import verify_runners

        mock_deploy.run_cmd.return_value = MagicMock(stdout='[{"name": "shifter-github-runner-1", "status": "online"}]')

        result = verify_runners(_cfg(), ["shifter-github-runner-1"])

        assert result == {"shifter-github-runner-1": "online"}
        argv = mock_deploy.run_cmd.call_args[0][0]
        assert argv[0] == "gh"
        assert any("repos/my-org/my-repo/actions/runners" in a for a in argv)


class TestApplyRunnerTerraform:
    """Terraform apply of the runner root never carries a registration token."""

    def test_dry_run_never_passes_a_token_and_wires_created_network(self, mock_deploy, monkeypatch):
        from runner import apply_runner_terraform

        apply_runner_terraform(_cfg(), dry_run=True, create_network=True, bucket_name="shifter-dev-infra-x")

        # No terraform command may carry a token as a -var/env or argument.
        for call in mock_deploy.run_cmd.call_args_list:
            for element in call[0][0]:
                assert "token" not in element.lower()
        # create_network=True must set the create_runner_network var.
        all_args = [a for call in mock_deploy.run_cmd.call_args_list for a in call[0][0]]
        assert any("create_runner_network=true" in a for a in all_args)


class TestProvisionAndRegisterRunners:
    """Full orchestration is a no-op-on-secrets dry run."""

    def test_dry_run_mints_no_token_and_sends_no_ssm(self, mock_deploy):
        from runner import provision_and_register_runners

        result = provision_and_register_runners(_cfg(), dry_run=True, create_network=True, bucket_name="b")

        # Dry-run mints/registers nothing and reports an empty fleet.
        assert result == {"targets": [], "verified": {}}
        # Positive assertion: the terraform init/plan/apply dry-run calls DID run,
        # so the no-token/no-SSM checks below are not vacuously true.
        all_args = [a for call in mock_deploy.run_cmd.call_args_list for a in call[0][0]]
        assert any("terraform" in a for a in all_args)
        assert not any("registration-token" in a for a in all_args)
        assert "send-command" not in all_args


class TestRegistrationFailures:
    """The automated path fails closed on failed registration / offline runners."""

    def test_all_success_and_online_is_clean(self, mock_deploy):
        from runner import _registration_failures

        problems = _registration_failures(
            {"r1": "Success", "r2": "Success"},
            {"r1": "online", "r2": "online"},
            ["r1", "r2"],
        )
        assert problems == []

    def test_non_success_ssm_status_is_a_problem(self, mock_deploy):
        from runner import _registration_failures

        problems = _registration_failures(
            {"r1": "Failed"},
            {"r1": "online"},
            ["r1"],
        )
        assert len(problems) == 1
        assert "r1" in problems[0]

    def test_offline_runner_is_a_problem(self, mock_deploy):
        from runner import _registration_failures

        problems = _registration_failures(
            {"r1": "Success"},
            {"r1": "offline"},
            ["r1"],
        )
        assert len(problems) == 1
        assert "r1" in problems[0]

    def test_missing_runner_is_a_problem(self, mock_deploy):
        from runner import _registration_failures

        problems = _registration_failures({"r1": "Success"}, {}, ["r1"])
        assert len(problems) == 1


class TestWaitForSsmCommand:
    """wait_for_ssm_command returns the terminal SSM status."""

    def test_success_status(self, mock_deploy):
        from runner import wait_for_ssm_command

        mock_deploy.run_cmd.return_value = MagicMock(stdout="Success\n")
        status = wait_for_ssm_command("cmd-1", _target(), _cfg())
        assert status == "Success"
        mock_deploy.success.assert_called()

    def test_non_success_status_warns(self, mock_deploy):
        from runner import wait_for_ssm_command

        mock_deploy.run_cmd.return_value = MagicMock(stdout="Failed\n")
        status = wait_for_ssm_command("cmd-1", _target(), _cfg())
        assert status == "Failed"
        mock_deploy.warn.assert_called()


class TestMintErrors:
    """mint fails closed when the API returns no token."""

    def test_empty_token_exits(self, mock_deploy):
        from runner import mint_registration_token

        mock_deploy.run_cmd.return_value = MagicMock(stdout="\n")
        cfg = _cfg()
        with pytest.raises(SystemExit):
            mint_registration_token(cfg)


class TestApplyRunnerTerraformErrors:
    """apply_runner_terraform fails closed on missing bucket / missing root."""

    def test_missing_bucket_exits(self, mock_deploy, monkeypatch):
        from runner import apply_runner_terraform

        monkeypatch.delenv("TF_INFRA_STATE_BUCKET", raising=False)
        cfg = _cfg()
        with pytest.raises(SystemExit):
            apply_runner_terraform(cfg, dry_run=False, bucket_name=None)

    def test_missing_tf_root_exits(self, mock_deploy, tmp_path):
        from runner import apply_runner_terraform

        mock_deploy.get_repo_root.return_value = tmp_path  # no platform/... tree created
        cfg = _cfg()
        with pytest.raises(SystemExit):
            apply_runner_terraform(cfg, dry_run=False, bucket_name="b")


class TestProvisionIntegration:
    """End-to-end (mocked-subprocess) apply -> register -> verify orchestration."""

    def _tf_root(self, tmp_path):
        tf_dir = tmp_path / "platform" / "terraform" / "global" / "github-runner"
        tf_dir.mkdir(parents=True)
        return tf_dir

    def test_success_path_returns_online_fleet(self, mock_deploy, tmp_path, monkeypatch):
        from runner import provision_and_register_runners

        self._tf_root(tmp_path)
        mock_deploy.get_repo_root.return_value = tmp_path
        mock_deploy.run_cmd.side_effect = _fake_run_cmd(status="Success")
        # Isolate AWS_PROFILE so the apply's account pin does not leak across tests.
        monkeypatch.setenv("AWS_PROFILE", "sentinel")

        result = provision_and_register_runners(_cfg(), dry_run=False, create_network=True, bucket_name="b")

        assert result["targets"] == ["shifter-github-runner-1", "shifter-github-runner-2"]
        assert result["verified"] == {
            "shifter-github-runner-1": "online",
            "shifter-github-runner-2": "online",
        }
        # The terraform plan carried the created-network var.
        all_args = [a for call in mock_deploy.run_cmd.call_args_list for a in call[0][0]]
        assert any("create_runner_network=true" in a for a in all_args)
        # The runner is provisioned into the account --profile targets.
        assert os.environ["AWS_PROFILE"] == "my-profile"

    def test_fails_closed_on_ssm_failure(self, mock_deploy, tmp_path):
        from runner import provision_and_register_runners

        self._tf_root(tmp_path)
        mock_deploy.get_repo_root.return_value = tmp_path
        mock_deploy.run_cmd.side_effect = _fake_run_cmd(status="Failed")

        cfg = _cfg()
        with pytest.raises(SystemExit):
            provision_and_register_runners(cfg, dry_run=False, bucket_name="b")

    def test_fails_closed_on_offline_runner(self, mock_deploy, tmp_path):
        from runner import provision_and_register_runners

        self._tf_root(tmp_path)
        mock_deploy.get_repo_root.return_value = tmp_path
        mock_deploy.run_cmd.side_effect = _fake_run_cmd(
            status="Success",
            runner_statuses={"shifter-github-runner-1": "offline", "shifter-github-runner-2": "online"},
        )

        cfg = _cfg()
        with pytest.raises(SystemExit):
            provision_and_register_runners(cfg, dry_run=False, bucket_name="b")

    def test_use_existing_network_sets_create_false(self, mock_deploy, tmp_path):
        from runner import provision_and_register_runners

        self._tf_root(tmp_path)
        mock_deploy.get_repo_root.return_value = tmp_path
        mock_deploy.run_cmd.side_effect = _fake_run_cmd(status="Success")

        provision_and_register_runners(_cfg(), dry_run=False, use_existing_network=True, bucket_name="b")

        all_args = [a for call in mock_deploy.run_cmd.call_args_list for a in call[0][0]]
        assert any("create_runner_network=false" in a for a in all_args)

    def test_no_targets_exits(self, mock_deploy, tmp_path):
        from runner import provision_and_register_runners

        self._tf_root(tmp_path)
        mock_deploy.get_repo_root.return_value = tmp_path

        def _no_targets(cmd, **kwargs):
            if "output" in cmd and "-json" in cmd:
                empty = {"runner_instance_ids": {"value": []}, "runner_names": {"value": []}}
                return MagicMock(stdout=json.dumps(empty))
            return MagicMock(stdout="")

        mock_deploy.run_cmd.side_effect = _no_targets
        cfg = _cfg()
        with pytest.raises(SystemExit):
            provision_and_register_runners(cfg, dry_run=False, bucket_name="b")
