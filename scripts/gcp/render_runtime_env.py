#!/usr/bin/env python3
"""Render the generated GKE runtime env file from Terraform outputs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _value(outputs: dict[str, object], key: str):
    try:
        return outputs[key]["value"]
    except KeyError as exc:
        raise KeyError(f"Missing Terraform output: {key}") from exc


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _derive_sibling_secret_id(secret_id: str, current_suffix: str, new_suffix: str) -> str:
    marker = f"-{current_suffix}"
    if marker in secret_id:
        return secret_id.rsplit(marker, 1)[0] + f"-{new_suffix}"
    return secret_id


def _csv_env(name: str) -> list[str]:
    return [item.strip().lower() for item in os.environ.get(name, "").split(",") if item.strip()]


def render_env(outputs: dict[str, object], *, secure_portal_mode: bool = False) -> str:
    assets_bucket = _value(outputs, "assets_bucket_name")
    terraform_state_bucket = _value(outputs, "terraform_state_bucket_name")
    topic_id = _value(outputs, "platform_events_topic_id")
    subscriptions = _value(outputs, "platform_event_subscriptions")
    secret_ids = _value(outputs, "runtime_secret_ids")
    database = _value(outputs, "control_plane_database")
    cache = _value(outputs, "control_plane_cache")
    guacamole_database = _value(outputs, "guacamole_database")
    image_roots = _value(outputs, "artifact_registry_image_roots")
    identity_platform_api_key = _value(outputs, "identity_platform_api_key")
    identity_platform_project_id = _value(outputs, "identity_platform_project_id")
    public_ingress_ip = _value(outputs, "public_ingress_ip_address")
    public_hostname = _value(outputs, "public_hostname").strip()
    managed_tls_enabled = bool(_value(outputs, "managed_tls_enabled"))
    range_network_id = _value(outputs, "range_network_id")
    range_network_cidr = _value(outputs, "range_network_cidr")
    range_network_region = _value(outputs, "range_network_region")
    portal_network_cidrs = _value(outputs, "portal_network_cidrs")

    if secure_portal_mode and (not public_hostname or not managed_tls_enabled):
        raise ValueError(
            "secure portal mode requires public_hostname and managed_tls_enabled to be configured"
        )

    use_hostname = secure_portal_mode and public_hostname and managed_tls_enabled
    public_origin_host = public_hostname if use_hostname else public_ingress_ip
    public_scheme = "https" if use_hostname else "http"
    site_url = f"{public_scheme}://{public_origin_host}"
    allowed_hosts = ",".join(_unique([public_hostname, public_ingress_ip, "localhost", "127.0.0.1"]))
    csrf_origins = [site_url]
    if not secure_portal_mode and public_hostname:
        csrf_origins.append(f"http://{public_hostname}")

    bootstrap_staff_emails = ",".join(_csv_env("PLATFORM_BOOTSTRAP_STAFF_EMAILS"))
    bootstrap_superuser_emails = ",".join(_csv_env("PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS"))

    values = {
        "STORAGE_BUCKET_NAME": assets_bucket,
        "AGENT_STORAGE_BUCKET": assets_bucket,
        "TF_STATE_BUCKET": terraform_state_bucket,
        "RANGE_EVENTS_TOPIC_ID": topic_id,
        "QUEUE_CMS_CONSUMER_ID": subscriptions["cms"],
        "QUEUE_CMS_PUBLISHER_ID": topic_id,
        "QUEUE_ENGINE_CONSUMER_ID": subscriptions["engine"],
        "QUEUE_ENGINE_PUBLISHER_ID": topic_id,
        "QUEUE_MC_CONSUMER_ID": subscriptions["mc"],
        "QUEUE_MC_PUBLISHER_ID": topic_id,
        "QUEUE_EXPERIMENTS_CONSUMER_ID": subscriptions["experiments"],
        "QUEUE_EXPERIMENTS_PUBLISHER_ID": topic_id,
        "DB_SECRET_ID": secret_ids["db"],
        "APP_SECRET_ID": secret_ids["app"],
        "GUACAMOLE_SECRET_ID": secret_ids["guacamole-json-auth"],
        "GDC_ACCESS_SECRET_ID": _derive_sibling_secret_id(secret_ids["app"], "app", "gdc-access"),
        "DJANGO_DEBUG": "false" if secure_portal_mode else "true",
        "SESSION_COOKIE_SECURE": "true" if secure_portal_mode else "false",
        "CSRF_COOKIE_SECURE": "true" if secure_portal_mode else "false",
        "DB_HOST": database["private_ip"],
        "DB_PORT": str(database["port"]),
        "REDIS_HOST": cache["host"],
        "REDIS_PORT": str(cache["port"]),
        "DJANGO_ALLOWED_HOSTS": allowed_hosts,
        "DJANGO_CSRF_TRUSTED_ORIGINS": ",".join(_unique(csrf_origins)),
        "SITE_URL": site_url,
        "GUACAMOLE_BASE_URL": "/guacamole",
        "GUACAMOLE_API_BASE_URL": "http://guacamole-client.shifter-platform.svc.cluster.local:8080/guacamole",
        "GUACAMOLE_POSTGRESQL_HOSTNAME": guacamole_database["host"],
        "GUACAMOLE_POSTGRESQL_PORT": str(guacamole_database["port"]),
        "GUACAMOLE_POSTGRESQL_DATABASE": guacamole_database["database_name"],
        "ENGINE_TASK_IMAGE": f"{image_roots['pulumi-provisioner']}:latest",
        "AUTH_PROVIDER": "identity_platform" if secure_portal_mode else "oidc",
        "IDENTITY_PLATFORM_API_KEY": identity_platform_api_key,
        "IDENTITY_PLATFORM_PROJECT_ID": identity_platform_project_id,
        "IDENTITY_ALLOWED_EMAIL_DOMAIN": "paloaltonetworks.com",
        "IDENTITY_PLATFORM_ISSUER": "Shifter",
        "IDENTITY_PLATFORM_TOTP_DISPLAY_NAME": "Shifter Authenticator",
        "RANGE_NETWORK_ID": range_network_id,
        "RANGE_NETWORK_CIDR": range_network_cidr,
        "RANGE_NETWORK_REGION": range_network_region,
        "PORTAL_NETWORK_CIDRS": ",".join(_unique(portal_network_cidrs)),
        "GDC_RANGE_NAMESPACE_PREFIX": "range",
        "GDC_NETWORK_INTERFACE": "vxlan0",
        "GDC_NETWORK_DNS_NAMESERVERS": "8.8.8.8",
        "GDC_STATIC_IP_RESERVATION_COUNT": "4",
        "RANGE_VPC_ID": range_network_id,
        "RANGE_VPC_CIDR": range_network_cidr,
    }

    if bootstrap_staff_emails:
        values["PLATFORM_BOOTSTRAP_STAFF_EMAILS"] = bootstrap_staff_emails
    if bootstrap_superuser_emails:
        values["PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS"] = bootstrap_superuser_emails

    return "".join(f"{key}={value}\n" for key, value in values.items())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terraform-output-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--secure-portal-mode",
        action="store_true",
        help="Render the portal runtime contract for the non-debug OIDC path.",
    )
    args = parser.parse_args()

    outputs = json.loads(args.terraform_output_json.read_text())
    rendered = render_env(outputs, secure_portal_mode=args.secure_portal_mode)
    args.output.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
