"""Cloud-provider, storage, ECS / GKE task-runner, and SQS/Pub-Sub config.

Extracted from ``config/settings.py`` to keep that module under the
500-line cap (Sonar S104). The module exposes plain values and one
helper function; ``config.settings`` star-imports the public names and
calls the helper to build ``QUEUE_CONFIG``.
"""

from __future__ import annotations

import os

__all__ = [
    "AWS_ENDPOINT_URL",
    "AWS_REGION",
    "AWS_S3_BUCKET_NAME",
    "AWS_S3_REGION",
    "CLOUD_PROVIDER",
    "CLOUD_REGION",
    "ENGINE_ECS_CLUSTER_ARN",
    "ENGINE_ECS_SECURITY_GROUP_ID",
    "ENGINE_PRIVATE_SUBNET_IDS",
    "ENGINE_TASK_BACKOFF_LIMIT",
    "ENGINE_TASK_CLUSTER",
    "ENGINE_TASK_DEFINITION",
    "ENGINE_TASK_DEFINITION_ARN",
    "ENGINE_TASK_IMAGE_PULL_POLICY",
    "ENGINE_TASK_NETWORK_SECURITY_GROUP_ID",
    "ENGINE_TASK_NETWORK_SUBNET_IDS",
    "ENGINE_TASK_SERVICE_ACCOUNT_NAME",
    "ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED",
    "EXPERIMENT_TASK_DEFINITION",
    "EXPERIMENT_TASK_DEFINITION_ARN",
    "GCP_PROJECT_ID",
    "GCP_REGION",
    "GOOGLE_CLOUD_PROJECT",
    "LOCAL_PROVISIONER",
    "PROVISIONER_PATH",
    "QUEUE_CONFIG",
    "RANGE_EVENTS_TOPIC_ID",
    "SNS_RANGE_EVENTS_ARN",
    "SQS_QUEUE_CONFIG",
    "STORAGE_BUCKET_NAME",
]

# ------------------------------------------------------------------------------
# Cloud Provider Configuration
# ------------------------------------------------------------------------------

# Which cloud provider to use: "aws" (default) or "gcp" (future)
CLOUD_PROVIDER = os.environ.get("CLOUD_PROVIDER", "aws")
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID") or GOOGLE_CLOUD_PROJECT
GCP_REGION = os.environ.get("GCP_REGION") or os.environ.get("CLOUD_REGION", "")

# Generic names — adapters use these; AWS-specific names kept as fallbacks
CLOUD_REGION = (
    os.environ.get("CLOUD_REGION") or os.environ.get("AWS_REGION") or os.environ.get("AWS_S3_REGION", "us-east-2")
)
STORAGE_BUCKET_NAME = os.environ.get("STORAGE_BUCKET_NAME") or os.environ.get("AWS_S3_BUCKET_NAME", "")

# ------------------------------------------------------------------------------
# AWS S3 Configuration
# ------------------------------------------------------------------------------

# Backward compat alias
AWS_S3_BUCKET_NAME = STORAGE_BUCKET_NAME
# Backward compat alias
AWS_S3_REGION = CLOUD_REGION
# Backward compat alias
AWS_REGION = CLOUD_REGION
# LocalStack support
AWS_ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL", "")

# Topic for publishing events (provisioner -> workers)
RANGE_EVENTS_TOPIC_ID = os.environ.get("RANGE_EVENTS_TOPIC_ID") or os.environ.get("SNS_RANGE_EVENTS_ARN", "")
# Backward compat alias
SNS_RANGE_EVENTS_ARN = RANGE_EVENTS_TOPIC_ID

# Shifter Engine task runner configuration.
# AWS uses ECS-compatible values. GCP uses a Kubernetes namespace plus a
# container image that the GKE-native task runner launches as a Job.
ENGINE_TASK_CLUSTER = (
    os.environ.get("ENGINE_TASK_NAMESPACE")
    or os.environ.get("ENGINE_TASK_CLUSTER")
    or os.environ.get("ENGINE_JOB_LOCATION")
    or os.environ.get("ENGINE_ECS_CLUSTER_ARN")
    or os.environ.get("PULUMI_ECS_CLUSTER_ARN", "")
)
ENGINE_TASK_DEFINITION = (
    os.environ.get("ENGINE_TASK_DEFINITION")
    or os.environ.get("ENGINE_TASK_IMAGE")
    or os.environ.get("ENGINE_TASK_DEFINITION_ARN")
    or os.environ.get("PULUMI_TASK_DEFINITION_ARN", "")
)
ENGINE_TASK_SERVICE_ACCOUNT_NAME = os.environ.get("ENGINE_TASK_SERVICE_ACCOUNT_NAME", "")
ENGINE_TASK_IMAGE_PULL_POLICY = os.environ.get("ENGINE_TASK_IMAGE_PULL_POLICY", "IfNotPresent")
ENGINE_TASK_BACKOFF_LIMIT = int(os.environ.get("ENGINE_TASK_BACKOFF_LIMIT", "0"))
ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED = int(os.environ.get("ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED", "3600"))
ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = (
    os.environ.get("ENGINE_TASK_NETWORK_SECURITY_GROUP_ID")
    or os.environ.get("ENGINE_ECS_SECURITY_GROUP_ID")
    or os.environ.get("PULUMI_ECS_SECURITY_GROUP_ID", "")
)
ENGINE_TASK_NETWORK_SUBNET_IDS = (
    os.environ.get("ENGINE_TASK_NETWORK_SUBNET_IDS")
    or os.environ.get("ENGINE_PRIVATE_SUBNET_IDS")
    or os.environ.get("PULUMI_PRIVATE_SUBNET_IDS", "")
)

# Backward compat aliases for existing AWS call sites and tests
ENGINE_ECS_CLUSTER_ARN = ENGINE_TASK_CLUSTER
ENGINE_TASK_DEFINITION_ARN = ENGINE_TASK_DEFINITION
ENGINE_ECS_SECURITY_GROUP_ID = ENGINE_TASK_NETWORK_SECURITY_GROUP_ID
ENGINE_PRIVATE_SUBNET_IDS = ENGINE_TASK_NETWORK_SUBNET_IDS
EXPERIMENT_TASK_DEFINITION = os.environ.get("EXPERIMENT_TASK_DEFINITION") or os.environ.get(
    "EXPERIMENT_TASK_DEFINITION_ARN", ""
)
EXPERIMENT_TASK_DEFINITION_ARN = EXPERIMENT_TASK_DEFINITION

# Local Provisioner (for local dev - runs provisioner as subprocess instead of ECS)
LOCAL_PROVISIONER = os.environ.get("LOCAL_PROVISIONER", "")
PROVISIONER_PATH = os.environ.get("PROVISIONER_PATH", "")

# ------------------------------------------------------------------------------
# SQS / Pub-Sub Worker Queues
# ------------------------------------------------------------------------------
# Queue identifiers are passed via environment variables by the deployment workflow.
# On AWS the consumer and publisher both use the same SQS URL. On GCP workers
# consume Pub/Sub subscriptions while publishers target topics, so the config
# allows those identifiers to diverge without changing existing AWS call sites.


def _build_queue_config(name: str, legacy_env: str, handler: str) -> dict[str, str]:
    """Read consumer/publisher IDs for a named queue, honoring legacy env-var aliases."""
    consumer_id = (
        os.environ.get(f"QUEUE_{name}_CONSUMER_ID")
        or os.environ.get(f"QUEUE_{name}_ID")
        or os.environ.get(legacy_env, "")
    )
    publisher_id = (
        os.environ.get(f"QUEUE_{name}_PUBLISHER_ID") or os.environ.get(f"QUEUE_{name}_TOPIC_ID") or consumer_id
    )
    return {
        "url": consumer_id,
        "consumer_id": consumer_id,
        "publisher_id": publisher_id,
        "handler": handler,
    }


QUEUE_CONFIG = {
    "cms": _build_queue_config("CMS", "SQS_CMS_URL", "cms.handlers.process_event"),
    "engine": _build_queue_config("ENGINE", "SQS_ENGINE_URL", "engine.handlers.process_event"),
    "mc": _build_queue_config("MC", "SQS_MC_URL", "mission_control.handlers.process_event"),
    "experiments": _build_queue_config(
        "EXPERIMENTS",
        "SQS_EXPERIMENTS_URL",
        "cms.experiments.handlers.process_event",
    ),
}
# Backward compat alias
SQS_QUEUE_CONFIG = QUEUE_CONFIG
