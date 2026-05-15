#!/usr/bin/env python3
"""Render the generated GKE runtime env file from Terraform outputs.

The GCP portal runtime is always rendered in the production security posture
(ADR-008, ADR-008-R1, ADR-008-R3):

* ``DJANGO_DEBUG=false``, ``SESSION_COOKIE_SECURE=true``,
  ``CSRF_COOKIE_SECURE=true``, ``AUTH_PROVIDER=identity_platform`` — emitted
  unconditionally; never derived from managed-TLS certificate readiness, DNS
  convergence, or identity-secret availability.
* ``SITE_URL`` is always ``https://<public_hostname>``. There is no
  ``http://<ingress-ip>`` fallback: a configured public hostname and managed
  TLS are mandatory inputs, and the renderer fails closed when either is
  missing. (Certificate *activation* is asynchronous and is handled by the
  deploy workflow — it does not change what this renderer emits.)
* The Identity Platform allow-list (``IDENTITY_ALLOWED_EMAIL_DOMAIN`` /
  ``IDENTITY_ALLOWED_EMAILS``) is rendered from the same Terraform outputs that
  configure the provider-side blocking function, so both enforce one policy.
"""

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


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def render_env(outputs: dict[str, object]) -> str:
    """Render the GCP portal runtime env contract.

    A configured public hostname and managed TLS are mandatory: the renderer
    fails closed (``ValueError``) rather than emitting an HTTP/ingress-IP
    runtime. The production security profile (debug disabled, secure
    session/CSRF cookies, Identity Platform auth, ``https://<hostname>``
    ``SITE_URL``) is emitted unconditionally.
    """
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
    identity_allowed_email_domain = str(_value(outputs, "identity_allowed_email_domain")).strip()
    identity_allowed_emails = _string_list(_value(outputs, "identity_allowed_emails"))
    public_hostname = _value(outputs, "public_hostname").strip()
    managed_tls_enabled = bool(_value(outputs, "managed_tls_enabled"))
    range_network_id = _value(outputs, "range_network_id")
    range_network_cidr = _value(outputs, "range_network_cidr")
    range_network_region = _value(outputs, "range_network_region")
    portal_network_cidrs = _value(outputs, "portal_network_cidrs")

    if not public_hostname or not managed_tls_enabled:
        raise ValueError(
            "GCP portal runtime requires public_hostname and managed_tls_enabled "
            f"(got public_hostname={public_hostname!r}, managed_tls_enabled={managed_tls_enabled}); "
            "refusing to render an insecure HTTP/ingress-IP runtime"
        )
    if not identity_allowed_email_domain:
        raise ValueError("GCP portal runtime requires identity_allowed_email_domain to be set")

    site_url = f"https://{public_hostname}"
    # The public hostname is the only externally addressable host. Health-check
    # probes hit /health/, which HealthCheckMiddleware short-circuits before
    # ALLOWED_HOSTS validation, so the ingress IP is intentionally not an
    # accepted application host. localhost/127.0.0.1 stay for in-pod probes and
    # port-forward debugging.
    allowed_hosts = ",".join(_unique([public_hostname, "localhost", "127.0.0.1"]))

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
        # Production runtime security profile — unconditional (ADR-008-R1, R3).
        "DJANGO_DEBUG": "false",
        "SESSION_COOKIE_SECURE": "true",
        "CSRF_COOKIE_SECURE": "true",
        "DB_HOST": database["private_ip"],
        "DB_PORT": str(database["port"]),
        # Redis host/port are non-secret and ride in the runtime ConfigMap.
        # REDIS_TLS / REDIS_SECRET_ID (added below) flag the secure posture
        # and point the entrypoint at the Secret Manager bundle that carries
        # the AUTH token; the password itself NEVER flows through this
        # ConfigMap-bound env (ADR-008-R6, #963).
        "REDIS_HOST": cache["host"],
        "REDIS_PORT": str(cache["port"]),
        "DJANGO_ALLOWED_HOSTS": allowed_hosts,
        "DJANGO_CSRF_TRUSTED_ORIGINS": site_url,
        "SITE_URL": site_url,
        "GUACAMOLE_BASE_URL": "/guacamole",
        "GUACAMOLE_API_BASE_URL": "http://guacamole-client.shifter-platform.svc.cluster.local:8080/guacamole",
        "GUACAMOLE_POSTGRESQL_HOSTNAME": guacamole_database["host"],
        "GUACAMOLE_POSTGRESQL_PORT": str(guacamole_database["port"]),
        "GUACAMOLE_POSTGRESQL_DATABASE": guacamole_database["database_name"],
        "ENGINE_TASK_IMAGE": f"{image_roots['pulumi-provisioner']}:latest",
        # GCP deployments authenticate against Identity Platform in every case.
        "AUTH_PROVIDER": "identity_platform",
        "IDENTITY_PLATFORM_API_KEY": identity_platform_api_key,
        "IDENTITY_PLATFORM_PROJECT_ID": identity_platform_project_id,
        "IDENTITY_PLATFORM_AUTH_DOMAIN": f"{identity_platform_project_id}.firebaseapp.com",
        # Allow-list rendered from the same Terraform outputs the provider-side
        # blocking function uses, so both enforce one policy.
        "IDENTITY_ALLOWED_EMAIL_DOMAIN": identity_allowed_email_domain,
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

    if identity_allowed_emails:
        values["IDENTITY_ALLOWED_EMAILS"] = ",".join(identity_allowed_emails)
    if bootstrap_staff_emails:
        values["PLATFORM_BOOTSTRAP_STAFF_EMAILS"] = bootstrap_staff_emails
    if bootstrap_superuser_emails:
        values["PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS"] = bootstrap_superuser_emails

    # Redis TLS posture and AUTH-secret pointer (ADR-008-R6, #963). This
    # renderer IS the GCP production runtime contract — there is no
    # legitimate path here where Memorystore lacks AUTH/TLS or where the
    # AUTH secret isn't published. If the Terraform outputs don't carry
    # the secure posture, the deploy is either pointed at a stale state
    # or has been rendered from a misconfigured environment; fail closed
    # so the misconfiguration surfaces at render time rather than as an
    # opaque Django startup or TLS handshake failure later. Local-dev
    # fallback (no REDIS_HOST at all) is handled separately in
    # config/settings.py and is unaffected by this gate.
    if not isinstance(cache, dict) or not cache.get("tls_enabled"):
        raise ValueError(
            "GCP runtime requires control_plane_cache.tls_enabled=true "
            "(ADR-008-R6); refusing to render an insecure Redis posture"
        )
    redis_secret_id = secret_ids.get("redis") if isinstance(secret_ids, dict) else None
    if not redis_secret_id:
        raise ValueError(
            'GCP runtime requires runtime_secret_ids["redis"] (the Memorystore '
            "AUTH/CA Secret Manager bundle) to be present in the Terraform outputs "
            "(ADR-008-R6); refusing to render without it"
        )
    values["REDIS_TLS"] = "true"
    values["REDIS_SECRET_ID"] = redis_secret_id

    return "".join(f"{key}={value}\n" for key, value in values.items())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terraform-output-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    outputs = json.loads(args.terraform_output_json.read_text())
    rendered = render_env(outputs)
    args.output.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
