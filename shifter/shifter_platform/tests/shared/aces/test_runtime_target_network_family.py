"""Network address-family admission tests for the ACES RuntimeTarget backend (#1568).

The GCE range-cell substrate is IPv4-only. The backend publishes a
``network-address-family = ipv4-only`` provisioner constraint and rejects a
compiled network whose CIDR is not IPv4 on the shared, pure ``validate()`` /
``apply()`` path -- before any dispatch or engine persistence -- classifying it
as an unsupported *capability* (not malformed SDL) and never echoing the authored
network literal. These behaviors live in their own module so ``test_runtime_target``
stays behavior-scoped; the plan builders are reused from that battery rather than
duplicated.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from aces_contracts.runtime_state import RuntimeSnapshot

from shared.aces.manifest import SHIFTER_PROVISIONER_CAPABILITIES
from shared.aces.runtime_target import ShifterProvisioner
from tests.shared.aces.test_runtime_target import (
    _FORBIDDEN_DIAGNOSTIC_SUBSTRINGS,
    FakeDispatchPort,
    _interpret,
    _network,
    _node,
    _plan,
)

_FAMILY_CODE = "shifter-provisioner.unsupported-network-address-family"


def test_ipv6_network_fails_validate_and_apply_without_dispatch_or_leak() -> None:
    """An IPv6 (non-IPv4) network is a valid-SDL but unsupported-capability plan.

    It must fail both validate() and apply() with the stable family code, never
    dispatch, and never echo the authored network literal in the diagnostic.
    """
    authored_cidr = "2001:db8:dead:beef::/64"
    plan = _plan(
        _node("provision.node.web", "web", links=("lan",)),
        _network("provision.network.lan", "lan", cidr=authored_cidr),
    )

    family_errors = [
        d for d in ShifterProvisioner(FakeDispatchPort()).validate(plan) if d.is_error and d.code == _FAMILY_CODE
    ]
    assert family_errors, "IPv6 network must be rejected at validate()"

    port = FakeDispatchPort()
    result = ShifterProvisioner(port).apply(plan, RuntimeSnapshot())
    assert result.success is False
    assert port.plans == []  # fail closed: no dispatch, no engine persistence
    assert any(d.code == _FAMILY_CODE for d in result.diagnostics)

    # The authored network literal (and any provider/subnet detail) must not leak.
    for diagnostic in family_errors:
        lowered = diagnostic.message.lower()
        assert "2001:db8" not in lowered
        assert "beef" not in lowered
        assert not any(marker in lowered for marker in _FORBIDDEN_DIAGNOSTIC_SUBSTRINGS)


@pytest.mark.parametrize("cidr", ["", "not-a-cidr", "10.0.0.0/33"])
def test_network_family_gate_defers_on_missing_or_unparseable_cidr(cidr: str) -> None:
    """The gate classifies only a parseable CIDR.

    A missing or malformed CIDR is deliberately left to the SDL/transport/plan
    validators, so the gate stays silent -- it must not mislabel malformed input as
    an unsupported address family, nor crash validate()/apply().
    """
    _, diagnostics = _interpret(_plan(_network("provision.network.lan", "lan", cidr=cidr)))
    assert not any(d.code == _FAMILY_CODE for d in diagnostics)


def test_gate_is_inert_when_constraint_not_published() -> None:
    """The gate is disclosure-driven: a backend that does not publish the ipv4-only
    constraint does not reject an IPv6 network here (declaration and enforcement move
    together). This guards against the gate firing on capabilities that never claimed it."""
    capabilities = replace(SHIFTER_PROVISIONER_CAPABILITIES, constraints={})
    plan = _plan(_network("provision.network.lan", "lan", cidr="2001:db8::/64"))
    _, diagnostics = _interpret(plan, capabilities=capabilities)
    assert not any(d.code == _FAMILY_CODE for d in diagnostics)


def test_ipv4_network_is_accepted_and_dispatches() -> None:
    """The IPv4 happy path is unchanged -- a v4 network serializes and dispatches."""
    port = FakeDispatchPort()
    plan = _plan(
        _node("provision.node.web", "web", links=("lan",)),
        _network("provision.network.lan", "lan", cidr="10.20.30.0/24"),
    )
    serialized, diagnostics = _interpret(plan)
    assert serialized is not None
    assert not any(d.code == _FAMILY_CODE for d in diagnostics)
    result = ShifterProvisioner(port).apply(plan, RuntimeSnapshot())
    assert result.success is True
    assert len(port.plans) == 1
