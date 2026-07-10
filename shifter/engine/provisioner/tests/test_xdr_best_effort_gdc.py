"""XDR agent install is best-effort on the GDC in-range transport (#615).

GDC range guests sit on an isolated L2 segment with no egress, so the Cortex
agent installer (fetched from GCS) and the agent's phone-home are unreachable.
The XDR install must not fail the provision on the GDC ``range-pod-ssh``
transport (log + continue), while the AWS SSM path stays strict and raises.
"""

import pytest

from instance_setup import _GDC_RANGE_TRANSPORT, _install_xdr_or_raise
from orchestrators.setup_orchestrator import SetupError


class _FakePlan:
    def get_context(self, _cfg):
        return {}


class _FakeResult:
    def __init__(self, success, error=""):
        self.success = success
        self.error = error


class _FakeOrchestrator:
    def __init__(self, result):
        self._result = result

    def orchestrate(self, _target, _plan, _ctx, document_name=None):
        return self._result


class _RaisingOrchestrator:
    """Mirrors the real orchestrator, which raises SetupError on step retry-exhaustion."""

    def __init__(self, error):
        self._error = error

    def orchestrate(self, _target, _plan, _ctx, document_name=None):
        raise SetupError(self._error)


class _FakeExecution:
    def __init__(self, transport_name):
        self.target = "range-1-core-victim"
        self.transport_name = transport_name
        self.document_name = "doc"


def _call(transport_name, *, success, error=""):
    _install_xdr_or_raise(
        _FakeOrchestrator(_FakeResult(success, error)),
        _FakeExecution(transport_name),
        _FakePlan,
        agent_presigned_url="https://example.invalid/agent",
        xdr_required=True,
        failure_prefix="Linux XDR install failed",
        success_log="Linux XDR agent installed on %s",
    )


def _call_raising(transport_name, error):
    _install_xdr_or_raise(
        _RaisingOrchestrator(error),
        _FakeExecution(transport_name),
        _FakePlan,
        agent_presigned_url="https://example.invalid/agent",
        xdr_required=True,
        failure_prefix="Linux XDR install failed",
        success_log="Linux XDR agent installed on %s",
    )


def test_gdc_transport_defers_xdr_failure_without_raising():
    # No exception: the range still provisions end-to-end.
    _call(_GDC_RANGE_TRANSPORT, success=False, error="curl: could not resolve host")


def test_aws_transport_raises_on_xdr_failure():
    with pytest.raises(SetupError, match="Linux XDR install failed"):
        _call("ssm", success=False, error="installer exited non-zero")


def test_gdc_transport_defers_raised_setup_error():
    # The real orchestrator raises SetupError on step retry-exhaustion
    # (e.g. download_xdr_agent exhausts retries). GDC must still defer.
    _call_raising(_GDC_RANGE_TRANSPORT, "Step 'download_xdr_agent' failed after all retry attempts")


def test_aws_transport_propagates_raised_setup_error():
    with pytest.raises(SetupError, match="download_xdr_agent"):
        _call_raising("ssm", "Step 'download_xdr_agent' failed after all retry attempts")


def test_successful_install_never_raises():
    _call(_GDC_RANGE_TRANSPORT, success=True)
    _call("ssm", success=True)
