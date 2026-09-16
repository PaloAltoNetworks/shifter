---
id: CTF-1006
title: "Scheduler Auto-Start"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.932719Z
updated_at: 2026-03-19T04:02:00.063473Z
---

# CTF-1006: Scheduler Auto-Start

## Statement

The system should automatically start the CTF task scheduler when the application starts, without requiring manual intervention or separate process management. The scheduler shall detect and recover from crashes by re-evaluating all pending tasks on startup. The scheduler shall not duplicate task executions or miss scheduled tasks after application restart.

## Rationale

Manual scheduler startup is a deployment hazard, if someone deploys the application and forgets to start the scheduler, all automated tasks silently fail. Auto-start ensures the scheduler is always running when the application is running. Crash recovery prevents missed tasks after infrastructure incidents.

## Traceability

- IMPLEMENTS → CODE_FILE `ctf/apps.py` (CTF App Configuration)
- IMPLEMENTS → CONFIG `.github/workflows/_shifter-platform.yml` (CI/CD Workflow - deploys ctf-scheduler alongside portal)
- IMPLEMENTS → CODE_FILE `ctf/management/commands/run_ctf_scheduler.py` (CTF Scheduled Task Executor Management Command)
- IMPLEMENTS → CODE_FILE `ctf/models.py` (CTF Models (CTFScheduledTask))
- IMPLEMENTS → CONFIG `platform/terraform/modules/portal/ec2/user_data.sh` (EC2 User Data - auto-starts ctf-scheduler with --restart unless-stopped)
- IMPLEMENTS → CONFIG `shifter/shifter_platform/docker-compose.yml` (Docker Compose - ctf-scheduler service (restart: always))
- IMPLEMENTS → CONFIG `platform/k8s/gcp/base/ctf-scheduler-deployment.yaml` (GCP base ctf-scheduler Deployment with dedicated job-launcher token)
- IMPLEMENTS → CONFIG `platform/k8s/gcp/base/rbac-job-launcher.yaml` (GCP base job-launcher RBAC for ctf-scheduler)
- IMPLEMENTS → CONFIG `platform/k8s/gcp/base/serviceaccounts.yaml` (GCP base ctf-scheduler ServiceAccount)
- IMPLEMENTS → CONFIG `platform/charts/shifter/templates/ctf-scheduler-deployment.yaml` (Helm ctf-scheduler Deployment with dedicated job-launcher token)
- IMPLEMENTS → CONFIG `platform/charts/shifter/templates/rbac-job-launcher.yaml` (Helm job-launcher RBAC for ctf-scheduler)
- IMPLEMENTS → CONFIG `platform/charts/shifter/templates/serviceaccounts.yaml` (Helm ctf-scheduler ServiceAccount)
- IMPLEMENTS → CONFIG `platform/charts/shifter/values.yaml` (Helm ctfScheduler service account value)
- TESTS → TEST `shifter/shifter_platform/tests/platform/test_ctf_scheduler_startup.py` (CTF scheduler startup deployment invariants)
- TESTS → TEST `shifter/shifter_platform/tests/platform/test_gcp_job_launcher_manifests.py` (GCP job-launcher token and RBAC invariants)
- IMPLEMENTS → CODE_FILE `platform/terraform/modules/portal/ec2/worker-health/shifter-worker-health.sh` (Worker health supervisor, detects a wedged/unhealthy ctf-scheduler (not just process exit) and restarts it, triggering its startup task re-evaluation (#953))
- TESTS → TEST `shifter/shifter_platform/tests/platform/test_worker_health_supervision.py` (Verifies the supervisor restarts unhealthy ctf-scheduler/workers and is installed on both AWS deploy paths (#953))
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
