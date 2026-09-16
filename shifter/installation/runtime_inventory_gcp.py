"""GCP backend runtime-env key inventories.

Split out of ``runtime_inventory`` so that module stays within the file-size
budget (SonarCloud S104). These frozensets are the GCP counterpart of the
AWS inventories and are re-exported by ``runtime_inventory`` for its existing
public import surface.
"""

from __future__ import annotations

GCP_GENERATED_RUNTIME_ENV_KEYS: frozenset[str] = frozenset(
    {
        "ACCESS_NETWORK_CIDRS",
        "APP_SECRET_ID",
        "AGENT_STORAGE_BUCKET",
        "AUTH_PROVIDER",
        # Renderer-owned selected-backend identity (PLAT-2005): the GCP backend
        # runtime-env renderer (scripts/gcp/render_runtime_env.py) IS this backend's
        # identity source, so CLOUD_PROVIDER is generated, not a static overlay literal.
        "CLOUD_PROJECT_ID",
        "CLOUD_PROVIDER",
        "CSRF_COOKIE_SECURE",
        "DB_HOST",
        "DB_NAME",
        "DB_PORT",
        "DB_SECRET_ID",
        "DB_USER",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "DJANGO_DEBUG",
        "DC_DOMAIN_PASSWORD_SECRET_ID",
        "EMAIL_BACKEND",
        "ENGINE_TASK_IMAGE",
        "GDC_NETWORK_DNS_NAMESERVERS",
        "GDC_NETWORK_INTERFACE",
        "GDC_RANGE_NAMESPACE_PREFIX",
        "GDC_STATIC_IP_RESERVATION_COUNT",
        "GCP_PROJECT_ID",
        "GCP_DYNAMIC_SECRET_PROJECT_ID",
        "GCP_RANGE_BACKEND",
        "GCP_RANGE_CELL_PROJECT_ID",
        "GOOGLE_CLOUD_PROJECT",
        "GUACAMOLE_API_BASE_URL",
        "GUACAMOLE_BASE_URL",
        "GUACAMOLE_POSTGRESQL_DATABASE",
        "GUACAMOLE_POSTGRESQL_HOSTNAME",
        "GUACAMOLE_POSTGRESQL_PORT",
        "GUACAMOLE_SECRET_ID",
        "IDENTITY_ALLOWED_EMAIL_DOMAIN",
        "IDENTITY_PLATFORM_API_KEY",
        "IDENTITY_PLATFORM_AUTH_DOMAIN",
        "IDENTITY_PLATFORM_ISSUER",
        "IDENTITY_PLATFORM_PROJECT_ID",
        "IDENTITY_PLATFORM_TOTP_DISPLAY_NAME",
        "MODEL_ACCESS_CATALOG_DIGEST",
        "MODEL_ACCESS_CATALOG_PATH",
        "MODEL_ACCESS_ENABLED",
        "PORTAL_NETWORK_CIDRS",
        "QUEUE_CMS_CONSUMER_ID",
        "QUEUE_CMS_PUBLISHER_ID",
        "QUEUE_ENGINE_CONSUMER_ID",
        "QUEUE_ENGINE_PUBLISHER_ID",
        "QUEUE_MC_CONSUMER_ID",
        "QUEUE_MC_PUBLISHER_ID",
        "RANGE_EVENTS_TOPIC_ID",
        "RANGE_NETWORK_CIDR",
        "RANGE_NETWORK_ID",
        "RANGE_NETWORK_REGION",
        "RANGE_VPC_CIDR",
        "RANGE_VPC_ID",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_SECRET_ID",
        "REDIS_TLS",
        "SESSION_COOKIE_SECURE",
        "SITE_URL",
        "STORAGE_BUCKET_NAME",
        "TF_STATE_BUCKET",
    }
)

GCP_OPTIONAL_GENERATED_RUNTIME_ENV_KEYS: frozenset[str] = frozenset(
    {
        "IDENTITY_ALLOWED_EMAILS",
        "PLATFORM_BOOTSTRAP_STAFF_EMAILS",
        "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS",
        # Transactional email (PLAT-002, #671) — emitted only when the operator
        # configures a SendGrid/Mailgun sender. EMAIL_BACKEND is always explicit
        # in generated runtime env; these are the extra sender-specific keys.
        # EMAIL_API_KEY_SECRET_ID is a Secret Manager reference, not the key
        # value. MAILGUN_SENDER_DOMAIN is emitted only for the Mailgun backend.
        "DEFAULT_FROM_EMAIL",
        "EMAIL_API_KEY_SECRET_ID",
        "GCP_PROVISIONER_SERVICE_ACCOUNT_EMAIL",
        "GCP_RANGE_CELL_NETWORK_MODE",
        "GCP_RANGE_DC_DISK_SIZE_GB",
        "GCP_RANGE_DC_DISK_TYPE",
        "GCP_RANGE_DC_IMAGE",
        "GCP_RANGE_DC_MACHINE_TYPE",
        "GCP_RANGE_EGRESS_ALLOW_CIDRS",
        "GCP_RANGE_HOST_MGMT_SSH_PORT",
        "GCP_RANGE_HOST_IDENTITY_POOL_SIZE",
        "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL",
        "GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES",
        "GCP_RANGE_KALI_ANTHROPIC_MODEL",
        "GCP_RANGE_KALI_ANTHROPIC_SMALL_FAST_MODEL",
        "GCP_RANGE_KALI_DISK_SIZE_GB",
        "GCP_RANGE_KALI_DISK_TYPE",
        "GCP_RANGE_KALI_IMAGE",
        "GCP_RANGE_IMAGE_KEY_PROFILES_JSON",
        "GCP_RANGE_KALI_MACHINE_TYPE",
        "GCP_RANGE_LINUX_DISK_SIZE_GB",
        "GCP_RANGE_LINUX_DISK_TYPE",
        "GCP_RANGE_LINUX_IMAGE",
        "GCP_RANGE_LINUX_MACHINE_TYPE",
        "GCP_RANGE_PLANE",
        "GCP_RANGE_PRIVATE_GOOGLE_ACCESS",
        "GCP_RANGE_VERTEX_PROJECT_ID",
        "GCP_RANGE_VERTEX_REGION",
        "GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL",
        "GCP_RANGE_VERTEX_SHARED_KEY_SECRET_ID",
        "GCP_RANGE_WINDOWS_DISK_SIZE_GB",
        "GCP_RANGE_WINDOWS_DISK_TYPE",
        "GCP_RANGE_WINDOWS_IMAGE",
        "GCP_RANGE_WINDOWS_MACHINE_TYPE",
        "GDC_ACCESS_SECRET_ID",
        "GDC_VM_IMAGE_GCS_SECRET_ID",
        "GDC_VMSERIES_BOOTSTRAP_XML_TEMPLATE_SECRET_ID",
        "GDC_VMSERIES_IMAGE_GCS_SECRET_ID",
        "MAILGUN_SENDER_DOMAIN",
        # Mission Control lease policy (#27): emitted only when the operator sets
        # settings.mission_control_leases; absent -> Django applies canonical defaults.
        "MISSION_CONTROL_LEASE_POLICY_JSON",
        "POLARIS_TESTS_BUCKET",
        "POLARIS_TESTS_KEY",
        "RANGE_NETWORK_ZONE",
        "RANGE_NETWORK_ZONES",
        "SHIFTER_CTF_CONTENT_BUCKET",
        "SHIFTER_CTF_CONTENT_MAX_BYTES",
        "SHIFTER_CTF_CONTENT_PREFIX",
    }
)

GCP_SECRET_RUNTIME_ENV_KEYS: frozenset[str] = frozenset()

# The generated runtime-env keys the standalone provisioner Job additionally receives
# (beyond the portal/worker platform image, which loads the whole generated env file).
# This is the subset of the generated GCP key set that the platform task runner forwards
# to the provisioner — it mirrors ``engine.ecs._GCP_PROVISIONER_ENV_KEYS`` intersected with
# the generated keys above. The installation package is standalone (it must not import the
# Django platform), so the set is declared here as data; a platform-side parity test
# (``tests/shared/cloud/test_gcp_runtime_role_parity.py``) fails if it drifts from the
# authoritative forwarding list. The backend bundle's generated-output ``process_roles``
# are derived from this set (portal/worker for every key, plus provisioner for these, plus
# range-task for the ``GCP_RANGE_*`` guest-configuration keys among them).
GCP_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS: frozenset[str] = frozenset(
    {
        "ACCESS_NETWORK_CIDRS",
        "AGENT_STORAGE_BUCKET",
        "CLOUD_PROJECT_ID",
        "CLOUD_PROVIDER",
        "DB_HOST",
        "DB_NAME",
        "DB_PORT",
        "DB_USER",
        "ENGINE_TASK_IMAGE",
        "GCP_PROJECT_ID",
        "GCP_DYNAMIC_SECRET_PROJECT_ID",
        "GCP_PROVISIONER_SERVICE_ACCOUNT_EMAIL",
        "GCP_RANGE_BACKEND",
        "GCP_RANGE_CELL_NETWORK_MODE",
        "GCP_RANGE_DC_DISK_SIZE_GB",
        "GCP_RANGE_DC_DISK_TYPE",
        "GCP_RANGE_DC_IMAGE",
        "GCP_RANGE_DC_MACHINE_TYPE",
        "GCP_RANGE_EGRESS_ALLOW_CIDRS",
        "GCP_RANGE_HOST_MGMT_SSH_PORT",
        "GCP_RANGE_HOST_IDENTITY_POOL_SIZE",
        "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL",
        "GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES",
        "GCP_RANGE_KALI_ANTHROPIC_MODEL",
        "GCP_RANGE_KALI_ANTHROPIC_SMALL_FAST_MODEL",
        "GCP_RANGE_KALI_DISK_SIZE_GB",
        "GCP_RANGE_KALI_DISK_TYPE",
        "GCP_RANGE_KALI_IMAGE",
        "GCP_RANGE_IMAGE_KEY_PROFILES_JSON",
        "GCP_RANGE_KALI_MACHINE_TYPE",
        "GCP_RANGE_LINUX_DISK_SIZE_GB",
        "GCP_RANGE_LINUX_DISK_TYPE",
        "GCP_RANGE_LINUX_IMAGE",
        "GCP_RANGE_LINUX_MACHINE_TYPE",
        "GCP_RANGE_PLANE",
        "GCP_RANGE_PRIVATE_GOOGLE_ACCESS",
        "GCP_RANGE_VERTEX_PROJECT_ID",
        "GCP_RANGE_VERTEX_REGION",
        "GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL",
        "GCP_RANGE_VERTEX_SHARED_KEY_SECRET_ID",
        "GCP_RANGE_WINDOWS_DISK_SIZE_GB",
        "GCP_RANGE_WINDOWS_DISK_TYPE",
        "GCP_RANGE_WINDOWS_IMAGE",
        "GCP_RANGE_WINDOWS_MACHINE_TYPE",
        "GDC_ACCESS_SECRET_ID",
        "GDC_NETWORK_DNS_NAMESERVERS",
        "GDC_NETWORK_INTERFACE",
        "GDC_RANGE_NAMESPACE_PREFIX",
        "GDC_STATIC_IP_RESERVATION_COUNT",
        "GDC_VM_IMAGE_GCS_SECRET_ID",
        "GDC_VMSERIES_BOOTSTRAP_XML_TEMPLATE_SECRET_ID",
        "GDC_VMSERIES_IMAGE_GCS_SECRET_ID",
        "GOOGLE_CLOUD_PROJECT",
        "POLARIS_TESTS_BUCKET",
        "POLARIS_TESTS_KEY",
        "PORTAL_NETWORK_CIDRS",
        "RANGE_NETWORK_CIDR",
        "RANGE_NETWORK_ID",
        "RANGE_NETWORK_REGION",
        "RANGE_NETWORK_ZONE",
        "RANGE_VPC_CIDR",
        "RANGE_VPC_ID",
        "STORAGE_BUCKET_NAME",
    }
)
