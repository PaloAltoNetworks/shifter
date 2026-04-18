# Docker Deployment: Single-Tenant Shifter

## Goal

Make Shifter fully runnable via `docker compose up` on any machine with AWS credentials, for a single technical seller running demos, CTFs, or experiments. Deployed for days-to-weeks at a time.

## Current State

The local dev compose already runs:
- Django (web) with Daphne ASGI
- PostgreSQL 16
- Redis 7
- LocalStack (SNS/SQS/S3)
- 3 SQS workers (cms, engine, mc)

Missing from compose:
- Guacamole (guacd + client) - has Dockerfiles, not wired in
- Provisioner - has Dockerfile, not wired in
- TLS termination (ALB in prod)
- Guacamole has its own RDS in prod

Auth: Cognito OIDC in prod, `dev_login` bypass in DEBUG mode. Keep Cognito.

## Phases

| Phase | What | Risk |
|-------|------|------|
| 1 | Consolidate Guacamole onto main Postgres | Low - idempotent schema init already exists |
| 2 | Add Guacamole stack to docker-compose | Low - Dockerfiles exist |
| 3 | Add provisioner to docker-compose | Medium - needs real AWS creds |
| 4 | Add nginx for TLS + routing | Low - standard pattern |
| 5 | Production-mode compose profile | Medium - Cognito config, secrets |

## Constraints

- AWS creds required (ranges provision real EC2 instances)
- Cognito stays as auth provider
- Single Postgres instance for Django + Guacamole
- Runs on a single host (EC2, dev box, etc.)
- Secure enough for weeks of uptime, not permanent infrastructure

## Out of Scope

- Multi-host / HA (we just turned that off)
- Replacing Cognito with local auth
- Mocking the provisioner / AWS services
- Kubernetes or ECS deployment
