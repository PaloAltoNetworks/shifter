"""Test the transport-aware guest-setup SSH-ready timeout (GDC vs EC2/SSM)."""

from instance_setup import _setup_ready_timeout


def test_gdc_in_range_transport_gets_larger_budget():
    # GDC bare-metal guests run first-boot cloud-init before SSH is ready.
    assert _setup_ready_timeout("range-pod-ssh") == 600


def test_ssm_and_direct_transports_keep_default():
    assert _setup_ready_timeout("ssm") == 300
    assert _setup_ready_timeout("ssh") == 300
