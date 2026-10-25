"""RAES static network-address admission tests (#2219)."""

from __future__ import annotations

import pytest

from tests.shared.raes.test_runtime_target import _interpret, _network, _node, _plan

_CODE = "shifter-provisioner.invalid-static-network-address"


def _addressed_plan(properties, *, count: int = 1):
    node = _node("provision.node.web", "web", count=count, links=("lan",))
    node.payload["spec"]["infrastructure"]["properties"] = properties
    return _plan(node, _network("provision.network.lan", "lan", cidr="10.50.0.0/24"))


def test_valid_static_address_is_admitted_and_serialized_verbatim() -> None:
    serialized, diagnostics = _interpret(_addressed_plan([{"lan": "10.50.0.10"}]))

    assert serialized is not None
    assert not any(item.code == _CODE for item in diagnostics)
    properties = serialized["resources"]["provision.node.web"]["payload"]["spec"]["infrastructure"]["properties"]
    assert properties == [{"lan": "10.50.0.10"}]


@pytest.mark.parametrize(
    "properties,count",
    [
        ({"lan": "10.50.0.10"}, 1),
        ([{"lan": "not-an-ip"}], 1),
        ([{"lan": "10.51.0.10"}], 1),
        ([{"lan": "10.50.0.10"}], 2),
        ([{"ghost": "10.50.0.10"}], 1),
        ([{"lan": "10.50.0.10"}, {"lan": "10.50.0.11"}], 1),
    ],
)
def test_invalid_or_ambiguous_static_address_fails_before_dispatch(properties, count) -> None:
    serialized, diagnostics = _interpret(_addressed_plan(properties, count=count))

    assert serialized is None
    errors = [item for item in diagnostics if item.code == _CODE]
    assert errors
    assert all("10.50" not in item.message and "10.51" not in item.message for item in errors)


def test_duplicate_static_address_across_nodes_is_rejected() -> None:
    first = _node("provision.node.first", "first", links=("lan",))
    second = _node("provision.node.second", "second", links=("lan",))
    for node in (first, second):
        node.payload["spec"]["infrastructure"]["properties"] = [{"lan": "10.50.0.10"}]

    serialized, diagnostics = _interpret(
        _plan(first, second, _network("provision.network.lan", "lan", cidr="10.50.0.0/24"))
    )

    assert serialized is None
    assert any(item.code == _CODE for item in diagnostics)


@pytest.mark.parametrize("address", ["10.50.0.0", "10.50.0.1", "10.50.0.2", "10.50.0.253"])
def test_reserved_static_address_fails_before_dispatch(address: str) -> None:
    serialized, diagnostics = _interpret(_addressed_plan([{"lan": address}]))

    assert serialized is None
    errors = [item for item in diagnostics if item.code == _CODE]
    assert errors
    assert all("reserved or unavailable" in item.message for item in errors)
