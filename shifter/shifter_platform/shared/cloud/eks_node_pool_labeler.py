"""Trusted labeler for the EKS runtime-plugin node pool (#2526).

Runtime-plugin worker Jobs select ``node-restriction.kubernetes.io/shifter-pool=
runtime-plugin``. NodeRestriction forbids a kubelet from setting labels under
that prefix, which is what makes the label a trustworthy pool identity: a node
cannot place itself into (or out of) the sandbox pool. GKE applies the label
through its control plane; EKS managed node groups apply labels through the
kubelet, so on EKS this controller applies it instead.

A node qualifies only when the EC2 instance behind it is running, its private
DNS name equals the node name the EKS authenticator assigned, and its
``aws:autoscaling:groupName`` tag names the runtime-plugin node group's Auto
Scaling group. Only AWS can set ``aws:``-prefixed tags, and nothing on the node
can change its DNS name or state. A node that positively fails the check loses
the label; a provider error leaves the node unchanged.

Usage: ``python -m shared.cloud.eks_node_pool_labeler`` with
``RUNTIME_PLUGIN_NODE_GROUP_ASG`` and ``AWS_REGION`` in the environment.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Protocol, TypedDict

logger = logging.getLogger(__name__)

POOL_LABEL = "node-restriction.kubernetes.io/shifter-pool"
POOL_VALUE = "runtime-plugin"
ASG_TAG = "aws:autoscaling:groupName"
HEARTBEAT = Path("/tmp/node-pool-labeler-heartbeat")  # noqa: S108 # nosec B108 # NOSONAR(S5443)
_PROVIDER_ID = re.compile(r"^aws:///[a-z0-9-]+/(i-[0-9a-f]{8,17})$")
_ASG_NAME = re.compile(r"[\w+=,.@/:-]{1,255}")
_POLL_SECONDS = 15


class _Tag(TypedDict):
    """One EC2 resource tag."""

    Key: str
    Value: str


class _InstanceState(TypedDict):
    """The lifecycle state of a described instance."""

    Name: str


class _Instance(TypedDict, total=False):
    """The described-instance fields the labeler reads."""

    State: _InstanceState
    PrivateDnsName: str
    Tags: list[_Tag]


class _Reservation(TypedDict):
    """One DescribeInstances reservation."""

    Instances: list[_Instance]


class _DescribeInstances(TypedDict, total=False):
    """The DescribeInstances response fields the labeler reads."""

    Reservations: list[_Reservation]


class Ec2Reader(Protocol):
    """The one EC2 read the labeler needs."""

    def describe_instances(self, **kwargs: list[str]) -> _DescribeInstances: ...


class NodeMetadata(Protocol):
    """The Node metadata the labeler reads."""

    name: str
    labels: dict[str, str] | None


class NodeSpec(Protocol):
    """The Node spec field the labeler reads."""

    provider_id: str | None


class Node(Protocol):
    """The fields of a Kubernetes Node the labeler reads."""

    metadata: NodeMetadata
    spec: NodeSpec


class NodeList(Protocol):
    """A listing of Nodes."""

    items: list[Node]


class NodeApi(Protocol):
    """The Kubernetes Node operations the labeler uses."""

    def list_node(self) -> NodeList: ...

    def patch_node(self, name: str, body: dict[str, object]) -> object: ...


def instance_group(ec2: Ec2Reader, instance_id: str, node_name: str) -> str:
    """The Auto Scaling group of the running instance named ``node_name``, or ``""``.

    Empty when the instance does not exist, is not running, does not match the
    node name, or belongs to no group. Provider errors other than a missing
    instance propagate.
    """
    from botocore.exceptions import ClientError

    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "InvalidInstanceID.NotFound":
            return ""
        raise
    instances = [instance for reservation in response.get("Reservations", []) for instance in reservation["Instances"]]
    if len(instances) != 1:
        return ""
    instance = instances[0]
    running = "State" in instance and instance["State"]["Name"] == "running"
    named = instance.get("PrivateDnsName") == node_name
    groups = [tag["Value"] for tag in instance.get("Tags", []) if tag["Key"] == ASG_TAG]
    return groups[0] if running and named and len(groups) == 1 else ""


def node_qualifies(node: Node, ec2: Ec2Reader, pool_asg: str) -> bool | None:
    """Whether ``node`` belongs to the pool; ``None`` when the provider could not answer."""
    from botocore.exceptions import BotoCoreError, ClientError

    match = _PROVIDER_ID.fullmatch(node.spec.provider_id or "")
    if match is None:
        return False
    try:
        return instance_group(ec2, match.group(1), node.metadata.name) == pool_asg
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "unknown")
        logger.warning("node pool check deferred node=%s error=ClientError code=%s", node.metadata.name, code)
    except BotoCoreError as exc:
        logger.warning("node pool check deferred node=%s error=%s", node.metadata.name, type(exc).__name__)
    return None


def reconcile_node(core: NodeApi, node: Node, ec2: Ec2Reader, pool_asg: str) -> None:
    """Apply or remove the pool label so it matches the node's verified identity."""
    qualifies = node_qualifies(node, ec2, pool_asg)
    if qualifies is None:
        return
    current = (node.metadata.labels or {}).get(POOL_LABEL)
    if qualifies and current != POOL_VALUE:
        core.patch_node(node.metadata.name, {"metadata": {"labels": {POOL_LABEL: POOL_VALUE}}})
        logger.info("node pool label applied node=%s", node.metadata.name)
    elif not qualifies and current is not None:
        core.patch_node(node.metadata.name, {"metadata": {"labels": {POOL_LABEL: None}}})
        logger.warning("node pool label removed from unverified node=%s", node.metadata.name)


def reconcile_all(core: NodeApi, ec2: Ec2Reader, pool_asg: str) -> None:
    """One pass over every node."""
    for node in core.list_node().items:
        reconcile_node(core, node, ec2, pool_asg)


def main() -> int:
    """Run the labeler until the process is stopped; returns 2 on missing configuration."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    pool_asg = os.environ.get("RUNTIME_PLUGIN_NODE_GROUP_ASG", "")
    region = os.environ.get("AWS_REGION", "")
    if not _ASG_NAME.fullmatch(pool_asg) or not region:
        sys.stderr.write("RUNTIME_PLUGIN_NODE_GROUP_ASG and AWS_REGION are required\n")
        return 2
    import boto3

    from shared.cloud.kubernetes._client import load_kubernetes_api

    _batch, core, _client, api_exception = load_kubernetes_api()
    ec2 = boto3.client("ec2", region_name=region)
    while True:
        try:
            reconcile_all(core, ec2, pool_asg)
            HEARTBEAT.touch()
        except api_exception as exc:
            logger.warning("node pool reconcile deferred status=%s", getattr(exc, "status", "unknown"))
        time.sleep(_POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
