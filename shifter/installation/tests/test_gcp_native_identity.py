"""Native projections retain distinct runtime and deployment-owner duties."""

from ipaddress import ip_address, ip_network

import pytest

from installation.gcp_migrations import render_migration_job, render_migration_native_sql_egress
from installation.gcp_native_identity import project_native_helm


def test_native_bootstrap_network_permits_only_its_required_endpoints():
    policy = render_migration_native_sql_egress(
        ["10.60.0.12/32"], provider_api_cidrs=["199.36.153.4/30", "199.36.153.8/30"]
    )["spec"]

    def allowed(address, port):
        return any(
            any(item["port"] == port for item in rule["ports"])
            and any(
                "ipBlock" in peer and ip_address(address) in ip_network(peer["ipBlock"]["cidr"]) for peer in rule["to"]
            )
            for rule in policy["egress"]
        )

    assert allowed("10.60.0.12", 3307) and not allowed("10.60.0.13", 3307)
    assert allowed("199.36.153.8", 443) and not allowed("203.0.113.10", 443)
    assert allowed("169.254.169.254", 80) and allowed("169.254.169.254", 988)
    assert not allowed("169.254.169.254", 443)
    dns = next(rule for rule in policy["egress"] if any(port["port"] == 53 for port in rule["ports"]))
    assert dns["to"] == [
        {
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
        }
    ]
    for addresses, apis in (
        ([], ["199.36.153.8/30"]),
        (["10.60.0.0/24"], ["199.36.153.8/30"]),
        (["10.60.0.12/32"], []),
        (["10.60.0.12/32"], ["0.0.0.0/0"]),
    ):
        with pytest.raises(ValueError):
            render_migration_native_sql_egress(addresses, provider_api_cidrs=apis)


def test_native_owner_job_retains_password_duty_without_an_iam_login():
    image = "example.invalid/platform@sha256:" + "1" * 64
    legacy = render_migration_job(image)["spec"]["template"]["spec"]
    assert "initContainers" not in legacy
    native = render_migration_job(image, instance_connection_name="synthetic-project:us-central1:platform-pg")
    pod = native["spec"]["template"]["spec"]
    assert "--auto-iam-authn" not in pod["initContainers"][0]["args"]
    env = {item["name"]: item for item in pod["containers"][0]["env"]}
    assert env["DB_AUTH_MODE"]["value"] == "password" and env["DB_HOST"]["value"] == "127.0.0.1"
    assert env["DB_SECRET_ID"]["valueFrom"]["configMapKeyRef"]["key"] == "DB_MIGRATION_SECRET_ID"
    assert "DB_PASSWORD" not in env


def test_runtime_projection_rejects_a_login_for_another_workload_identity():
    roles = ("portal", "workers", "ctf-scheduler", "provisioner-launcher", "provisioner")
    users = {role: f"synthetic-{role}@synthetic-project.iam" for role in roles}
    outputs = {
        "identity_platform_project_id": {"value": "synthetic-project"},
        "workload_service_accounts": {"value": {role: user + ".gserviceaccount.com" for role, user in users.items()}},
        "control_plane_database": {"value": {"private_ip": "10.60.0.12"}},
        "native_identity": {
            "value": {
                "enabled": True,
                "database_users": users,
                "instance_connection_name": "synthetic-project:us-central1:platform-pg",
            }
        },
    }
    projection = project_native_helm(outputs)
    assert projection["cloudSqlProxy"]["databaseUsers"]["portal"] == users["portal"]
    assert projection["cloudSqlProxy"]["databaseCidrs"] == ["10.60.0.12/32"]
    outputs["workload_service_accounts"]["value"]["portal"] = "different-user@synthetic-project.iam.gserviceaccount.com"
    with pytest.raises(ValueError, match="attached workload identity"):
        project_native_helm(outputs)
