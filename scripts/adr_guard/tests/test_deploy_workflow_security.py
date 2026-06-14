import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


def _read_workflow(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def _job_blocks(workflow_name: str) -> dict[str, str]:
    text = _read_workflow(workflow_name)
    lines = text.splitlines()
    jobs_start = next(i for i, line in enumerate(lines) if line == "jobs:")
    jobs: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[jobs_start + 1 :]:
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            current = match.group(1)
            jobs[current] = [line]
            continue
        if current is not None:
            jobs[current].append(line)
    return {name: "\n".join(block) for name, block in jobs.items()}


def _active_lines(text: str) -> list[str]:
    return [
        stripped
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]


def _active_line_contains(text: str, expected: str) -> bool:
    return any(expected in line for line in _active_lines(text))


def _active_text(text: str) -> str:
    return "\n".join(_active_lines(text))


class DeployWorkflowSecurityTests(unittest.TestCase):
    def test_active_line_filter_ignores_commented_security_conditions(self) -> None:
        block = """
        # github.event_name != 'pull_request'
        # environment: ${{ inputs.github_environment }}
        runs-on: self-hosted
        """

        active = _active_lines(block)

        self.assertNotIn("github.event_name != 'pull_request'", active)
        self.assertNotIn("environment: ${{ inputs.github_environment }}", active)

    def test_pull_requests_do_not_route_provider_deploys(self) -> None:
        deploy = _read_workflow("deploy.yml")
        pr_branch = deploy.split(
            'if [ "${{ github.event_name }}" == "pull_request" ]; then', 1
        )[-1].split(
            'elif [ "${{ github.event_name }}" == "workflow_dispatch" ]; then', 1
        )[0]

        self.assertNotIn('RUN_AWS="true"', pr_branch)
        self.assertNotIn('RUN_GCP="true"', pr_branch)

    def test_self_hosted_reusable_jobs_fail_closed_on_pull_request(self) -> None:
        for workflow_name in (
            "_core.yml",
            "_range.yml",
            "_shifter-engine.yml",
            "_shifter-platform.yml",
            "_gcp-dev.yml",
        ):
            with self.subTest(workflow=workflow_name):
                self_hosted_jobs = {
                    name: block
                    for name, block in _job_blocks(workflow_name).items()
                    if "runs-on: self-hosted" in block
                }
                self.assertTrue(self_hosted_jobs)
                for job_name, block in self_hosted_jobs.items():
                    with self.subTest(job=job_name):
                        self.assertTrue(
                            _active_line_contains(
                                block, "github.event_name != 'pull_request'"
                            )
                        )

    def test_mutating_deploy_jobs_bind_github_environment(self) -> None:
        expected_jobs = {
            "_core.yml": ("apply",),
            "_range.yml": ("apply",),
            "_shifter-engine.yml": ("build", "deploy"),
            "_shifter-platform.yml": (
                "push-guacamole-images",
                "apply",
                "build",
                "deploy",
            ),
            "_gcp-dev.yml": ("deploy",),
        }
        for workflow_name, job_names in expected_jobs.items():
            blocks = _job_blocks(workflow_name)
            self.assertIn("github_environment:", _read_workflow(workflow_name))
            for job_name in job_names:
                with self.subTest(workflow=workflow_name, job=job_name):
                    self.assertIn(
                        "environment: ${{ inputs.github_environment }}",
                        _active_lines(blocks[job_name]),
                    )

    def test_engine_terraform_uses_explicit_digest_without_ecr_tag_lookup(self) -> None:
        engine_main = (
            REPO_ROOT / "platform/terraform/modules/engine-provisioner/main.tf"
        ).read_text(encoding="utf-8")
        engine_task = (
            REPO_ROOT / "platform/terraform/modules/engine-provisioner/task_definition.tf"
        ).read_text(encoding="utf-8")
        engine_variables = (
            REPO_ROOT / "platform/terraform/modules/engine-provisioner/variables.tf"
        ).read_text(encoding="utf-8")
        platform_workflow = _active_text(_read_workflow("_shifter-platform.yml"))
        deploy_workflow = _active_text(_read_workflow("deploy.yml"))

        self.assertNotIn('data "aws_ecr_image"', engine_main)
        self.assertIn('variable "container_image_digest"', engine_variables)
        self.assertIn(
            "${var.ecr_repository_url}@${var.container_image_digest}",
            engine_task,
        )
        self.assertIn("engine_image_digest:", platform_workflow)
        self.assertIn('engine_container_image_digest = "%s"', platform_workflow)
        self.assertIn(
            "engine_image_digest: ${{ needs.shifter-engine.outputs.image_digest }}",
            deploy_workflow,
        )


if __name__ == "__main__":
    unittest.main()
