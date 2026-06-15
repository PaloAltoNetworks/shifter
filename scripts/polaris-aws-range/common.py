"""Shared AWS/SSM helpers for the Polaris operator scripts (issue #691).

Before this module existed, ``orchestrate_provisioning.py``,
``cleanup_non_keepers.py``, and ``check_range_health.py`` each rolled their
own boto3 session wiring, portal-instance discovery, SSM ``send_command``
poll loop, Django-shell-via-SSM wrapper, and JSON-envelope parser.

The seam belongs at the AWS transport / target boundary (per the
``polaris-support-decomposition-preflight-691.md`` architecture note):

- ``PolarisAwsContext`` — owns the boto3 session and per-service client
  caching.
- ``find_portal_instance`` — name-tag EC2 lookup of a portal host.
- ``SsmExecutor`` — single-instance and batched SSM ``send_command`` /
  ``get_command_invocation`` poll loop with shared retry rules.
- ``PortalShellTransport`` — operator-side ``manage.py shell`` wrapper that
  ships a Python snippet into the ``portal`` container via SSM and parses
  the ``__JSON_START__``/``__JSON_END__`` envelope the in-container snippet
  writes.
- ``parse_json_envelope`` / ``mask_sensitive_output`` — pure helpers shared
  across scripts that ingest SSM stdout.

Provisioner-owned runtime mutation (Bedrock shard, splice watcher, DNS
override, Kali key) does NOT belong here — it lives in
``shifter/engine/provisioner/plans/polaris_range_bootstrap.py`` and runs via
``SetupOrchestrator`` / ``SSMExecutor``. These helpers are for the operator
fleet scripts that inspect, orchestrate, or remediate already-provisioned
ranges.

``SsmResult`` returns sanitized ``stdout`` / ``stderr`` strings — callers
are expected to feed those through ``mask_sensitive_output`` before
serializing them into status documents or error logs. No CTFd admin tokens,
AWS credentials, participant credentials, static flags, or generated
Bedrock secrets ever land in command argv or in the ``str()`` of an error
raised from here.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import boto3
from botocore.exceptions import ClientError

DEFAULT_REGION = "us-east-2"
PORTAL_INSTANCE_TAG_NAME = "dev-portal-ec2"

DEFAULT_JSON_START = "__JSON_START__"
DEFAULT_JSON_END = "__JSON_END__"

REDACTION = "***REDACTED***"


# -----------------------------------------------------------------------------
# Pure helpers
# -----------------------------------------------------------------------------


def parse_json_envelope(
    stdout: str,
    *,
    start: str = DEFAULT_JSON_START,
    end: str = DEFAULT_JSON_END,
) -> Any:
    """Return the JSON object delimited by ``start`` / ``end`` in ``stdout``.

    Raises ``RuntimeError`` if either marker is missing or the body between
    them isn't parseable JSON. Surrounding whitespace inside the envelope is
    tolerated so callers can write Python that prints with a leading
    newline.
    """
    start_at = stdout.find(start)
    end_at = stdout.find(end)
    if start_at == -1 or end_at == -1:
        raise RuntimeError(
            f"JSON markers missing in stdout (start={start!r}, end={end!r})"
        )
    block = stdout[start_at + len(start) : end_at].strip()
    try:
        return json.loads(block)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"bad JSON in payload: {exc}: {block[:500]}") from exc


def mask_sensitive_output(text: str, secrets: Iterable[str | None]) -> str:
    """Replace every non-empty entry in ``secrets`` with the redaction marker.

    Used before any SSM output is written to status documents, error logs,
    or printed to stdout. Empty / ``None`` secrets are silently skipped — an
    empty needle would match everywhere and a ``None`` is treated as
    "nothing to redact for this slot".
    """
    out = text
    for secret in secrets:
        if not secret:
            continue
        out = out.replace(secret, REDACTION)
    return out


# -----------------------------------------------------------------------------
# AWS context
# -----------------------------------------------------------------------------


class PolarisAwsContext:
    """boto3 session plus cached service clients.

    The session is built lazily so dry-run paths that never touch AWS can
    instantiate a context without credentials. ``profile`` follows the
    boto3 chain when ``None``.

    ``_session`` and ``_session_factory`` are test-only injection seams;
    production callers should leave them at their defaults.
    """

    def __init__(
        self,
        *,
        profile: str | None = None,
        region: str = DEFAULT_REGION,
        _session: Any | None = None,
        _session_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.profile = profile
        self.region = region
        self._cached_session = _session
        self._session_factory = _session_factory or boto3.Session
        self._clients: dict[str, Any] = {}

    def session(self):
        if self._cached_session is None:
            self._cached_session = self._session_factory(
                profile_name=self.profile,
                region_name=self.region,
            )
        return self._cached_session

    def client(self, service: str):
        cached = self._clients.get(service)
        if cached is not None:
            return cached
        cached = self.session().client(service)
        self._clients[service] = cached
        return cached

    def ec2(self):
        return self.client("ec2")

    def ssm(self):
        return self.client("ssm")


# -----------------------------------------------------------------------------
# Portal discovery
# -----------------------------------------------------------------------------


def find_portal_instance(ec2_client, *, name_tag: str = PORTAL_INSTANCE_TAG_NAME) -> str:
    """Return the first running EC2 instance id tagged ``Name=<name_tag>``.

    Existing operator behavior is "any running one" — multiple portal hosts
    are interchangeable for SSM purposes. Raises if no running instance
    matches; callers that want a specific instance should not use this.
    """
    resp = ec2_client.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": [name_tag]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )
    for reservation in resp.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            return instance["InstanceId"]
    raise RuntimeError(f"no running instance tagged Name={name_tag}")


# -----------------------------------------------------------------------------
# SSM execution
# -----------------------------------------------------------------------------


class SsmTimeout(RuntimeError):
    """Raised when an SSM invocation does not reach a terminal state in time."""


SSM_TERMINAL_STATUSES = ("Success", "Failed", "TimedOut", "Cancelled")


@dataclass(frozen=True)
class SsmResult:
    """Sanitized SSM ``get_command_invocation`` outcome.

    Carries only ``command_id``, ``instance_id``, ``status``, and the
    ``stdout`` / ``stderr`` content. Callers that need to expose any of
    these to a status doc should run the strings through
    ``mask_sensitive_output`` first.
    """

    command_id: str
    instance_id: str
    status: str
    stdout: str
    stderr: str


@dataclass
class SsmExecutor:
    """Thin shared wrapper over the SSM ``send_command`` / poll loop.

    Single-instance ``run_bash`` / ``poll_invocation`` and batched
    ``run_bash_batch`` collapse three near-duplicate copies of this loop
    that previously lived in the operator scripts. The defaults match the
    longest-running operator script (5-minute timeout, 3-second poll) so a
    drop-in replacement does not change observable timing.
    """

    ssm_client: Any
    poll_interval_s: float = 3.0
    default_timeout_s: int = 300
    poll_grace_s: int = 30
    invocation_max_concurrency: str = "50"
    invocation_max_errors: str = "100%"

    def run_bash(
        self,
        instance_id: str,
        script: str,
        *,
        timeout_s: int | None = None,
        comment: str | None = None,
    ) -> SsmResult:
        """Run ``script`` on ``instance_id`` and wait for terminal status."""
        timeout = timeout_s if timeout_s is not None else self.default_timeout_s
        params: dict[str, Any] = {
            "InstanceIds": [instance_id],
            "DocumentName": "AWS-RunShellScript",
            "Parameters": {
                "commands": [script],
                "executionTimeout": [str(timeout)],
            },
            "TimeoutSeconds": timeout,
        }
        if comment:
            params["Comment"] = comment
        resp = self.ssm_client.send_command(**params)
        cmd_id = resp["Command"]["CommandId"]
        result = self.poll_invocation(cmd_id, instance_id, timeout_s=timeout)
        if result.status != "Success":
            raise RuntimeError(
                f"SSM command failed ({result.status}):\n"
                f"stdout={result.stdout[-2000:]}\nstderr={result.stderr[-2000:]}"
            )
        return result

    def poll_invocation(
        self,
        command_id: str,
        instance_id: str,
        *,
        timeout_s: int,
    ) -> SsmResult:
        """Poll a single invocation until terminal or timeout."""
        deadline = time.monotonic() + timeout_s + self.poll_grace_s
        while True:
            try:
                inv = self.ssm_client.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=instance_id,
                )
            except ClientError as exc:
                if "InvocationDoesNotExist" in str(exc):
                    if time.monotonic() >= deadline:
                        raise SsmTimeout(
                            f"SSM command {command_id} on {instance_id} did not "
                            f"register before deadline"
                        ) from exc
                    self._sleep()
                    continue
                raise
            if inv.get("Status") in SSM_TERMINAL_STATUSES:
                return SsmResult(
                    command_id=command_id,
                    instance_id=instance_id,
                    status=inv["Status"],
                    stdout=inv.get("StandardOutputContent", "") or "",
                    stderr=inv.get("StandardErrorContent", "") or "",
                )
            if time.monotonic() >= deadline:
                raise SsmTimeout(
                    f"SSM command {command_id} on {instance_id} did not finish "
                    f"within deadline"
                )
            self._sleep()

    def run_bash_batch(
        self,
        instance_ids: list[str],
        script: str,
        *,
        timeout_s: int | None = None,
        comment: str | None = None,
    ) -> dict[str, SsmResult]:
        """Run ``script`` on many instances and wait for all to settle.

        Uses ``list_command_invocations`` for fan-out reads; the per-instance
        ``SsmResult`` carries the plugin output (matches existing
        ``check_range_health.py`` behavior).
        """
        timeout = timeout_s if timeout_s is not None else self.default_timeout_s
        params: dict[str, Any] = {
            "InstanceIds": instance_ids,
            "DocumentName": "AWS-RunShellScript",
            "Parameters": {
                "commands": [script],
                "executionTimeout": [str(timeout)],
            },
            "TimeoutSeconds": timeout,
            "MaxConcurrency": self.invocation_max_concurrency,
            "MaxErrors": self.invocation_max_errors,
        }
        if comment:
            params["Comment"] = comment
        resp = self.ssm_client.send_command(**params)
        cmd_id = resp["Command"]["CommandId"]

        terminal = set(SSM_TERMINAL_STATUSES)
        deadline = time.monotonic() + timeout + self.poll_grace_s
        requested = set(instance_ids)
        results: dict[str, SsmResult] = {}
        while True:
            results = {}
            paginator = self.ssm_client.get_paginator("list_command_invocations")
            for page in paginator.paginate(CommandId=cmd_id, Details=True, MaxResults=50):
                for inv in page.get("CommandInvocations", []):
                    plugin_out = ""
                    plugin_err = ""
                    for plugin in inv.get("CommandPlugins") or []:
                        plugin_out = plugin.get("Output", "") or plugin_out
                        plugin_err = plugin.get("StandardErrorContent", "") or plugin_err
                    results[inv["InstanceId"]] = SsmResult(
                        command_id=cmd_id,
                        instance_id=inv["InstanceId"],
                        status=inv["Status"],
                        stdout=plugin_out,
                        stderr=plugin_err,
                    )
            missing = requested - set(results)
            pending = [iid for iid, r in results.items() if r.status not in terminal]
            if not missing and not pending:
                return results
            if time.monotonic() >= deadline:
                raise SsmTimeout(
                    f"SSM batch {cmd_id} did not finish for "
                    f"{len(pending) + len(missing)} instance(s) within deadline"
                )
            self._sleep()

    def _sleep(self) -> None:
        if self.poll_interval_s > 0:
            time.sleep(self.poll_interval_s)


# -----------------------------------------------------------------------------
# Django-shell-over-SSM transport
# -----------------------------------------------------------------------------


_PORTAL_SHELL_WRAPPER = r"""
set -euo pipefail
echo "$PY_B64" | base64 -d > /tmp/{tmp_name}.py
sudo docker cp /tmp/{tmp_name}.py portal:/tmp/{tmp_name}.py
sudo docker exec portal bash -c '
  set -euo pipefail
  while IFS= read -r -d "" kv; do export "$kv"; done < /proc/1/environ
  cd /app
  python manage.py shell < /tmp/{tmp_name}.py
'
sudo docker exec portal rm -f /tmp/{tmp_name}.py || true
rm -f /tmp/{tmp_name}.py || true
"""

_TMP_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


@dataclass
class PortalShellTransport:
    """Run a Python snippet inside the ``portal`` container via SSM.

    The snippet is base64-encoded and piped into ``python manage.py shell``
    so command bodies never appear in process argv on the host. The snippet
    is expected to emit a JSON envelope between the standard markers; the
    transport returns the parsed object.

    Callers that need raw stdout (e.g. cleanup_non_keepers' line-oriented
    ``SHELL_EVENT|`` framing) should use ``executor.run_bash`` directly with
    a hand-written wrapper instead.
    """

    executor: SsmExecutor
    portal_instance_id: str
    tmp_name: str = "orch"

    def __post_init__(self) -> None:
        if not _TMP_NAME_RE.fullmatch(self.tmp_name):
            raise ValueError(
                f"tmp_name must match {_TMP_NAME_RE.pattern!r}; got {self.tmp_name!r}"
            )

    def run_django(
        self,
        python_source: str,
        *,
        timeout_s: int = 300,
        comment: str | None = None,
        json_start: str = DEFAULT_JSON_START,
        json_end: str = DEFAULT_JSON_END,
    ) -> Any:
        py_b64 = base64.b64encode(python_source.encode("utf-8")).decode("ascii")
        wrapper = _PORTAL_SHELL_WRAPPER.format(tmp_name=self.tmp_name)
        command = f"export PY_B64='{py_b64}'\n{wrapper}"
        result = self.executor.run_bash(
            self.portal_instance_id,
            command,
            timeout_s=timeout_s,
            comment=comment,
        )
        return parse_json_envelope(result.stdout, start=json_start, end=json_end)

    def run_raw(
        self,
        python_source: str,
        *,
        timeout_s: int = 300,
        comment: str | None = None,
    ) -> SsmResult:
        """Same transport without envelope parsing; returns the raw SsmResult.

        Used by scripts (cleanup_non_keepers) that emit line-oriented event
        records instead of a single JSON object.
        """
        py_b64 = base64.b64encode(python_source.encode("utf-8")).decode("ascii")
        wrapper = _PORTAL_SHELL_WRAPPER.format(tmp_name=self.tmp_name)
        command = f"export PY_B64='{py_b64}'\n{wrapper}"
        return self.executor.run_bash(
            self.portal_instance_id,
            command,
            timeout_s=timeout_s,
            comment=comment,
        )


# Re-exports for cross-script type hints.
__all__ = [
    "DEFAULT_JSON_END",
    "DEFAULT_JSON_START",
    "DEFAULT_REGION",
    "PORTAL_INSTANCE_TAG_NAME",
    "PolarisAwsContext",
    "PortalShellTransport",
    "REDACTION",
    "SSM_TERMINAL_STATUSES",
    "SsmExecutor",
    "SsmResult",
    "SsmTimeout",
    "find_portal_instance",
    "mask_sensitive_output",
    "parse_json_envelope",
]
