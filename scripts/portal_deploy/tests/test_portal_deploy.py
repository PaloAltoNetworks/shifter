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


if __name__ == "__main__":
    unittest.main()
