"""GitHub Actions runner host-health supervision invariants (issue #292).

A self-hosted runner host froze (SSM connectivity lost, instance hung) and the
outage was only caught by manual investigation. There was no host-level liveness
signal and no CloudWatch alarm on the runner pool.

This adds a host-level systemd-timer monitor that reports the runner systemd
service liveness as a custom CloudWatch metric, plus native EC2 status-check and
CPU alarms, all wired to an SNS topic. The runner-service liveness alarm treats
missing data as breaching so a hung host that can no longer publish its heartbeat
alarms instead of going silent.

These tests pin the structural contract: the monitor watches the
``actions.runner.*`` service (not the portal worker set), emits the
``RunnerServiceActive`` metric to the runner-specific namespace, never carries a
GitHub token or a broad ``cloudwatch:*`` grant, the systemd units run it on a
fixed interval, the single runner deploy path (instance user_data) installs it,
and the Terraform grants the least-privilege metric permission, defines the four
alarms, owns the SNS topic, and gates EC2 auto-recovery to the system status
check behind a variable.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER_ROOT = REPO_ROOT / "platform" / "terraform" / "global" / "github-runner"
RUNNER_MAIN_TF = RUNNER_ROOT / "main.tf"
RUNNER_VARIABLES_TF = RUNNER_ROOT / "variables.tf"
RUNNER_OUTPUTS_TF = RUNNER_ROOT / "outputs.tf"
RUNNER_ALARMS_TF = RUNNER_ROOT / "alarms.tf"
RUNNER_HEALTH_DIR = RUNNER_ROOT / "runner-health"
MONITOR_SCRIPT = RUNNER_HEALTH_DIR / "shifter-runner-health.sh"
MONITOR_SERVICE = RUNNER_HEALTH_DIR / "shifter-runner-health.service"
MONITOR_TIMER = RUNNER_HEALTH_DIR / "shifter-runner-health.timer"

METRIC_NAMESPACE = "Shifter/RunnerHealth"
LIVENESS_METRIC = "RunnerServiceActive"
TIMER_UNIT = "shifter-runner-health.timer"
SERVICE_UNIT = "shifter-runner-health.service"
MONITOR_HOST_PATH = "/usr/local/bin/shifter-runner-health.sh"
ENV_FILE = "/etc/shifter-runner-health.env"


def test_monitor_script_present_with_shebang() -> None:
    assert MONITOR_SCRIPT.is_file()
    assert MONITOR_SCRIPT.read_text(encoding="utf-8").startswith("#!/")


def test_monitor_watches_runner_service_and_emits_liveness_metric() -> None:
    text = MONITOR_SCRIPT.read_text(encoding="utf-8")
    # Liveness is the installed Actions runner systemd service, not the portal
    # worker containers.
    assert "systemctl is-active" in text
    assert "actions.runner." in text
    assert "cloudwatch put-metric-data" in text
    assert METRIC_NAMESPACE in text
    assert LIVENESS_METRIC in text


def test_monitor_has_no_github_token_or_broad_grant() -> None:
    text = MONITOR_SCRIPT.read_text(encoding="utf-8")
    # The host monitor must not poll the GitHub API or carry a token (preflight:
    # no long-lived GitHub credentials on AWS as the first design).
    assert "api.github.com" not in text
    assert "GITHUB_TOKEN" not in text
    assert "RUNNER_TOKEN" not in text


def test_metric_is_scoped_per_runner() -> None:
    # CloudWatch metrics are account/region scoped; each runner stamps a
    # RunnerName dimension from a systemd EnvironmentFile so the per-runner alarm
    # series do not collide.
    monitor = MONITOR_SCRIPT.read_text(encoding="utf-8")
    assert "RUNNER_HEALTH_NAME" in monitor
    assert "RunnerName=" in monitor

    service = MONITOR_SERVICE.read_text(encoding="utf-8")
    assert f"EnvironmentFile=-{ENV_FILE}" in service

    alarms_tf = RUNNER_ALARMS_TF.read_text(encoding="utf-8")
    assert "RunnerName" in alarms_tf


def test_systemd_service_is_oneshot_running_the_monitor() -> None:
    text = MONITOR_SERVICE.read_text(encoding="utf-8")
    assert "Type=oneshot" in text
    assert f"ExecStart={MONITOR_HOST_PATH}" in text


def test_systemd_timer_fires_on_a_fixed_interval() -> None:
    text = MONITOR_TIMER.read_text(encoding="utf-8")
    assert "OnUnitActiveSec=" in text
    assert "Persistent=true" in text
    assert "WantedBy=timers.target" in text


def test_user_data_installs_the_monitor() -> None:
    text = RUNNER_MAIN_TF.read_text(encoding="utf-8")
    assert MONITOR_HOST_PATH in text
    assert f"/etc/systemd/system/{SERVICE_UNIT}" in text
    assert f"/etc/systemd/system/{TIMER_UNIT}" in text
    assert f"systemctl enable --now {TIMER_UNIT}" in text
    # The env file carries the per-runner metric dimension and must be written
    # before the timer is enabled; otherwise the first run emits under an unknown
    # RunnerName.
    assert "RUNNER_HEALTH_NAME=" in text
    assert ENV_FILE in text
    assert text.index("RUNNER_HEALTH_NAME=") < text.index(f"systemctl enable --now {TIMER_UNIT}")


def test_user_data_change_forces_replacement() -> None:
    # user_data only runs on first boot, so the monitor reaches existing runners
    # only if a user_data change replaces the instance. Without this, the
    # breaching service-inactive alarm would page forever on a host that never
    # installs the monitor.
    text = RUNNER_MAIN_TF.read_text(encoding="utf-8")
    assert "user_data_replace_on_change = true" in text


def test_runner_role_grants_putmetricdata_least_privilege() -> None:
    text = RUNNER_MAIN_TF.read_text(encoding="utf-8")
    assert "cloudwatch:PutMetricData" in text
    assert "cloudwatch:namespace" in text
    assert METRIC_NAMESPACE in text
    # Namespace-conditioned, not an unconditioned wildcard grant.
    assert "cloudwatch:*" not in text


def test_alarms_cover_ec2_health_and_runner_liveness() -> None:
    text = RUNNER_ALARMS_TF.read_text(encoding="utf-8")
    assert "aws_cloudwatch_metric_alarm" in text
    assert "StatusCheckFailed_Instance" in text
    assert "StatusCheckFailed_System" in text
    assert "CPUUtilization" in text
    assert LIVENESS_METRIC in text
    assert METRIC_NAMESPACE in text


def _alarm_block(text: str, resource_name: str) -> str:
    """Return the body of a single aws_cloudwatch_metric_alarm resource block."""
    match = re.search(
        r'resource\s+"aws_cloudwatch_metric_alarm"\s+"' + re.escape(resource_name) + r'"\s*\{(.*?)\n\}',
        text,
        re.DOTALL,
    )
    assert match, f"alarm resource {resource_name!r} not found"
    return match.group(1)


def test_liveness_alarm_treats_missing_data_as_breaching() -> None:
    # A hung host cannot publish its heartbeat; missing data must alarm rather
    # than stay silent (the actual #292 incident). Scope the assertion to the
    # runner_service_inactive block so a value-swap onto an EC2 alarm cannot pass
    # this test.
    text = RUNNER_ALARMS_TF.read_text(encoding="utf-8")
    liveness = _alarm_block(text, "runner_service_inactive")
    assert re.search(r'treat_missing_data\s*=\s*"breaching"', liveness)

    # The EC2 platform alarms must NOT be breaching: a stopped/rebooting instance
    # legitimately produces no datapoints, and the liveness alarm already covers
    # the hung-host case.
    for ec2_alarm in (
        "runner_status_check_instance",
        "runner_status_check_system",
        "runner_cpu_high",
    ):
        block = _alarm_block(text, ec2_alarm)
        assert re.search(r'treat_missing_data\s*=\s*"notBreaching"', block)
        assert "breaching" not in re.sub(r'"notBreaching"', "", block)


def test_sns_topic_owned_by_root_and_actions_wired() -> None:
    text = RUNNER_ALARMS_TF.read_text(encoding="utf-8")
    assert "aws_sns_topic" in text
    assert "runner_alerts" in text
    # SNS encryption via the AWS-managed key, matching the engine-provisioner idiom.
    assert "alias/aws/sns" in text
    assert "alarm_actions" in text


def test_system_auto_recovery_is_gated_and_scoped_to_system_check() -> None:
    text = RUNNER_ALARMS_TF.read_text(encoding="utf-8")
    # EC2 recover action is opt-in via a variable and only on the system status
    # check (AWS-hardware faults), never on CPU or service-offline.
    assert "enable_system_auto_recovery" in text
    assert "ec2:recover" in text


def test_health_variables_defined() -> None:
    text = RUNNER_VARIABLES_TF.read_text(encoding="utf-8")
    assert "alarm_email" in text
    assert "enable_system_auto_recovery" in text
    assert "cpu_alarm_threshold" in text


def test_outputs_expose_alerts_topic() -> None:
    assert "runner_alerts_topic_arn" in RUNNER_OUTPUTS_TF.read_text(encoding="utf-8")
