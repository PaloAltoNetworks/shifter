"""Cloud grant activation refuses missing or broader-than-installed authority."""

from copy import deepcopy

import pytest

from shared.cloud.preparation_cloud_installation import PERMISSIONS, cloud_bindings, role_name, workload_member
from shared.cloud.preparation_cloud_readback import verify_cloud_installation
from tests.shared.cloud.test_preparation_installation import installation_fixture


def cloud_observations(configuration):
    grant = configuration.grant
    network = f"projects/{grant.project_id}/global/networks/" + grant.subnetwork.rsplit("/", 1)[1]
    values = {"project-policy": {"bindings": []}}
    for key, permissions in PERMISSIONS.items():
        values["role:" + key] = {"includedPermissions": permissions, "stage": "GA"}
    for actor, key, condition in cloud_bindings(configuration).values():
        binding = {
            "role": role_name(configuration, key),
            "members": ["serviceAccount:" + configuration.service_accounts[actor]],
        }
        if condition:
            binding["condition"] = condition
        values["project-policy"]["bindings"].append(binding)
    for actor, email in configuration.service_accounts.items():
        values["identity:" + actor] = {"email": email, "disabled": False}
        values["identity-policy:" + actor] = {
            "bindings": [{"role": "roles/iam.workloadIdentityUser", "members": [workload_member(configuration, actor)]}]
        }
    values["subnetwork"] = {
        "network": network,
        "ipCidrRange": configuration.network_cidr,
        "privateIpGoogleAccess": False,
        "stackType": "IPV4_ONLY",
    }
    values["network"] = {"autoCreateSubnetworks": False, "peerings": [], "routingConfig": {"routingMode": "REGIONAL"}}
    values["subnetwork-policy"] = {
        "bindings": [
            {
                "role": role_name(configuration, "subnet_use"),
                "members": [
                    "serviceAccount:" + configuration.service_accounts[actor] for actor in ("builder", "verifier")
                ],
            }
        ]
    }
    values["firewalls"] = {
        "items": [
            {
                "network": network,
                "direction": "INGRESS",
                "priority": 1000,
                "sourceTags": ["shifter-preparation"],
                "targetTags": ["shifter-preparation"],
                "allowed": [{"IPProtocol": "tcp", "ports": ["8080"]}],
            }
        ]
    }
    values["routes"] = {
        "items": [{"network": network, "destRange": configuration.network_cidr, "nextHopNetwork": network}]
    }
    values["routers"] = {"items": []}
    values["cluster"] = {
        "workloadIdentityConfig": {"workloadPool": grant.project_id + ".svc.id.goog"},
        "networkConfig": {"datapathProvider": "ADVANCED_DATAPATH"},
    }
    for key in configuration.controller_secret_ids:
        values["secret-policy:" + key] = {
            "bindings": [
                {
                    "role": "roles/secretmanager.secretAccessor",
                    "members": ["serviceAccount:" + configuration.service_accounts["controller"]],
                }
            ]
        }
    return deepcopy(values)


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "missing-role",
        "broad-role",
        "owner",
        "foreign-wi",
        "subnet",
        "peering",
        "nat",
        "default-route",
        "ingress",
        "secret",
        "network-policy",
    ],
)
def test_activation_requires_current_cloud_iam_and_isolated_network(failure):
    configuration = installation_fixture()
    observed = cloud_observations(configuration)
    if failure == "missing-role":
        observed.pop("role:builder_create")
    elif failure == "broad-role":
        observed["role:builder_create"]["includedPermissions"].append("compute.instances.delete")
    elif failure == "owner":
        observed["project-policy"]["bindings"].append(
            {"role": "roles/owner", "members": ["serviceAccount:" + configuration.service_accounts["builder"]]}
        )
    elif failure == "foreign-wi":
        observed["identity-policy:builder"]["bindings"][0]["members"].append("serviceAccount:foreign")
    elif failure == "subnet":
        observed["subnetwork"]["ipCidrRange"] = "10.0.0.0/8"
    elif failure == "peering":
        observed["network"]["peerings"] = [{"name": "another-network"}]
    elif failure == "nat":
        observed["routers"]["items"] = [{"network": observed["subnetwork"]["network"]}]
    elif failure == "default-route":
        observed["routes"]["items"][0]["destRange"] = "0.0.0.0/0"
    elif failure == "ingress":
        observed["firewalls"]["items"][0]["sourceRanges"] = ["0.0.0.0/0"]
    elif failure == "secret":
        observed["secret-policy:DB_SECRET_ID"]["bindings"][0]["members"].append(
            "serviceAccount:" + configuration.service_accounts["builder"]
        )
    elif failure == "network-policy":
        observed["cluster"]["networkConfig"] = {}
    if failure:
        with pytest.raises(ValueError):
            verify_cloud_installation(configuration, lambda key: observed.get(key))
    else:
        assert verify_cloud_installation(configuration, lambda key: observed.get(key)) == configuration.digest
