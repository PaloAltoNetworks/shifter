# GCP Dev Environment

Placeholder for GCP infrastructure (GKE + KubeVirt range provisioning).

This environment will contain Terraform configurations for:
- GKE cluster with KubeVirt for full VM range instances
- Cloud SQL (PostgreSQL) for the platform database
- GCS buckets for state and agent storage
- Pub/Sub for event messaging
- Secret Manager for credentials
- Artifact Registry for VM disk images

## Status

Not yet implemented. The `--provider gcp` flag in `deploy.py` will target
this directory once GCP Terraform modules are built.

## Migration Plan

Ranges migrate first (GKE + KubeVirt), portal follows later.
AWS infrastructure remains fully operational throughout migration.
