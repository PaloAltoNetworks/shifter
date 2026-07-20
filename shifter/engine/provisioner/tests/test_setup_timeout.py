"""Test the transport-aware guest-setup SSH-ready timeout (in-range SSH vs SSM)."""

from instance_setup import _setup_ready_timeout


def test_in_range_ssh_transports_get_larger_budget():
    # GDC bare-metal and GCE range cell guests run a full first-boot cloud-init
    # pass before SSH is ready, so both in-range SSH transports get the larger
    # budget (the heavy Polaris host image does not finish within 300s).
    assert _setup_ready_timeout("range-pod-ssh") == 900
    assert _setup_ready_timeout("ssh") == 900


def test_ssm_transport_keeps_default():
    # SSM (AWS) guests are ready fast and keep the tuned 300s default.
    assert _setup_ready_timeout("ssm") == 300
