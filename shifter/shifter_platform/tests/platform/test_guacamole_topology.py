"""Guacamole client topology invariants (issue #928).

Guacamole auth tokens are minted server-side and held in the serving task's
process memory. With more than one ``guacamole-client`` task, a token minted on
one task is invalid when the browser's sticky load-balancer session lands on a
different task, so first-click RDP redirects to the Guacamole login. The fix is
to keep the client (token/web) tier pinned to exactly one task and scale
``guacd`` (the per-connection protocol worker) for capacity instead.

These static invariants keep the single-client posture from silently
regressing: the client must not carry an autoscaling path, Terraform must own
its desired count, and every production deployment surface must declare a single
client task/replica.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
GUACAMOLE_MODULE = REPO_ROOT / "platform" / "terraform" / "modules" / "guacamole"
GUACAMOLE_ECS_TF = GUACAMOLE_MODULE / "ecs.tf"
PROD_PORTAL_TFVARS = REPO_ROOT / "platform" / "terraform" / "environments" / "prod" / "portal" / "terraform.tfvars"
GCP_PROD_VALUES = REPO_ROOT / "platform" / "charts" / "shifter" / "values-gcp-prod.yaml"


def _extract_block(source: str, header: str) -> str:
    """Return the body of the first HCL block whose opening line contains ``header``.

    Brace-matches from the header's opening ``{`` to its closing ``}`` so that a
    nested block (for example ``guacd``'s lifecycle) is not attributed to the
    wrong resource.
    """
    start = source.index(header)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : index]
    raise AssertionError(f"unbalanced braces after {header!r}")


def test_guacamole_client_has_no_autoscaling_resources() -> None:
    """The client tier must not be autoscalable; multiple client tasks reintroduce #928."""
    ecs = GUACAMOLE_ECS_TF.read_text(encoding="utf-8")
    assert 'resource "aws_appautoscaling_target" "guacamole_client"' not in ecs, (
        "guacamole-client must not have an autoscaling target: scaling the client tier "
        "to more than one task reintroduces the token/task affinity bug (#928)"
    )
    assert 'resource "aws_appautoscaling_policy" "guacamole_client_cpu"' not in ecs, (
        "guacamole-client must not have an autoscaling policy (#928)"
    )


def test_guacd_keeps_autoscaling() -> None:
    """guacd is the capacity tier and must remain the horizontal-scale knob."""
    ecs = GUACAMOLE_ECS_TF.read_text(encoding="utf-8")
    assert 'resource "aws_appautoscaling_target" "guacd"' in ecs, (
        "guacd must remain autoscalable as the per-connection capacity tier (#928)"
    )


def test_guacamole_client_service_does_not_ignore_desired_count() -> None:
    """Terraform must own the client desired_count so the single-task posture is enforced."""
    ecs = GUACAMOLE_ECS_TF.read_text(encoding="utf-8")
    client_block = _extract_block(ecs, 'resource "aws_ecs_service" "guacamole_client"')
    assert re.search(r"ignore_changes\s*=", client_block) is None, (
        "guacamole-client must not ignore desired_count changes: with the autoscaler "
        "removed, Terraform owns and enforces the single-task client count (#928)"
    )


def test_guacamole_client_desired_count_is_hard_pinned_in_module() -> None:
    """The module must hard-pin the client count to 1, not read a per-env input.

    Prod AWS deploys render local.auto.tfvars from secrets, so pinning only the
    checked-in tfvars baseline is defeatable: a generated value of 2 would
    reconcile the service back to multiple client tasks. The invariant must live
    at the module boundary as a literal so no input can scale the client tier
    above one task (#928).
    """
    ecs = GUACAMOLE_ECS_TF.read_text(encoding="utf-8")
    client_block = _extract_block(ecs, 'resource "aws_ecs_service" "guacamole_client"')
    assert re.search(r"^\s*desired_count\s*=\s*1\b", client_block, re.MULTILINE) is not None, (
        "guacamole-client service must hard-pin desired_count to the literal 1 (#928)"
    )
    assert re.search(r"^\s*desired_count\s*=\s*var\.", client_block, re.MULTILINE) is None, (
        "guacamole-client desired_count must not be assigned from a var: "
        "a generated/deployed tfvars value could then scale the client tier above one task (#928)"
    )


def test_guacamole_client_desired_count_variable_validates_single_task() -> None:
    """The module input must reject any value other than 1 at plan time (#928)."""
    variables = (GUACAMOLE_MODULE / "variables.tf").read_text(encoding="utf-8")
    client_var = _extract_block(variables, 'variable "guacamole_client_desired_count"')
    assert re.search(r"var\.guacamole_client_desired_count\s*==\s*1", client_var) is not None, (
        "guacamole_client_desired_count must carry a validation pinning it to 1 so a "
        "generated/deployed value other than 1 fails the plan (#928)"
    )


def test_prod_pins_single_guacamole_client_task() -> None:
    """Production must run exactly one guacamole-client task."""
    tfvars = PROD_PORTAL_TFVARS.read_text(encoding="utf-8")
    match = re.search(r"^guacamole_client_desired_count\s*=\s*(\d+)", tfvars, re.MULTILINE)
    assert match is not None, "prod portal tfvars must set guacamole_client_desired_count"
    assert match.group(1) == "1", (
        "prod must pin guacamole_client_desired_count to 1 to keep first-click RDP reliable (#928)"
    )


def test_gcp_prod_pins_single_guacamole_client_replica() -> None:
    """GCP production must run exactly one guacamole-client replica (parity with AWS)."""
    values = yaml.safe_load(GCP_PROD_VALUES.read_text(encoding="utf-8"))
    assert values["guacamoleClient"]["replicas"] == 1, (
        "GCP prod must pin guacamoleClient.replicas to 1 so the token/task affinity fix "
        "applies consistently across providers (#928)"
    )
