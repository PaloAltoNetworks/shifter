"""AWS worker-container health supervision invariants (issue #953).

Docker marks the worker/scheduler containers ``unhealthy`` via their heartbeat
health-cmds, but ``--restart unless-stopped`` only acts on process exit and
nothing watches health or signals CloudWatch. A host-level systemd-timer agent
restarts unhealthy worker containers and emits a CloudWatch metric that alarms.

These tests pin the structural contract: the monitor is scoped to the worker /
scheduler set (never ``portal``), it restarts unhealthy containers and emits the
metric, the systemd units run it on the health interval, BOTH AWS deploy paths
install it (so fresh boot and SSM redeploy never diverge), and the Terraform
grants the least-privilege metric permission plus the alarm.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
EC2_MODULE = REPO_ROOT / "platform" / "terraform" / "modules" / "portal" / "ec2"
AWS_USER_DATA = EC2_MODULE / "user_data.sh"
AWS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "_shifter-platform.yml"
WORKER_HEALTH_DIR = EC2_MODULE / "worker-health"
MONITOR_SCRIPT = WORKER_HEALTH_DIR / "shifter-worker-health.sh"
MONITOR_SERVICE = WORKER_HEALTH_DIR / "shifter-worker-health.service"
MONITOR_TIMER = WORKER_HEALTH_DIR / "shifter-worker-health.timer"
EC2_MAIN_TF = EC2_MODULE / "main.tf"
EC2_VARIABLES_TF = EC2_MODULE / "variables.tf"
DEV_PORTAL_TF = REPO_ROOT / "platform" / "terraform" / "environments" / "dev" / "portal" / "main.tf"
PROD_PORTAL_TF = REPO_ROOT / "platform" / "terraform" / "environments" / "prod" / "portal" / "main.tf"

MONITORED_CONTAINERS = ("worker-cms", "worker-engine", "worker-mc", "ctf-scheduler")
METRIC_NAMESPACE = "Shifter/WorkerHealth"
TIMER_UNIT = "shifter-worker-health.timer"
SERVICE_UNIT = "shifter-worker-health.service"
MONITOR_HOST_PATH = "/usr/local/bin/shifter-worker-health.sh"


def test_monitor_script_present_with_shebang() -> None:
    assert MONITOR_SCRIPT.is_file()
    assert MONITOR_SCRIPT.read_text(encoding="utf-8").startswith("#!/")


def test_monitor_targets_worker_set_and_not_portal() -> None:
    text = MONITOR_SCRIPT.read_text(encoding="utf-8")
    monitored_line = next(line for line in text.splitlines() if line.strip().startswith("MONITORED="))
    for container in MONITORED_CONTAINERS:
        assert container in monitored_line
    # The preflight is explicit: host supervision must not restart the portal.
    assert "portal" not in monitored_line.replace("ctf-scheduler", "")


def test_monitor_restarts_unhealthy_and_emits_metric() -> None:
    text = MONITOR_SCRIPT.read_text(encoding="utf-8")
    assert "{{.State.Health.Status}}" in text
    assert "docker restart" in text
    assert "cloudwatch put-metric-data" in text
    assert METRIC_NAMESPACE in text
    # Aggregate metric the alarm watches.
    assert "UnhealthyWorkers" in text


def test_metric_is_scoped_per_environment() -> None:
    # CloudWatch metrics are account/region scoped, so dev and prod must not
    # share a metric series. The supervisor stamps a NamePrefix dimension from a
    # systemd EnvironmentFile, the unit loads it, and the alarm matches it.
    monitor = MONITOR_SCRIPT.read_text(encoding="utf-8")
    assert "WH_NAME_PREFIX" in monitor
    assert "NamePrefix=" in monitor

    service = MONITOR_SERVICE.read_text(encoding="utf-8")
    assert "EnvironmentFile=-/etc/shifter-worker-health.env" in service

    alarm_tf = EC2_MAIN_TF.read_text(encoding="utf-8")
    assert "NamePrefix = var.name_prefix" in alarm_tf


def test_systemd_service_is_oneshot_running_the_monitor() -> None:
    text = MONITOR_SERVICE.read_text(encoding="utf-8")
    assert "Type=oneshot" in text
    assert f"ExecStart={MONITOR_HOST_PATH}" in text


def test_systemd_timer_fires_on_the_health_interval() -> None:
    text = MONITOR_TIMER.read_text(encoding="utf-8")
    assert "OnUnitActiveSec=30s" in text
    assert "Persistent=true" in text
    assert "WantedBy=timers.target" in text


@pytest.mark.parametrize("path", [AWS_USER_DATA, AWS_WORKFLOW])
def test_both_aws_deploy_paths_install_the_monitor(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert MONITOR_HOST_PATH in text
    assert f"/etc/systemd/system/{SERVICE_UNIT}" in text
    assert f"/etc/systemd/system/{TIMER_UNIT}" in text
    assert f"systemctl enable --now {TIMER_UNIT}" in text
    # Both paths write the per-environment metric dimension.
    assert "WH_NAME_PREFIX=" in text
    assert "/etc/shifter-worker-health.env" in text
    # The env-file write MUST precede enabling the timer. EnvironmentFile=- makes
    # a missing file silent, so if a future edit swapped the order the first
    # supervisor run would read WH_NAME_PREFIX unset and emit metrics under
    # NamePrefix=unknown, silently collapsing dev/prod and defeating alarm scoping.
    assert text.index("WH_NAME_PREFIX=") < text.index(f"systemctl enable --now {TIMER_UNIT}")


def test_ec2_module_grants_putmetricdata_least_privilege() -> None:
    text = EC2_MAIN_TF.read_text(encoding="utf-8")
    assert "cloudwatch:PutMetricData" in text
    # Namespace-conditioned, not an unconditioned cloudwatch:* grant.
    assert "cloudwatch:namespace" in text
    assert "cloudwatch:*" not in text


def test_ec2_module_defines_unhealthy_workers_alarm() -> None:
    text = EC2_MAIN_TF.read_text(encoding="utf-8")
    assert "aws_cloudwatch_metric_alarm" in text
    assert "UnhealthyWorkers" in text
    assert METRIC_NAMESPACE in text
    assert "var.worker_health_alarm_actions" in text


def test_alarm_actions_variable_and_env_wiring() -> None:
    assert "worker_health_alarm_actions" in EC2_VARIABLES_TF.read_text(encoding="utf-8")
    for env_main in (DEV_PORTAL_TF, PROD_PORTAL_TF):
        assert "worker_health_alarm_actions" in env_main.read_text(encoding="utf-8")
