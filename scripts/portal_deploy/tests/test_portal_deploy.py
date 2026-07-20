import json
import subprocess
import unittest

from scripts.portal_deploy import portal_deploy


class PortalDeployTopologyTests(unittest.TestCase):
    def test_asg_topology_resolves_from_terraform_outputs(self) -> None:
        topology = portal_deploy.TerraformTopology(
            enable_autoscaling=True,
            ec2_instance_id="",
            asg_name="dev-portal-asg-abc123",
        )

        resolved = portal_deploy.resolve_topology(
            topology,
            running_instance_ids=[],
            asg_exists=True,
        )

        self.assertEqual(resolved.mode, "asg")
        self.assertEqual(resolved.asg_name, "dev-portal-asg-abc123")
        self.assertEqual(resolved.enable_autoscaling_output, "true")

    def test_single_instance_topology_requires_exactly_one_tagged_instance(self) -> None:
        topology = portal_deploy.TerraformTopology(
            enable_autoscaling=False,
            ec2_instance_id="i-123",
            asg_name="",
        )

        resolved = portal_deploy.resolve_topology(
            topology,
            running_instance_ids=["i-123"],
            asg_exists=False,
        )

        self.assertEqual(resolved.mode, "single")
        self.assertEqual(resolved.instance_id, "i-123")
        self.assertEqual(resolved.enable_autoscaling_output, "false")

    def test_asg_enabled_without_asg_name_fails_loud(self) -> None:
        topology = portal_deploy.TerraformTopology(
            enable_autoscaling=True,
            ec2_instance_id="",
            asg_name="",
        )

        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "ASG mode"):
            portal_deploy.resolve_topology(
                topology,
                running_instance_ids=[],
                asg_exists=False,
            )

    def test_asg_enabled_with_single_instance_output_fails_loud(self) -> None:
        topology = portal_deploy.TerraformTopology(
            enable_autoscaling=True,
            ec2_instance_id="i-stale",
            asg_name="dev-portal-asg-abc123",
        )

        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "ec2_instance_id"):
            portal_deploy.resolve_topology(topology, running_instance_ids=[], asg_exists=True)

    def test_single_instance_enabled_with_asg_output_fails_loud(self) -> None:
        topology = portal_deploy.TerraformTopology(
            enable_autoscaling=False,
            ec2_instance_id="i-123",
            asg_name="dev-portal-asg-abc123",
        )

        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "asg_name"):
            portal_deploy.resolve_topology(
                topology,
                running_instance_ids=["i-123"],
                asg_exists=False,
            )

    def test_single_instance_mode_rejects_multiple_tagged_instances(self) -> None:
        topology = portal_deploy.TerraformTopology(
            enable_autoscaling=False,
            ec2_instance_id="i-123",
            asg_name="",
        )

        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "exactly one"):
            portal_deploy.resolve_topology(
                topology,
                running_instance_ids=["i-123", "i-456"],
                asg_exists=False,
            )

    def test_single_instance_mode_rejects_tag_mismatch(self) -> None:
        topology = portal_deploy.TerraformTopology(
            enable_autoscaling=False,
            ec2_instance_id="i-expected",
            asg_name="",
        )

        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "does not match"):
            portal_deploy.resolve_topology(
                topology,
                running_instance_ids=["i-observed"],
                asg_exists=False,
            )

    def test_parse_terraform_output_json_requires_boolean_mode(self) -> None:
        raw = """
        {
          "enable_autoscaling": {"value": true},
          "ec2_instance_id": {"value": ""},
          "asg_name": {"value": "dev-portal-asg-abc123"}
        }
        """

        topology = portal_deploy.parse_terraform_outputs(raw)

        self.assertTrue(topology.enable_autoscaling)
        self.assertEqual(topology.asg_name, "dev-portal-asg-abc123")

    def test_parse_terraform_output_json_rejects_missing_mode(self) -> None:
        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "enable_autoscaling"):
            portal_deploy.parse_terraform_outputs('{"asg_name": {"value": "asg"}}')


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.responses: list[subprocess.CompletedProcess[str]] = []

    def queue(self, stdout: str = "") -> None:
        self.responses.append(subprocess.CompletedProcess([], 0, stdout=stdout, stderr=""))

    def __call__(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        check: bool,
        text: bool,
        stdout: int,
        stderr: int,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check, text, stdout, stderr
        self.calls.append(command)
        if not self.responses:
            raise AssertionError(f"unexpected command: {command}")
        return self.responses.pop(0)


class PortalDeployAsgVerificationTests(unittest.TestCase):
    def test_verify_asg_image_digest_checks_every_in_service_instance(self) -> None:
        runner = FakeRunner()
        runner.queue("i-1\ti-2\n")
        runner.queue("cmd-123\n")
        runner.queue("")
        runner.queue("Success\n")
        runner.queue("")
        runner.queue("Success\n")

        checked = portal_deploy.verify_asg_image_digest(
            asg_name="dev-portal-asg-abc123",
            image_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            runner=runner,
        )

        self.assertEqual(checked, ["i-1", "i-2"])
        self.assertIn("send-command", runner.calls[1])
        self.assertIn("i-1", runner.calls[1])
        self.assertIn("i-2", runner.calls[1])
        self.assertIn(
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            " ".join(runner.calls[1]),
        )
        wait_calls = [
            call
            for call in runner.calls
            if call[:4] == ["aws", "ssm", "wait", "command-executed"]
        ]
        invocation_calls = [
            call
            for call in runner.calls
            if call[:3] == ["aws", "ssm", "get-command-invocation"]
        ]
        self.assertEqual([call[4] for call in wait_calls], ["--command-id", "--command-id"])
        for call in [*wait_calls, *invocation_calls]:
            self.assertIn("cmd-123", call)

    def test_verify_asg_image_digest_rejects_empty_asg(self) -> None:
        runner = FakeRunner()
        runner.queue("\n")

        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "No in-service"):
            portal_deploy.verify_asg_image_digest(
                asg_name="dev-portal-asg-abc123",
                image_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                runner=runner,
            )

    def test_verify_asg_image_digest_rejects_empty_digest(self) -> None:
        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "image digest"):
            portal_deploy.verify_asg_image_digest(
                asg_name="dev-portal-asg-abc123",
                image_digest="",
            )

    def test_verify_asg_image_digest_retries_transient_non_success(self) -> None:
        # #1397: a just-in-service instance can report a non-Success status on
        # the first attempt (container/agent still starting). The check must
        # retry rather than fail the deploy.
        runner = FakeRunner()
        runner.queue("i-1\n")  # in-service instances (fetched once)
        runner.queue("cmd-1\n")  # attempt 1 send
        runner.queue("")  # attempt 1 wait
        runner.queue("Failed\n")  # attempt 1 status -> retry
        runner.queue("cmd-2\n")  # attempt 2 send
        runner.queue("")  # attempt 2 wait
        runner.queue("Success\n")  # attempt 2 status -> ok
        sleep = FakeSleep()

        checked = portal_deploy.verify_asg_image_digest(
            asg_name="dev-portal-asg-abc123",
            image_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            runner=runner,
            sleep=sleep,
        )

        self.assertEqual(checked, ["i-1"])
        self.assertEqual(len(sleep.calls), 1)

    def test_verify_asg_image_digest_fails_after_exhausting_retries(self) -> None:
        runner = FakeRunner()
        runner.queue("i-1\n")
        for _ in range(2):  # max_attempts=2 attempts, each non-Success
            runner.queue("cmd\n")
            runner.queue("")
            runner.queue("Failed\n")
        sleep = FakeSleep()

        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "after 2 attempts"):
            portal_deploy.verify_asg_image_digest(
                asg_name="dev-portal-asg-abc123",
                image_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                runner=runner,
                max_attempts=2,
                sleep=sleep,
            )

        self.assertEqual(len(sleep.calls), 1)  # slept between the 2 attempts only


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class PostDeployVerificationTests(unittest.TestCase):
    def test_parse_post_deploy_outputs_requires_portal_contracts(self) -> None:
        raw = json.dumps(
            {
                "domain_name": {"value": "dev.example.com"},
                "portal_target_group_arn": {"value": "arn:aws:elasticloadbalancing:us-east-2:1:targetgroup/p/abc"},
            }
        )
        parsed = portal_deploy.parse_post_deploy_outputs(raw)
        self.assertEqual(parsed.domain_name, "dev.example.com")
        self.assertEqual(
            parsed.portal_target_group_arn,
            "arn:aws:elasticloadbalancing:us-east-2:1:targetgroup/p/abc",
        )
        self.assertEqual(parsed.guacamole_ecs_cluster_name, "")

    def test_parse_post_deploy_outputs_reads_optional_guacamole_fields(self) -> None:
        raw = json.dumps(
            {
                "domain_name": {"value": "dev.example.com"},
                "portal_target_group_arn": {"value": "arn:portal-tg"},
                "guacamole_target_group_arn": {"value": "arn:guac-tg"},
                "guacamole_ecs_cluster_name": {"value": "dev-portal-guacamole"},
                "guacd_service_name": {"value": "dev-portal-guacd"},
                "guacamole_client_service_name": {"value": "dev-portal-guacamole-client"},
            }
        )
        parsed = portal_deploy.parse_post_deploy_outputs(raw)
        self.assertEqual(parsed.guacamole_target_group_arn, "arn:guac-tg")
        self.assertEqual(parsed.guacamole_ecs_cluster_name, "dev-portal-guacamole")

    def test_wait_target_group_healthy_succeeds_when_all_targets_healthy(self) -> None:
        runner = FakeRunner()
        runner.queue(
            json.dumps(
                {
                    "TargetHealthDescriptions": [
                        {"TargetHealth": {"State": "healthy"}},
                        {"TargetHealth": {"State": "healthy"}},
                    ]
                }
            )
        )
        portal_deploy.wait_target_group_healthy(
            "arn:portal-tg",
            runner=runner,
            sleep_fn=lambda _seconds: None,
            timeout_seconds=30,
            poll_interval_seconds=1,
        )
        self.assertEqual(runner.calls[0][:3], ["aws", "elbv2", "describe-target-health"])

    def test_wait_target_group_healthy_times_out_on_unhealthy_targets(self) -> None:
        runner = FakeRunner()
        runner.queue(
            json.dumps(
                {
                    "TargetHealthDescriptions": [
                        {"TargetHealth": {"State": "unhealthy", "Reason": "Target.FailedHealthChecks"}}
                    ]
                }
            )
        )
        runner.queue(
            json.dumps(
                {
                    "TargetHealthDescriptions": [
                        {"TargetHealth": {"State": "unhealthy", "Reason": "Target.FailedHealthChecks"}}
                    ]
                }
            )
        )
        sleep = FakeSleep()
        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "did not become healthy"):
            portal_deploy.wait_target_group_healthy(
                "arn:portal-tg",
                runner=runner,
                sleep_fn=sleep,
                timeout_seconds=0,
                poll_interval_seconds=0,
            )

    def test_verify_https_endpoint_accepts_expected_status(self) -> None:
        runner = FakeRunner()
        runner.responses = [
            subprocess.CompletedProcess([], 0, stdout="200\n", stderr=""),
        ]
        portal_deploy.verify_https_endpoint(
            "https://dev.example.com/health/",
            expected_status_codes={200},
            runner=runner,
        )
        self.assertIn("https://dev.example.com/health/", runner.calls[0])

    def test_verify_https_endpoint_rejects_unexpected_status(self) -> None:
        runner = FakeRunner()
        runner.responses = [
            subprocess.CompletedProcess([], 0, stdout="503\n", stderr=""),
        ]
        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "503"):
            portal_deploy.verify_https_endpoint(
                "https://dev.example.com/health/",
                expected_status_codes={200},
                runner=runner,
            )

    def test_wait_ecs_services_stable_requires_completed_rollouts(self) -> None:
        runner = FakeRunner()
        runner.queue("COMPLETED\n")
        runner.queue("COMPLETED\n")
        portal_deploy.wait_ecs_services_stable(
            cluster_name="dev-portal-guacamole",
            service_names=["dev-portal-guacd", "dev-portal-guacamole-client"],
            runner=runner,
            sleep_fn=lambda _seconds: None,
            timeout_seconds=30,
            poll_interval_seconds=1,
        )
        self.assertEqual(len(runner.calls), 2)
        for call, service_name in zip(runner.calls, ["dev-portal-guacd", "dev-portal-guacamole-client"], strict=True):
            self.assertEqual(call[:3], ["aws", "ecs", "describe-services"])
            self.assertIn("--cluster", call)
            self.assertIn("dev-portal-guacamole", call)
            self.assertIn(service_name, call)

    def test_verify_post_deploy_fails_when_guacamole_cluster_inactive(self) -> None:
        runner = FakeRunner()
        verification = portal_deploy.PostDeployVerification(
            domain_name="dev.example.com",
            portal_target_group_arn="arn:portal-tg",
            guacamole_target_group_arn="arn:guac-tg",
            guacamole_ecs_cluster_name="dev-portal-guacamole",
            guacd_service_name="dev-portal-guacd",
            guacamole_client_service_name="dev-portal-guacamole-client",
        )
        runner.queue(json.dumps({"TargetHealthDescriptions": [{"TargetHealth": {"State": "healthy"}}]}))
        runner.responses.append(subprocess.CompletedProcess([], 0, stdout="200\n", stderr=""))
        runner.queue("INACTIVE\n")
        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "ACTIVE cluster"):
            portal_deploy.verify_post_deploy(
                verification,
                runner=runner,
                sleep_fn=lambda _seconds: None,
                portal_target_timeout_seconds=30,
                guacamole_target_timeout_seconds=30,
                ecs_timeout_seconds=30,
            )

    def test_portal_manage_script_inherits_entrypoint_env(self) -> None:
        script = portal_deploy._portal_manage_script(
            ["run_post_deploy_smoke", "--variant", "linux"]
        )
        self.assertIn("/proc/1/environ", script)
        self.assertIn("run_post_deploy_smoke", script)
        self.assertIn("docker exec portal", script)

    def test_wait_ssm_command_polls_until_success(self) -> None:
        runner = FakeRunner()
        runner.queue(json.dumps({"Status": "InProgress"}))
        runner.queue(
            json.dumps(
                {
                    "Status": "Success",
                    "StandardOutputContent": "ok",
                    "StandardErrorContent": "",
                }
            )
        )
        payload = portal_deploy._wait_ssm_command(
            command_id="cmd-123",
            instance_id="i-abc",
            timeout_seconds=60,
            runner=runner,
            sleep_fn=lambda _seconds: None,
            poll_interval_seconds=1,
        )
        self.assertEqual(payload["Status"], "Success")
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.calls[0][:3], ["aws", "ssm", "get-command-invocation"])
        self.assertNotIn(
            ["aws", "ssm", "wait", "command-executed"],
            [call[:4] for call in runner.calls],
        )

    def test_wait_ssm_command_times_out_before_terminal_status(self) -> None:
        runner = FakeRunner()
        runner.queue(json.dumps({"Status": "InProgress"}))
        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "did not reach a terminal state"):
            portal_deploy._wait_ssm_command(
                command_id="cmd-123",
                instance_id="i-abc",
                timeout_seconds=0,
                runner=runner,
                sleep_fn=lambda _seconds: None,
                poll_interval_seconds=0,
            )


if __name__ == "__main__":
    unittest.main()


class PortalDeployWorkerHealthTests(unittest.TestCase):
    _DIGEST = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    def test_passes_when_all_workers_healthy(self) -> None:
        runner = FakeRunner()
        runner.queue("i-1\n")  # in-service instances
        runner.queue("cmd\n")  # send-command
        runner.queue("")  # wait
        runner.queue("Success\n")  # status

        checked = portal_deploy.verify_asg_worker_health(
            asg_name="dev-portal-asg-abc123",
            runner=runner,
            sleep=FakeSleep(),
        )

        self.assertEqual(checked, ["i-1"])
        # The check script targets the worker/scheduler containers.
        send = runner.calls[1]
        self.assertIn("send-command", send)
        joined = " ".join(send)
        self.assertIn("worker-outbox-drainer", joined)
        self.assertIn("worker-reconciler", joined)

    def test_retries_transient_non_success(self) -> None:
        runner = FakeRunner()
        runner.queue("i-1\n")
        runner.queue("cmd-1\n")
        runner.queue("")
        runner.queue("Failed\n")  # attempt 1 -> retry (e.g. still starting)
        runner.queue("cmd-2\n")
        runner.queue("")
        runner.queue("Success\n")  # attempt 2 -> ok
        sleep = FakeSleep()

        checked = portal_deploy.verify_asg_worker_health(
            asg_name="dev-portal-asg-abc123",
            runner=runner,
            sleep=sleep,
        )

        self.assertEqual(checked, ["i-1"])
        self.assertEqual(len(sleep.calls), 1)

    def test_fails_after_exhausting_retries_on_crash_loop(self) -> None:
        runner = FakeRunner()
        runner.queue("i-1\n")
        for _ in range(2):
            runner.queue("cmd\n")
            runner.queue("")
            runner.queue("Failed\n")
        sleep = FakeSleep()

        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "after 2 attempts"):
            portal_deploy.verify_asg_worker_health(
                asg_name="dev-portal-asg-abc123",
                runner=runner,
                max_attempts=2,
                sleep=sleep,
            )

        self.assertEqual(len(sleep.calls), 1)

    def test_rejects_empty_asg(self) -> None:
        with self.assertRaisesRegex(portal_deploy.PortalDeployError, "non-empty ASG name"):
            portal_deploy.verify_asg_worker_health(asg_name="", runner=FakeRunner())


class PortalDeploySsmParametersJsonTests(unittest.TestCase):
    """#1413: SSM --parameters must be JSON (preserves \n), not shorthand.

    Shorthand (commands=[...]) does not interpret JSON escapes, so multi-line
    scripts arrived on one line with literal \n and broke (for-loop / case).
    """

    _DIGEST = "sha256:" + "a" * 64

    def _params_of(self, runner):
        send = next(c for c in runner.calls if "send-command" in c)
        return send[send.index("--parameters") + 1]

    def test_verify_asg_image_digest_parameters_are_json_with_newlines(self) -> None:
        runner = FakeRunner()
        runner.queue("i-1\n")
        runner.queue("cmd\n")
        runner.queue("")
        runner.queue("Success\n")
        portal_deploy.verify_asg_image_digest(
            asg_name="dev-portal-asg-abc123", image_digest=self._DIGEST,
            runner=runner, sleep=FakeSleep(),
        )
        parsed = json.loads(self._params_of(runner))  # raises on old shorthand
        self.assertIn("commands", parsed)
        self.assertIn("\n", parsed["commands"][0])

    def test_verify_asg_worker_health_parameters_are_json_with_newlines(self) -> None:
        runner = FakeRunner()
        runner.queue("i-1\n")
        runner.queue("cmd\n")
        runner.queue("")
        runner.queue("Success\n")
        portal_deploy.verify_asg_worker_health(
            asg_name="dev-portal-asg-abc123", runner=runner, sleep=FakeSleep(),
        )
        parsed = json.loads(self._params_of(runner))
        self.assertIn("commands", parsed)
        self.assertIn("\n", parsed["commands"][0])


class PortalDeployManageEnvForwardTests(unittest.TestCase):
    """#1417: run-manage-on-portal must forward extra env into the container."""

    def test_manage_script_renders_docker_exec_e_flags(self) -> None:
        script = portal_deploy._portal_manage_script(
            ["run_post_deploy_smoke", "--variant", "linux"],
            env={"SMOKE_TEST_USER_EMAIL": "smoke@example.com"},
        )
        self.assertIn("docker exec -e SMOKE_TEST_USER_EMAIL=smoke@example.com portal", script)
        self.assertIn("run_post_deploy_smoke", script)

    def test_manage_script_without_env_has_no_e_flag(self) -> None:
        script = portal_deploy._portal_manage_script(["migrate"])
        self.assertIn("sudo docker exec portal bash -c", script)
        self.assertNotIn(" -e ", script)

    def test_run_manage_on_portal_forwards_env_in_ssm_parameters(self) -> None:
        runner = FakeRunner()
        runner.queue("cmd-1\n")  # send-command -> command id
        runner.queue(  # get-command-invocation -> terminal Success
            '{"Status": "Success", "StandardOutputContent": "done", "StandardErrorContent": ""}'
        )
        portal_deploy.run_manage_on_portal(
            instance_id="i-1",
            manage_args=["run_post_deploy_smoke", "--variant", "linux"],
            env={"SMOKE_TEST_USER_EMAIL": "smoke@example.com"},
            runner=runner,
        )
        send = next(c for c in runner.calls if "send-command" in c)
        parsed = json.loads(send[send.index("--parameters") + 1])
        self.assertIn(
            "docker exec -e SMOKE_TEST_USER_EMAIL=smoke@example.com portal",
            parsed["commands"][0],
        )
