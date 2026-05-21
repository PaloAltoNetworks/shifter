"""Set local guest desktop / RDP password (#762).

Per-instance random password is generated at Terraform/Pulumi apply
time and stored in the cloud's secret manager (AWS Secrets Manager via
``aws_secretsmanager_secret.guest_password``, or GCP Secret Manager via
``_ensure_rdp_password_secret``). This plan pushes the value onto the
guest after the bootstrap plan has finished and the per-instance SSH
key is in ``authorized_keys`` / ``administrators_authorized_keys``.

Why this lives in a setup plan instead of in user_data
------------------------------------------------------

1. The password value never appears in EC2 user_data, IMDS, GDC VM
   Runtime cloud-init manifests, or Terraform state's rendered output.
2. The control plane (engine provisioner ECS task) is the trust anchor:
   it already has Secrets Manager read on per-range secrets via
   `aws_iam_role_policy.ecs_task_secrets_manager`. The guest never
   authenticates to the cloud secret store.
3. The orchestrator masks the password value in stdout/stderr capture
   because the context key contains ``password`` (see
   ``SetupOrchestrator.SENSITIVE_CONTEXT_KEY_PARTS``).
4. On Windows the script uses ``Set-LocalUser`` with
   ``ConvertTo-SecureString``, so the password never appears in
   ``net.exe`` process argv. On Linux ``chpasswd`` reads
   ``user:password`` from stdin, never from argv.

Roles in scope
--------------

This plan applies to non-DC guests (kali, ubuntu, windows-victim). The
DC role's local Administrator account *is* the domain Administrator,
so its password is set by the DC promote workflow using the
deployment-scoped ``DC_DOMAIN_PASSWORD`` value (not this plan).
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import SetupStep

# ---------------------------------------------------------------------------
# Linux script — pipes ``$USER:$PASSWORD`` into ``chpasswd`` via a here-doc
# in the script body. We cannot rely on stdin_input here because
# ``SSMExecutor`` ignores stdin (see ``executors/ssm_executor.py``); SSM Run
# Command's ``commands`` parameter is the only transport. The orchestrator's
# ``SENSITIVE_CONTEXT_KEY_PARTS`` masks ``rdp_password`` values in captured
# stdout/stderr so the password does not appear in our log capture. The
# rendered script body itself is the residual-risk surface (same as
# ``dc_setup.py``/``domain_join.py``); see secrets.md for the mitigation.
# ---------------------------------------------------------------------------
LINUX_SET_PASSWORD_SCRIPT = """#!/bin/bash
set -euo pipefail
# Resolve a privileged ``chpasswd`` invocation. On AWS SSM the agent
# runs commands as root so ``chpasswd`` works directly. On GDC the
# guest SSH executor authenticates as the cloud-init default user
# (``kali`` / ``ubuntu``) which carries the cloud-init default
# passwordless-sudo entitlement; ``sudo -n`` keeps the path identical
# without prompting. The here-doc payload is read by chpasswd; the
# value is never on argv.
if [ "$(id -u)" -eq 0 ]; then
    CHPASSWD_CMD=(chpasswd)
else
    if ! command -v sudo >/dev/null 2>&1; then
        echo "FATAL: chpasswd requires root and sudo is unavailable" >&2
        exit 1
    fi
    CHPASSWD_CMD=(sudo -n chpasswd)
fi
"${CHPASSWD_CMD[@]}" <<'__SHIFTER_RDP_PW__'
{{ rdp_username }}:{{ rdp_password }}
__SHIFTER_RDP_PW__
"""  # noqa: S105  # nosec B105  # NOSONAR shell script template, not a credential

LINUX_VERIFY_SCRIPT = """#!/bin/bash
set -euo pipefail
ssh_user="{{ rdp_username }}"
if ! id "$ssh_user" >/dev/null 2>&1; then
    echo "FATAL: user $ssh_user is absent on host" >&2
    exit 1
fi
# passwd -S needs root (it reads /etc/shadow); resolve the same way the
# set step does.
if [ "$(id -u)" -eq 0 ]; then
    PASSWD_CMD=(passwd -S)
else
    PASSWD_CMD=(sudo -n passwd -S)
fi
status=$("${PASSWD_CMD[@]}" "$ssh_user" 2>/dev/null | awk '{print $2}' || echo "")
case "$status" in
    PS|P)
        echo "Password for $ssh_user is set and unlocked"
        exit 0
        ;;
    *)
        echo "FATAL: password status for $ssh_user is '$status' (expected 'PS')" >&2
        exit 1
        ;;
esac
"""

# ---------------------------------------------------------------------------
# Windows script — uses Set-LocalUser with a SecureString. The password
# is in the script body (server-side, in SSM Run Command document) but
# never appears in process argv on the target Windows host. Set-LocalUser
# accepts SecureString natively so the cleartext is only ever in a
# transient PowerShell variable.
# ---------------------------------------------------------------------------
WINDOWS_SET_PASSWORD_SCRIPT = """
$ErrorActionPreference = "Stop"
$Username = "{{ rdp_username }}"
$Password = "{{ rdp_password }}"

try {
    $secure = ConvertTo-SecureString -String $Password -AsPlainText -Force
} finally {
    $Password = $null
}

try {
    Set-LocalUser -Name $Username -Password $secure -ErrorAction Stop
    Write-Host "Local user $Username password reset via Set-LocalUser"
} catch {
    Write-Host "FATAL: Set-LocalUser failed: $($_.Exception.Message)"
    throw
} finally {
    $secure = $null
}
"""  # noqa: S105  # nosec B105  # NOSONAR powershell script template, not a credential

WINDOWS_VERIFY_SCRIPT = """
$ErrorActionPreference = "Stop"
$Username = "{{ rdp_username }}"
$user = Get-LocalUser -Name $Username -ErrorAction Stop
if ($user.Enabled -ne $true) {
    Write-Host "FATAL: local user $Username is disabled"
    exit 1
}
Write-Host "Local user $Username is enabled"
exit 0
"""


class SetLocalPasswordPlan:
    """Push the per-instance local Administrator / desktop password.

    The plan instance is constructed with the platform — ``linux`` or
    ``windows`` — so the orchestrator picks the right script for the
    target's executor. Context keys (``rdp_username``, ``rdp_password``)
    flow through ``SetupOrchestrator`` masking because the key contains
    ``password``.
    """

    # Render-context keys. get_context() passes its input dict through
    # unchanged, so the keys cannot be inferred from a literal return; this
    # explicit declaration is consumed by the CI plan-script token lint
    # (tests/test_plan_template_tokens.py).
    TEMPLATE_CONTEXT_KEYS: ClassVar[frozenset[str]] = frozenset({"rdp_username", "rdp_password"})

    def __init__(self, *, platform: str) -> None:
        if platform not in ("linux", "windows"):
            raise ValueError(f"Unknown platform for SetLocalPasswordPlan: {platform!r}")
        self._platform = platform

    @property
    def steps(self) -> list[SetupStep]:
        if self._platform == "linux":
            return [
                SetupStep(
                    name="set_local_password_linux",
                    script=LINUX_SET_PASSWORD_SCRIPT,
                    timeout_seconds=60,
                    requires_reboot=False,
                ),
            ]
        return [
            SetupStep(
                name="set_local_password_windows",
                script=WINDOWS_SET_PASSWORD_SCRIPT,
                timeout_seconds=120,
                requires_reboot=False,
            ),
        ]

    @property
    def verify_step(self) -> SetupStep:
        if self._platform == "linux":
            return SetupStep(
                name="verify_local_password_linux",
                script=LINUX_VERIFY_SCRIPT,
                timeout_seconds=30,
                is_verification=True,
            )
        return SetupStep(
            name="verify_local_password_windows",
            script=WINDOWS_VERIFY_SCRIPT,
            timeout_seconds=30,
            is_verification=True,
        )

    def get_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Validate the supplied per-instance context.

        Args:
            context: Dict with ``rdp_username`` and ``rdp_password``.

        Returns:
            The same dict (passes through; this plan adds no template
            variables of its own).

        Raises:
            ValueError: If either ``rdp_username`` or ``rdp_password`` is
                missing or empty.
        """
        username = context.get("rdp_username")
        password = context.get("rdp_password")
        if not username:
            raise ValueError("SetLocalPasswordPlan requires non-empty rdp_username")
        if not password:
            raise ValueError("SetLocalPasswordPlan requires non-empty rdp_password")
        return context
