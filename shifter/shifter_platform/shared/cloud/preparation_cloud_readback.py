"""Operator-only readback of the preparation installation's cloud resources.

No credentials or Secret payloads are read by these APIs. Project and named
resource policy checks cover this installation; organization administrators
retain their existing authority over the tenant and its inherited IAM policies.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any, cast

from shared.cloud.preparation_cloud_installation import PERMISSIONS, cloud_bindings, role_name, workload_member
from shared.cloud.preparation_installation import PreparationInstallation

_GET_IAM_POLICY = ":getIamPolicy"
_IDENTITY_POLICY_PREFIX = "identity-policy:"
_SERVICE_ACCOUNT_MEMBER_PREFIX = "serviceAccount:"


class CloudInstallationReader:
    """Bounded reads at fixed Google API origins under the installing operator."""

    def __init__(self, configuration: PreparationInstallation) -> None:
        from shared.cloud.gcp.base import import_google_module

        auth = import_google_module("google.auth")
        transport = import_google_module("google.auth.transport.requests")
        credentials, _ = auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.session = transport.AuthorizedSession(credentials)
        self.configuration = configuration

    def __call__(self, key: str) -> dict[str, Any]:
        method, url, body, params = self._request_spec(key)
        result = self._request(method, url, body, params)
        if key not in {"firewalls", "routes", "routers"}:
            return result
        items = list(result.get("items", []))
        seen: set[str] = set()
        while result.get("nextPageToken"):
            token = result["nextPageToken"]
            if not isinstance(token, str) or len(token) > 2048 or token in seen or len(seen) >= 16:
                raise ValueError("invalid preparation installation pagination")
            seen.add(token)
            result = self._request(method, url, body, dict(params, pageToken=token))
            items.extend(result.get("items", []))
            if len(items) > 2048:
                raise ValueError("preparation installation resources exceed the readback bound")
        return {"items": items}

    def _request(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        response = self.session.request(
            method, url, json=body, params=params, timeout=30, allow_redirects=False, stream=True
        )
        try:
            if response.status_code != 200:
                raise ValueError("preparation cloud installation readback failed")
            data = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                data.extend(chunk)
                if len(data) > 2 * 1024**2:
                    raise ValueError("preparation installation readback exceeds its bound")
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("invalid preparation cloud installation observation")
            return value
        finally:
            response.close()

    def _request_spec(self, key: str) -> tuple[str, str, dict[str, Any] | None, dict[str, Any]]:
        configuration = self.configuration
        grant = configuration.grant
        project = f"projects/{grant.project_id}"
        region = grant.zone.rsplit("-", 1)[0]
        network = project + "/global/networks/" + grant.subnetwork.rsplit("/", 1)[1]
        compute = "https://compute.googleapis.com/compute/v1/"
        iam = "https://iam.googleapis.com/v1/"
        spec = _project_request_spec(key, project)
        if spec is None:
            spec = _iam_request_spec(configuration, key, iam, project)
        if spec is None:
            spec = _secret_or_cluster_request_spec(configuration, key, project)
        if spec is None:
            spec = _compute_request_spec(key, compute, project, network, grant.subnetwork, region)
        return spec


def _project_request_spec(key: str, project: str) -> tuple[str, str, dict[str, Any] | None, dict[str, Any]] | None:
    """Return the project policy read when requested."""
    if key != "project-policy":
        return None
    url = "https://cloudresourcemanager.googleapis.com/v1/" + project + _GET_IAM_POLICY
    return "POST", url, {"options": {"requestedPolicyVersion": 3}}, {}


def _iam_request_spec(
    configuration: PreparationInstallation, key: str, iam: str, project: str
) -> tuple[str, str, dict[str, Any] | None, dict[str, Any]] | None:
    """Handle iam request spec."""
    spec: tuple[str, str, dict[str, Any] | None, dict[str, Any]] | None = None
    if key.startswith("role:"):
        spec = ("GET", iam + role_name(configuration, key.split(":", 1)[1]), None, {})
    elif key.startswith(("identity:", _IDENTITY_POLICY_PREFIX)):
        accounts = cast(Mapping[str, str], configuration.service_accounts)
        url = iam + project + "/serviceAccounts/" + accounts[key.split(":", 1)[1]]
        if key.startswith(_IDENTITY_POLICY_PREFIX):
            spec = ("POST", url + _GET_IAM_POLICY, {"options": {"requestedPolicyVersion": 3}}, {})
        else:
            spec = ("GET", url, None, {})
    return spec


def _secret_or_cluster_request_spec(
    configuration: PreparationInstallation, key: str, project: str
) -> tuple[str, str, dict[str, Any] | None, dict[str, Any]] | None:
    """Return Secret Manager or GKE installation readback requests."""
    if key.startswith("secret-policy:"):
        secret = configuration.controller_secret_ids[key.split(":", 1)[1]]
        url = "https://secretmanager.googleapis.com/v1/" + project + "/secrets/" + secret + _GET_IAM_POLICY
        return "GET", url, None, {"options.requestedPolicyVersion": 3}
    if key == "cluster":
        url = (
            "https://container.googleapis.com/v1/"
            + project
            + "/locations/"
            + configuration.cluster_location
            + "/clusters/"
            + configuration.cluster_name
        )
        return "GET", url, None, {}
    return None


def _compute_request_spec(
    key: str, compute: str, project: str, network: str, subnetwork: str, region: str
) -> tuple[str, str, dict[str, Any] | None, dict[str, Any]]:
    """Handle compute request spec."""
    if key in {"network", "subnetwork", "subnetwork-policy"}:
        url = compute + (network if key == "network" else subnetwork)
        params: dict[str, Any] = {}
        if key == "subnetwork-policy":
            url += "/getIamPolicy"
            params = {"optionsRequestedPolicyVersion": 3}
        return "GET", url, None, params
    if key in {"firewalls", "routes", "routers"}:
        scope = f"regions/{region}" if key == "routers" else "global"
        url = compute + project + "/" + scope + "/" + key
        params = {"maxResults": 100, "filter": f'network = "https://www.googleapis.com/compute/v1/{network}"'}
        return "GET", url, None, params
    raise ValueError("unknown preparation installation observation")


def verify_cloud_installation(
    configuration: PreparationInstallation,
    read: Callable[[str], dict[str, Any] | None] | None = None,
) -> str:
    """Require installed IAM, Workload Identity and isolated preparation networking."""
    reader = read or CloudInstallationReader(configuration)
    _verify_roles(reader)
    _verify_identities(configuration, reader)
    _verify_network(configuration, reader)
    _verify_cluster(configuration, reader("cluster") or {})
    return configuration.digest


def _verify_roles(read: Callable[[str], dict[str, Any] | None]) -> None:
    """Handle verify roles."""
    for key, permissions in PERMISSIONS.items():
        observed = read("role:" + key) or {}
        if (
            set(observed.get("includedPermissions", [])) != set(permissions)
            or observed.get("deleted")
            or observed.get("stage") != "GA"
        ):
            raise ValueError("preparation cloud role does not match the installed authority")


def _verify_cluster(configuration: PreparationInstallation, cluster: Mapping[str, Any]) -> None:
    """Handle verify cluster."""
    workload_pool = cluster.get("workloadIdentityConfig", {}).get("workloadPool")
    network_policy = cluster.get("networkConfig", {}).get("datapathProvider") == "ADVANCED_DATAPATH"
    network_policy = network_policy or cluster.get("networkPolicy", {}).get("enabled") is True
    if workload_pool != configuration.grant.project_id + ".svc.id.goog" or not network_policy:
        raise ValueError("preparation cluster requires Workload Identity and enforced NetworkPolicy")


def _policy_for(policy: object, members: set[str]) -> list[tuple[str, str, str]]:
    """Handle policy for."""
    if not isinstance(policy, dict):
        raise ValueError("preparation IAM policy is unavailable")
    return sorted(
        (member, binding["role"], json.dumps(binding.get("condition"), sort_keys=True))
        for binding in policy.get("bindings", [])
        for member in binding.get("members", [])
        if member in members
    )


def _verify_identities(
    configuration: PreparationInstallation,
    read: Callable[[str], dict[str, Any] | None],
) -> None:
    """Handle verify identities."""
    accounts = cast(Mapping[str, str], configuration.service_accounts)
    members = {_SERVICE_ACCOUNT_MEMBER_PREFIX + email for email in accounts.values()}
    expected: list[tuple[str, str, str]] = []
    for actor, key, condition in cloud_bindings(configuration).values():
        expected.append(
            (
                _SERVICE_ACCOUNT_MEMBER_PREFIX + accounts[actor],
                role_name(configuration, key),
                json.dumps(condition, sort_keys=True),
            )
        )
    if _policy_for(read("project-policy"), members) != sorted(expected):
        raise ValueError("preparation project IAM differs from the installed role and condition bindings")
    for actor, email in configuration.service_accounts.items():
        _verify_identity(configuration, read, actor, email)
    expected_secret = [
        (
            _SERVICE_ACCOUNT_MEMBER_PREFIX + accounts["controller"],
            "roles/secretmanager.secretAccessor",
            "null",
        )
    ]
    for key in configuration.controller_secret_ids:
        if _policy_for(read("secret-policy:" + key), members) != expected_secret:
            raise ValueError("preparation runtime secret access does not match its named controller grant")
    expected_subnet = sorted(
        (
            _SERVICE_ACCOUNT_MEMBER_PREFIX + accounts[actor],
            role_name(configuration, "subnet_use"),
            "null",
        )
        for actor in ("builder", "verifier")
    )
    if _policy_for(read("subnetwork-policy"), members) != expected_subnet:
        raise ValueError("preparation subnet use does not match its worker grants")


def _verify_identity(
    configuration: PreparationInstallation,
    read: Callable[[str], dict[str, Any] | None],
    actor: str,
    email: str,
) -> None:
    """Handle verify identity."""
    observed = read("identity:" + actor) or {}
    policy = read("identity-policy:" + actor) or {}
    expected = [{"role": "roles/iam.workloadIdentityUser", "members": [workload_member(configuration, actor)]}]
    if observed.get("email") != email or observed.get("disabled") or policy.get("bindings") != expected:
        raise ValueError("preparation identity or its Workload Identity binding does not match")


def _relative(reference: object) -> str:
    """Handle relative."""
    return (
        str(reference)
        .removeprefix("https://www.googleapis.com/compute/v1/")
        .removeprefix("https://compute.googleapis.com/compute/v1/")
    )


def _verify_network(
    configuration: PreparationInstallation,
    read: Callable[[str], dict[str, Any] | None],
) -> None:
    """Handle verify network."""
    grant = configuration.grant
    reference = f"projects/{grant.project_id}/global/networks/" + grant.subnetwork.rsplit("/", 1)[1]
    network, subnet = read("network") or {}, read("subnetwork") or {}
    invalid = (
        network.get("autoCreateSubnetworks") is not False,
        bool(network.get("peerings")),
        network.get("routingConfig", {}).get("routingMode") != "REGIONAL",
        _relative(subnet.get("network")) != reference,
        subnet.get("ipCidrRange") != configuration.network_cidr,
        bool(subnet.get("privateIpGoogleAccess")),
        subnet.get("stackType", "IPV4_ONLY") != "IPV4_ONLY",
        bool(subnet.get("secondaryIpRanges")),
    )
    if any(invalid):
        raise ValueError("preparation network is not the configured isolated subnet")
    for kind in ("routes", "routers", "firewalls"):
        _verify_network_resources(configuration, read, kind, reference)


def _verify_network_resources(
    configuration: PreparationInstallation,
    read: Callable[[str], dict[str, Any] | None],
    kind: str,
    reference: str,
) -> None:
    """Handle verify network resources."""
    observation = read(kind)
    if not isinstance(observation, dict):
        raise ValueError("preparation network observation is unavailable")
    items = [item for item in observation.get("items", []) if _relative(item.get("network")) == reference]
    if kind == "routers":
        _verify_no_routers(items)
    elif kind == "routes":
        _verify_local_route(items, configuration.network_cidr, reference)
    else:
        _verify_probe_firewall(items)


def _verify_no_routers(items: list[Mapping[str, Any]]) -> None:
    """Reject every router or NAT attached to the preparation network."""
    if items:
        raise ValueError("preparation network must not have routers or NAT")


def _verify_local_route(items: list[Mapping[str, Any]], network_cidr: str, reference: str) -> None:
    """Require exactly the provider-created local subnet route."""
    if len(items) != 1:
        raise ValueError("preparation network must have only its local subnet route")
    invalid = (
        items[0].get("destRange") != network_cidr,
        _relative(items[0].get("nextHopNetwork")) != reference,
    )
    if any(invalid):
        raise ValueError("preparation network must have only its local subnet route")


def _verify_probe_firewall(items: list[Mapping[str, Any]]) -> None:
    """Require exactly the contained boot-probe firewall."""
    if len(items) != 1 or not _probe_firewall(items[0]):
        raise ValueError("preparation network must have only its contained boot-probe firewall")


def _probe_firewall(item: Mapping[str, Any]) -> bool:
    """Handle probe firewall."""
    return (
        item.get("direction") == "INGRESS"
        and item.get("priority") == 1000
        and not item.get("disabled")
        and item.get("sourceTags") == ["shifter-preparation"]
        and item.get("targetTags") == ["shifter-preparation"]
        and item.get("allowed") == [{"IPProtocol": "tcp", "ports": ["8080"]}]
        and not any(
            item.get(key)
            for key in ("sourceRanges", "destinationRanges", "sourceServiceAccounts", "targetServiceAccounts", "denied")
        )
    )
