# Cloud Adapters

Protocol-based abstractions that isolate cloud-specific code. The same Django application runs on AWS or GCP without conditional logic in business code.

## How It Works

`CLOUD_PROVIDER` environment variable (`aws` or `gcp`) selects the active provider. Factory functions lazy-import the matching implementation. Unrecognized providers raise `CloudProviderNotImplementedError`.

Two independent adapter sets exist: one for the platform (Django), one for the provisioner (standalone process).

## Platform Adapters

Defined in `shifter_platform/shared/cloud/types.py`. Obtained via factory functions in `shifter_platform/shared/cloud/__init__.py`.

| Protocol | Methods | AWS | GCP |
|----------|---------|-----|-----|
| **ObjectStorage** | `upload_file`, `delete_object`, `head_object`, `generate_presigned_upload_url`, `generate_presigned_download_url`, `tag_object` | S3 | GCS |
| **TaskRunner** | `run_task`, `get_task_status` | ECS Fargate | Kubernetes Job |
| **QueueConsumer** | `receive_messages`, `delete_message` | SQS | Pub/Sub |
| **QueuePublisher** | `send_message` | SQS | Pub/Sub |
| **SecretsStore** | `get_secret` | Secrets Manager | Secret Manager |

Factory functions: `get_object_storage()`, `get_task_runner()`, `get_queue_consumer()`, `get_queue_publisher()`, `get_secrets_store()`.

## Provisioner Adapters

Defined in `engine/provisioner/cloud/types.py`. Obtained via factory functions in `engine/provisioner/cloud/__init__.py`.

| Protocol | Methods | AWS | GCP |
|----------|---------|-----|-----|
| **EventBus** | `publish` | SNS | Pub/Sub |
| **ConfigStore** | `get_parameter` | SSM Parameter Store | Secret Manager |
| **DBAuth** | `generate_auth_token` | RDS IAM auth | Cloud SQL IAM auth |
| **SecretsStore** | `get_secret` | Secrets Manager | Secret Manager |
| **ObjectStorage** | `generate_presigned_download_url`, `object_exists`, `delete_object` | S3 | GCS |
| **NetworkInventory** | `list_subnet_cidrs`, `publish_subnet_exhaustion_alarm` | EC2 VPC API | GDC/GKE API |

Factory functions: `get_event_bus()`, `get_config_store()`, `get_db_auth()`, `get_secrets_store()`, `get_object_storage()`, `get_network_inventory()`.

## Adding a New Provider

1. Create implementation module in `shared/cloud/{provider}/` (platform) or `provisioner/cloud/{provider}/` (provisioner)
2. Implement all protocols from `types.py`
3. Add the provider branch to each factory function in `__init__.py`

## File Locations

```
shifter_platform/shared/cloud/
├── __init__.py          # Platform factory functions
├── types.py             # Platform protocol definitions
├── aws/                 # AWS implementations
│   ├── storage.py       # S3
│   ├── task_runner.py   # ECS Fargate
│   ├── queue.py         # SQS
│   └── secrets.py       # Secrets Manager
└── gcp/                 # GCP implementations
    ├── storage.py       # GCS
    ├── task_runner.py   # Kubernetes Job
    ├── queue.py         # Pub/Sub
    └── secrets.py       # Secret Manager

engine/provisioner/cloud/
├── __init__.py          # Provisioner factory functions
├── types.py             # Provisioner protocol definitions
├── aws/                 # AWS implementations
│   ├── event_bus.py     # SNS
│   ├── config_store.py  # SSM Parameter Store
│   ├── db_auth.py       # RDS IAM
│   ├── storage.py       # S3
│   ├── secrets.py       # Secrets Manager
│   └── network.py       # EC2 VPC
└── gcp/                 # GCP implementations
    ├── event_bus.py     # Pub/Sub
    ├── config_store.py  # Secret Manager
    ├── db_auth.py       # Cloud SQL IAM
    ├── storage.py       # GCS
    ├── secrets.py       # Secret Manager
    └── network.py       # GDC/GKE
```
