"""Portal launch lifecycle completion invariants (issue #1032).

Warm-pool / early-boot portal instances finished bootstrap but never completed
the ASG launch lifecycle hook, so they sat in ``Pending:Wait`` until the hook's
``heartbeat_timeout`` elapsed and the ASG ABANDONed them, breaking
instance-refresh convergence and failing the platform Deploy step.

Root cause: ``user_data.sh`` resolved the ASG name once, early in boot, via
``describe-auto-scaling-instances`` (empty for warm-pool launches), then
silently skipped ``complete-lifecycle-action`` when the name was empty AND
swallowed any API failure as a warning while still printing bootstrap success.

These tests pin the fixed contract: the ASG name is resolved at completion time
with bounded retry from the IMDS instance tag (primary) and the Auto Scaling API
(fallback); a configured launch hook that cannot be completed fails bootstrap
loudly instead of printing success; and the invariants the fix relies on
(launch-hook ``ABANDON`` default, IMDSv2 + instance metadata tags,
least-privilege lifecycle IAM) stay in place.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
EC2_MODULE = REPO_ROOT / "platform" / "terraform" / "modules" / "portal" / "ec2"
USER_DATA = EC2_MODULE / "user_data.sh"
MAIN_TF = EC2_MODULE / "main.tf"

SUCCESS_BANNER = "Shifter Platform bootstrap complete!"
IMDS_ASG_TAG_PATH = "meta-data/tags/instance/aws:autoscaling:groupName"


def _user_data() -> str:
    return USER_DATA.read_text(encoding="utf-8")


def _main_tf_compact() -> str:
    return MAIN_TF.read_text(encoding="utf-8").replace(" ", "")


def _function_body(text: str, name: str) -> str:
    """Return the body of a top-level bash function ``name() { ... }``."""
    start = text.index(f"{name}() {{")
    end = text.index("\n}\n", start)
    return text[start:end]


def _if_block(text: str, header: str) -> str:
    """Return a top-level ``if ...; then ... fi`` block (header line through fi).

    Slices to the block's own closing ``fi`` (column 0) so assertions confirm a
    statement is actually *inside* the conditional, not merely somewhere between
    the header and a later anchor.
    """
    start = text.index(header)
    end = text.index("\nfi\n", start)
    return text[start:end]


def test_resolver_prefers_imds_instance_tag() -> None:
    # The IMDS instance tag reflects ASG membership immediately (including
    # warm-pool launches), where describe-auto-scaling-instances is briefly
    # empty. It must be the primary discovery source.
    text = _user_data()
    assert "resolve_asg_name" in text
    resolver = _function_body(text, "resolve_asg_name")
    assert IMDS_ASG_TAG_PATH in resolver


def test_resolver_falls_back_to_describe_api() -> None:
    resolver = _function_body(_user_data(), "resolve_asg_name")
    assert "describe-auto-scaling-instances" in resolver


def test_asg_discovery_is_retried() -> None:
    # A single early lookup is exactly what left warm-pool instances stuck;
    # discovery must retry (bounded) at completion time.
    text = _user_data()
    assert "ASG_DISCOVERY_ATTEMPTS" in text
    resolver = _function_body(text, "resolve_asg_name")
    assert ("while" in resolver) or ("for" in resolver)
    assert "sleep" in resolver


def test_imds_discovery_uses_imdsv2_and_is_bounded() -> None:
    # No IMDSv1 fallback; bounded curl so a hung IMDS cannot stall bootstrap.
    resolver = _function_body(_user_data(), "resolve_asg_name")
    assert "X-aws-ec2-metadata-token" in resolver
    assert "--max-time" in resolver


def test_lifecycle_completion_failure_is_not_swallowed() -> None:
    # The pre-fix silent warning let bootstrap "succeed" without completing the
    # hook. It must be gone so the AWS CLI exit code propagates.
    assert "Warning: Failed to complete lifecycle action" not in _user_data()


def test_continue_completion_is_fail_loud_before_success_banner() -> None:
    text = _user_data()
    # A configured launch hook that cannot be completed must fail bootstrap.
    assert "if ! complete_lifecycle_action CONTINUE" in text
    # The success banner is only reached after the CONTINUE guard block.
    assert text.index("if ! complete_lifecycle_action CONTINUE") < text.index(SUCCESS_BANNER)
    # exit 1 must live INSIDE the guard block (not merely before the banner), so
    # a mutant that moves fi up to run exit/ABANDON unconditionally is caught.
    block = _if_block(text, "if ! complete_lifecycle_action CONTINUE")
    assert "exit 1" in block


def test_continue_failure_abandons_immediately() -> None:
    # A resolved ASG but failed CONTINUE must ABANDON immediately rather than
    # leaving the instance in Pending:Wait until the launch hook times out --
    # that slow-failure mode is exactly what this change eliminates. The ABANDON
    # must be inside the failure guard block, not unconditional.
    block = _if_block(_user_data(), "if ! complete_lifecycle_action CONTINUE")
    assert "complete_lifecycle_action ABANDON" in block


def test_error_trap_disarms_before_best_effort_abandon() -> None:
    # The ERR handler must disarm the trap BEFORE its best-effort ABANDON, inside
    # on_error, so a failing abandon cannot re-enter the handler. Ordering and
    # confinement to on_error both matter (ABANDON also appears at other sites).
    text = _user_data()
    assert "trap on_error ERR" in text
    body = _function_body(text, "on_error")
    assert body.index("trap - ERR") < body.index("complete_lifecycle_action ABANDON")


def test_imdsv2_and_instance_metadata_tags_enabled() -> None:
    compact = _main_tf_compact()
    assert 'http_tokens="required"' in compact
    assert 'instance_metadata_tags="enabled"' in compact


def test_launch_hook_defaults_to_abandon() -> None:
    compact = _main_tf_compact()
    assert 'lifecycle_transition="autoscaling:EC2_INSTANCE_LAUNCHING"' in compact
    assert 'default_result="ABANDON"' in compact


def test_lifecycle_iam_is_present_and_scoped() -> None:
    text = MAIN_TF.read_text(encoding="utf-8")
    assert "autoscaling:CompleteLifecycleAction" in text
    assert "autoscaling:DescribeAutoScalingInstances" in text
    # CompleteLifecycleAction stays scoped to the ASG, not wildcarded.
    assert "aws_autoscaling_group.this[0].arn" in text
    assert "autoscaling:*" not in text
