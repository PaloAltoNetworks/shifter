"""Trusted EKS runtime-plugin pool labeler (#2526)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from shared.cloud.eks_node_pool_labeler import ASG_TAG, POOL_LABEL, POOL_VALUE, reconcile_all

POOL_ASG = "eks-runtime-plugins-1234-abcd"
NODE = "ip-10-0-1-10.us-east-2.compute.internal"
PLATFORM_NODE = "ip-10-0-1-11.us-east-2.compute.internal"


class FakeEc2:
    def __init__(self, instances: dict[str, dict]) -> None:
        self.instances = instances
        self.error: Exception | None = None

    def describe_instances(self, **kwargs):
        if self.error:
            raise self.error
        instance = self.instances.get(kwargs["InstanceIds"][0])
        if instance is None:
            raise ClientError({"Error": {"Code": "InvalidInstanceID.NotFound"}}, "DescribeInstances")
        return {"Reservations": [{"Instances": [instance]}]}


class FakeCore:
    def __init__(self, nodes: list) -> None:
        self.nodes = nodes
        self.patches: list[tuple[str, dict]] = []

    def list_node(self):
        return SimpleNamespace(items=self.nodes)

    def patch_node(self, name, body):
        self.patches.append((name, body))


def _node(name=NODE, instance="i-0abc12345678def00", labels=None):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, labels=labels or {}),
        spec=SimpleNamespace(provider_id=f"aws:///us-east-2a/{instance}" if instance else None),
    )


def _instance(group=POOL_ASG, dns=NODE, state="running"):
    tags = [{"Key": "Name", "Value": "worker"}]
    if group:
        tags.append({"Key": ASG_TAG, "Value": group})
    return {"State": {"Name": state}, "PrivateDnsName": dns, "Tags": tags}


@pytest.fixture
def ec2():
    return FakeEc2(
        {
            "i-0abc12345678def00": _instance(),
            "i-0abc12345678def01": _instance(group="eks-platform-9876", dns=PLATFORM_NODE),
            "i-0abc12345678def02": _instance(dns="ip-10-0-9-9.us-east-2.compute.internal"),
            "i-0abc12345678def03": _instance(state="stopped"),
            "i-0abc12345678def04": _instance(group=""),
        }
    )


def test_labels_only_nodes_in_the_pool_auto_scaling_group(ec2):
    core = FakeCore([_node(), _node(name=PLATFORM_NODE, instance="i-0abc12345678def01")])

    reconcile_all(core, ec2, POOL_ASG)

    assert core.patches == [(NODE, {"metadata": {"labels": {POOL_LABEL: POOL_VALUE}}})]
    already = FakeCore([_node(labels={POOL_LABEL: POOL_VALUE})])
    reconcile_all(already, ec2, POOL_ASG)
    assert already.patches == []


def test_removes_the_label_from_any_node_that_fails_verification(ec2):
    labeled = {POOL_LABEL: POOL_VALUE}
    nodes = [
        _node(name=PLATFORM_NODE, instance="i-0abc12345678def01", labels=dict(labeled)),  # other group
        _node(name=NODE, instance="i-0abc12345678def02", labels=dict(labeled)),  # DNS name mismatch
        _node(name=NODE, instance="i-0abc12345678def03", labels=dict(labeled)),  # stopped
        _node(name=NODE, instance="i-0abc12345678def04", labels=dict(labeled)),  # no group tag
        _node(name="ip-b", instance="i-0abc12345678def99", labels=dict(labeled)),  # missing instance
        _node(name="ip-c", instance=None, labels=dict(labeled)),  # no provider ID
    ]
    core = FakeCore(nodes)

    reconcile_all(core, ec2, POOL_ASG)

    assert len(core.patches) == len(nodes)
    assert all(body == {"metadata": {"labels": {POOL_LABEL: None}}} for _, body in core.patches)


@pytest.mark.parametrize(
    "error",
    [
        EndpointConnectionError(endpoint_url="https://ec2.us-east-2.amazonaws.com"),
        ClientError({"Error": {"Code": "UnauthorizedOperation"}}, "DescribeInstances"),
    ],
)
def test_provider_errors_leave_nodes_unchanged(ec2, error, caplog):
    ec2.error = error
    core = FakeCore([_node(), _node(name="ip-x", labels={POOL_LABEL: POOL_VALUE})])

    reconcile_all(core, ec2, POOL_ASG)

    assert core.patches == []
    if isinstance(error, ClientError):
        assert "code=UnauthorizedOperation" in caplog.text
