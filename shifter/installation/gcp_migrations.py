"""One canonical GCP migration Job for bootstrap and release deployment."""

from ipaddress import ip_network
from typing import Any

from shared.gcp_native_identity import cloud_sql_proxy_spec

_GCP_PRIVATE_API_CIDRS = frozenset(
    {
        "199.36.153.4/30",  # NOSONAR - Google restricted.googleapis.com VIP.
        "199.36.153.8/30",  # NOSONAR - Google private.googleapis.com VIP.
    }
)
_GKE_METADATA_CIDR = "169.254.169.254/32"  # NOSONAR - GKE Workload Identity metadata server.


def render_migration_native_sql_egress(database_cidrs: list[str], *, provider_api_cidrs: list[str]) -> dict[str, Any]:
    """Bootstrap needs the instance transport before the Helm release exists."""
    if not database_cidrs or any(ip_network(cidr).num_addresses != 1 for cidr in database_cidrs):
        raise ValueError("Native migration transport requires exact database addresses")
    if not provider_api_cidrs or set(provider_api_cidrs) - _GCP_PRIVATE_API_CIDRS:
        raise ValueError("Native migration APIs require the installation's Google private or restricted VIPs")
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "platform-migration-native-sql-egress", "namespace": "shifter-platform"},
        "spec": {
            "podSelector": {"matchLabels": {"app.kubernetes.io/component": "migrator"}},
            "policyTypes": ["Egress"],
            "egress": [
                {
                    "to": [{"ipBlock": {"cidr": cidr}} for cidr in database_cidrs],
                    "ports": [{"protocol": "TCP", "port": 3307}],
                },
                {
                    "to": [{"ipBlock": {"cidr": cidr}} for cidr in provider_api_cidrs],
                    "ports": [{"protocol": "TCP", "port": 443}],
                },
                {
                    "to": [{"ipBlock": {"cidr": _GKE_METADATA_CIDR}}],
                    "ports": [{"protocol": "TCP", "port": 80}, {"protocol": "TCP", "port": 988}],
                },
                {
                    "to": [
                        {
                            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
                            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                        }
                    ],
                    "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}],
                },
            ],
        },
    }


def render_migration_job(
    platform_image: str, *, instance_connection_name: str = "", job_name: str = "platform-migrate"
) -> dict[str, object]:
    """Build the hardened one-off schema migration Job."""
    labels = {"app.kubernetes.io/part-of": "shifter", "app.kubernetes.io/component": "migrator"}
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": "shifter-platform",
            "labels": labels,
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 900,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "serviceAccountName": "migrator",
                    "automountServiceAccountToken": True,
                    "restartPolicy": "Never",
                    "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
                    "containers": [
                        {
                            "name": "migrate",
                            "image": platform_image,
                            "imagePullPolicy": "IfNotPresent",
                            "args": [
                                "/bin/sh",
                                "-c",
                                "python manage.py reconcile_gcp_database_duties"
                                " && python manage.py bootstrap_inbox_catalog"
                                " && python manage.py seed_raes_image_registry"
                                " && python manage.py acquire_feature_artifacts",
                            ],
                            "envFrom": [{"configMapRef": {"name": "platform-runtime"}}],
                            "env": [
                                {
                                    "name": "DB_SECRET_ID",
                                    "valueFrom": {
                                        "configMapKeyRef": {
                                            "name": "platform-runtime",
                                            "key": "DB_MIGRATION_SECRET_ID",
                                        }
                                    },
                                },
                                {"name": "DB_AUTH_MODE", "value": "password"},
                                {"name": "TMPDIR", "value": "/var/run/shifter-migrate"},
                                {"name": "SKIP_MIGRATIONS", "value": ""},
                                {"name": "GUACAMOLE_SECRET_ID", "value": ""},
                                {"name": "DC_DOMAIN_PASSWORD_SECRET_ID", "value": ""},
                                {"name": "REDIS_SECRET_ID", "value": ""},
                                # This Job blanks REDIS_SECRET_ID (above), so entrypoint.sh
                                # never hydrates REDIS_PASSWORD. The runtime ConfigMap still
                                # carries REDIS_HOST/REDIS_TLS=true for the app pods, which
                                # would make Django settings demand the (absent) AUTH token at
                                # import (config/_redis.py resolve_redis_connection, ADR-008-R6).
                                # Migrations touch only the database, so blank REDIS_HOST here
                                # too: with no host, config/_redis.py and config/_channels.py
                                # both select the LocMem cache and in-memory channel layer.
                                {"name": "REDIS_HOST", "value": ""},
                                # This DB-only Job has no mounted model catalog.
                                {"name": "MODEL_ACCESS_ENABLED", "value": "false"},
                                {"name": "MODEL_ACCESS_CATALOG_PATH", "value": ""},
                                {"name": "MODEL_ACCESS_CATALOG_DIGEST", "value": ""},
                                {"name": "EMAIL_API_KEY_SECRET_ID", "value": ""},
                            ],
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                                "readOnlyRootFilesystem": True,
                                "runAsNonRoot": True,
                                # The portal image declares USER as the name appuser (uid 1000);
                                # the kubelet cannot verify a non-numeric user as non-root, so
                                # pair runAsNonRoot with the numeric uid (matches every other
                                # workload and the CI _gcp-dev.yml migrate Job).
                                "runAsUser": 1000,
                            },
                            "volumeMounts": [{"name": "tmp", "mountPath": "/var/run/shifter-migrate"}],
                        }
                    ],
                    "volumes": [{"name": "tmp", "emptyDir": {}}],
                },
            },
        },
    }

    pod = job["spec"]["template"]["spec"]
    if instance_connection_name:
        pod["initContainers"] = [cloud_sql_proxy_spec(instance_connection_name, auto_iam=False)]
        pod["containers"][0]["env"].extend(
            [
                {"name": "DB_HOST", "value": "127.0.0.1"},
                {"name": "DB_PORT", "value": "5432"},
            ]
        )
    return job
