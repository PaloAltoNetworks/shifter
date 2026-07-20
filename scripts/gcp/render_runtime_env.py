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
import re
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


_CONSOLE_EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
_MAILGUN_EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"
_GCE_RANGE_ENV_KEYS = (
    "GCP_RANGE_PLANE",
    "GCP_RANGE_CELL_NETWORK_MODE",
    "RANGE_NETWORK_ZONE",
    "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL",
    "GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES",
    "GCP_RANGE_LINUX_IMAGE",
    "GCP_RANGE_LINUX_MACHINE_TYPE",
    "GCP_RANGE_LINUX_DISK_SIZE_GB",
    "GCP_RANGE_LINUX_DISK_TYPE",
    "GCP_RANGE_KALI_IMAGE",
    "GCP_RANGE_KALI_MACHINE_TYPE",
    "GCP_RANGE_KALI_DISK_SIZE_GB",
    "GCP_RANGE_KALI_DISK_TYPE",
    "GCP_RANGE_IMAGE_KEY_PROFILES_JSON",
    "GCP_RANGE_WINDOWS_IMAGE",
    "GCP_RANGE_WINDOWS_MACHINE_TYPE",
    "GCP_RANGE_WINDOWS_DISK_SIZE_GB",
    "GCP_RANGE_WINDOWS_DISK_TYPE",
    "GCP_RANGE_DC_IMAGE",
    "GCP_RANGE_DC_MACHINE_TYPE",
    "GCP_RANGE_DC_DISK_SIZE_GB",
    "GCP_RANGE_DC_DISK_TYPE",
    "GCP_RANGE_EGRESS_ALLOW_CIDRS",
    "GCP_RANGE_PRIVATE_GOOGLE_ACCESS",
    "GCP_RANGE_HOST_MGMT_SSH_PORT",
    "GCP_RANGE_VERTEX_PROJECT_ID",
    "GCP_RANGE_VERTEX_REGION",
    "GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL",
    "GCP_RANGE_KALI_ANTHROPIC_MODEL",
    "GCP_RANGE_KALI_ANTHROPIC_SMALL_FAST_MODEL",
    "POLARIS_TESTS_BUCKET",
    "POLARIS_TESTS_KEY",
)


def _email_runtime_values(outputs: dict[str, object]) -> dict[str, str]:
    """Optional transactional-email runtime env for GCP (PLAT-002, #671).

    Email is **optional**: when no ``email_config`` Terraform output is present
    the runtime explicitly selects the console backend. When the output *is*
    present it must be complete — ``backend`` and
    ``api_key_secret_id`` are both required — so a half-configured deployment
    fails at render time rather than silently dropping mail.

    Only the secret **reference** (``EMAIL_API_KEY_SECRET_ID``) is emitted here;
    the ESP API key itself is hydrated from Secret Manager by ``entrypoint.sh``
    and never travels through this ConfigMap-bound env (same posture as the
    Redis AUTH bundle, ADR-008).
    """
    raw = outputs.get("email_config")
    config = raw.get("value") if isinstance(raw, dict) else None
    if not isinstance(config, dict) or not config:
        return {"EMAIL_BACKEND": _CONSOLE_EMAIL_BACKEND}

    backend = str(config.get("backend", "")).strip()
    secret_id = str(config.get("api_key_secret_id", "")).strip()
    from_email = str(config.get("from_email", "")).strip()
    sender_domain = str(config.get("sender_domain", "")).strip()

    # Fail closed on an enabled-but-unusable sender. A non-empty email_config
    # means the operator opted into real delivery, so every field the ESP needs
    # to send must be present: both backends need a From address (otherwise mail
    # goes out as Django's webmaster@localhost), and Mailgun additionally needs
    # its sender domain. Surface the gap at render time, not as a runtime send
    # failure.
    missing = []
    if not backend:
        missing.append("backend")
    if not secret_id:
        missing.append("api_key_secret_id")
    if not from_email:
        missing.append("from_email")
    if backend == _MAILGUN_EMAIL_BACKEND and not sender_domain:
        missing.append("sender_domain")
    if missing:
        raise ValueError(
            "GCP email_config is incomplete (missing: " + ", ".join(missing) + "); "
            "refusing to render an email runtime that cannot send"
        )

    email_values = {
        "EMAIL_BACKEND": backend,
        "EMAIL_API_KEY_SECRET_ID": secret_id,
        "DEFAULT_FROM_EMAIL": from_email,
    }
    if backend == _MAILGUN_EMAIL_BACKEND:
        email_values["MAILGUN_SENDER_DOMAIN"] = sender_domain
    return email_values


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build one JSON object without silently overwriting duplicate keys."""
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def _canonical_image_key_profiles(raw: str) -> str:
    """Return compact one-line JSON while preserving semantic validation for the provisioner."""
    if len(raw.encode("utf-8")) > 32_768:
        raise ValueError("GCP_RANGE_IMAGE_KEY_PROFILES_JSON exceeds the 32768-byte configuration limit")
    try:
        decoded = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except json.JSONDecodeError as exc:
        raise ValueError(f"GCP_RANGE_IMAGE_KEY_PROFILES_JSON must be valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError("GCP_RANGE_IMAGE_KEY_PROFILES_JSON must be a JSON object")
    return json.dumps(decoded, separators=(",", ":"), sort_keys=True)


def _optional_gce_range_values() -> dict[str, str]:
    values = {key: value for key in _GCE_RANGE_ENV_KEYS if (value := os.environ.get(key, "").strip())}
    if raw_profiles := values.get("GCP_RANGE_IMAGE_KEY_PROFILES_JSON"):
        values["GCP_RANGE_IMAGE_KEY_PROFILES_JSON"] = _canonical_image_key_profiles(raw_profiles)
    return values


def _project_from_self_link(self_link: object) -> str:
    """Extract the GCP project id from a ``projects/<project>/...`` self-link.

    The range VPC self-link (``range_network_id`` Terraform output) always
    carries the real range project, which is what the GCE range-cell backend
    must target for Compute API calls and image URLs — independent of the
    control-plane ``GCP_PROJECT_ID`` (which may be a deploy-overlay placeholder).
    """
    text = str(self_link or "").strip()
    parts = text.split("/")
    if "projects" in parts:
        index = parts.index("projects")
        if index + 1 < len(parts) and parts[index + 1]:
            return parts[index + 1]
    return ""


_ENGINE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _validated_engine_digest(engine_image_digest: str) -> str:
    """Require an immutable ``sha256:<64 hex>`` provisioner image digest.

    The CI GKE deploy path passes the verified build digest so ENGINE_TASK_IMAGE
    (which the GKE ValidatingAdmissionPolicy pins to, ADR-006-R4) is the exact
    attested image, never a mutable tag (ADR-037-R6).
    """
    digest = engine_image_digest.strip()
    if not digest:
        raise ValueError("engine_image_digest must be non-empty")
    if not _ENGINE_DIGEST_RE.match(digest):
        raise ValueError(
            "engine_image_digest must be an immutable sha256 digest (sha256:<64 hex>); refusing to render a mutable tag"
        )
    return digest


def _engine_task_image(root: str, engine_image: str) -> str:
    """Build ENGINE_TASK_IMAGE from the provisioner image root.

    ``engine_image`` is either an immutable ``sha256:<64 hex>`` digest (the CI
    GKE deploy path, ADR-037-R6 -> ``root@digest``) or a version tag (the GDC
    bootstrap path, which resolves its own image identity -> ``root:tag``).
    ``latest`` and empty values are refused in both modes.
    """
    identity = engine_image.strip()
    if not identity:
        raise ValueError("engine_image must be non-empty")
    if _ENGINE_DIGEST_RE.match(identity):
        return f"{root}@{identity}"
    if identity == "latest":
        raise ValueError("engine_image must be immutable; refusing to render latest")
    return f"{root}:{identity}"


def render_env(outputs: dict[str, object], *, engine_image: str) -> str:
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
    # The real deploy GCP project. Google client libraries use GCP_PROJECT_ID /
    # GOOGLE_CLOUD_PROJECT as the default quota/consumer project, so a placeholder
    # here makes every API call bill an invalid project (CONSUMER_INVALID). Derive
    # it from the Identity Platform project (the deploy project), falling back to
    # the project in the range VPC self-link.
    real_project = str(identity_platform_project_id).strip() or _project_from_self_link(range_network_id)

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
    # probes hit /health/ with the ingress IP as the Host header; the
    # path-scoped `HealthCheckMiddleware` overrides that to `localhost` so
    # `ALLOWED_HOSTS` admits the request, and then the real
    # `config.health.CoarseHealthCheckView` runs the `django-health-check`
    # probes (DB / cache / storage). The ingress IP is intentionally not an
    # accepted application host outside that path. localhost / 127.0.0.1 stay
    # for in-pod probes and port-forward debugging. See issue #477 and
    # `docs/architecture/portal-health-readiness-preflight-477.md`.
    allowed_hosts = ",".join(_unique([public_hostname, "localhost", "127.0.0.1"]))

    bootstrap_staff_emails = ",".join(_csv_env("PLATFORM_BOOTSTRAP_STAFF_EMAILS"))
    bootstrap_superuser_emails = ",".join(_csv_env("PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS"))

    values = {
        # This module IS the GCP backend runtime-env renderer (installation.registry's
        # ``_cloud_provider_output``); CLOUD_PROVIDER is this backend's own identity,
        # renderer-owned rather than a static overlay literal or branch-name inference
        # (PLAT-2005, docs/architecture/root-configured-backend-bundles.md).
        "CLOUD_PROVIDER": "gcp",
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
        "DB_SECRET_ID": secret_ids["db"],
        "APP_SECRET_ID": secret_ids["app"],
        "GUACAMOLE_SECRET_ID": secret_ids["guacamole-json-auth"],
        "GDC_ACCESS_SECRET_ID": _derive_sibling_secret_id(secret_ids["app"], "app", "gdc-access"),
        # Prebaked Windows DC domain Administrator password (GCE + GDC range
        # backends). The entrypoint resolves DC_DOMAIN_PASSWORD from this
        # reference and ecs.py passes it into the provisioner Job; without it the
        # DC's set_admin_password step gets an empty password. Only the secret
        # reference rides the ConfigMap; the value never does.
        "DC_DOMAIN_PASSWORD_SECRET_ID": _derive_sibling_secret_id(secret_ids["app"], "app", "dc-domain-password"),
        # Production runtime security profile — unconditional (ADR-008-R1, R3).
        "DJANGO_DEBUG": "false",
        "SESSION_COOKIE_SECURE": "true",
        "CSRF_COOKIE_SECURE": "true",
        "DB_HOST": database["private_ip"],
        "DB_PORT": str(database["port"]),
        # DB_NAME / DB_USER are non-secret and MUST ride the runtime ConfigMap as
        # literals: the restrict-provisioner-jobs admission policy (issue #1177)
        # lists them in requiredLiteralEnv and validates every Job literal against
        # this ConfigMap (params.data). The provisioner-launcher emits them (the
        # entrypoint hydrates them into the pod env from the DB secret bundle), so
        # if they are absent here the policy denies every range Job (#1742). Only
        # DB_PASSWORD is Secret-backed; name/user are plain connection metadata.
        "DB_NAME": database["database_name"],
        "DB_USER": database["user_name"],
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
        "ENGINE_TASK_IMAGE": _engine_task_image(image_roots["pulumi-provisioner"], engine_image),
        # GCP deployments authenticate against Identity Platform in every case.
        "AUTH_PROVIDER": "identity_platform",
        # Real deploy project (not the overlay placeholder), so Google client
        # libraries bill the correct quota/consumer project.
        "GCP_PROJECT_ID": real_project,
        "GOOGLE_CLOUD_PROJECT": real_project,
        # CLOUD_PROJECT_ID is emitted by the provisioner-launcher (its
        # _get_gcp_provisioner_env_overrides fallback is settings.GCP_PROJECT_ID),
        # so it must be present in this ConfigMap or the restrict-provisioner-jobs
        # policy denies the Job (#1742). Mirror GCP_PROJECT_ID (the real project).
        "CLOUD_PROJECT_ID": real_project,
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
        "GCP_RANGE_BACKEND": os.environ.get("GCP_RANGE_BACKEND", "gce").strip() or "gce",
        # Real range project (from the range VPC self-link), so the GCE
        # range-cell backend targets it directly even when the control-plane
        # GCP_PROJECT_ID is a deploy-overlay placeholder. An explicit
        # GCP_RANGE_CELL_PROJECT_ID env override wins.
        "GCP_RANGE_CELL_PROJECT_ID": (
            os.environ.get("GCP_RANGE_CELL_PROJECT_ID", "").strip() or _project_from_self_link(range_network_id)
        ),
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

    # Optional transactional-email runtime env (PLAT-002, #671). Absent ->
    # console backend; present -> SendGrid/Mailgun via anymail with the API key
    # hydrated from Secret Manager by the entrypoint.
    values.update(_email_runtime_values(outputs))
    values.update(_optional_gce_range_values())

    return "".join(f"{key}={value}\n" for key, value in values.items())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terraform-output-json", required=True, type=Path)
    parser.add_argument("--engine-image-digest", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    outputs = json.loads(args.terraform_output_json.read_text())
    # The CLI (CI GKE deploy) enforces an immutable digest (ADR-037-R6); the
    # GDC bootstrap calls render_env() directly with its own image identity.
    rendered = render_env(outputs, engine_image=_validated_engine_digest(args.engine_image_digest))
    args.output.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
