# Technical Documentation

Platform architecture, infrastructure, and development documentation.

## Architecture

- [Architecture Overview](architecture) - Platform structure and design decisions

## Platform Domains

- [Platform Overview](shifter_platform/) - Domain architecture
- [Mission Control](shifter_platform/mission_control) - Presentation layer
- [Engine](shifter_platform/engine) - Range orchestration
- [CMS](shifter_platform/cms) - Content management
- [Management](shifter_platform/management) - Administration

## Infrastructure

- [Infrastructure Overview](platform_infrastructure/) - AWS and GCP components
- [GCP Infrastructure](platform_infrastructure/gcp-infrastructure) - GKE, Cloud SQL, Kustomize
- [GDC Provisioning](platform_infrastructure/gdc-provisioning) - Range guests on GDC (KubeVirt, pods)
- [Networking](platform_infrastructure/networking) - Network architecture (both clouds)
- [CI/CD](platform_infrastructure/cicd) - Deployment pipelines
- [Machine Images](platform_infrastructure/ami-management) - AMIs (AWS) and GDC images
- [Guacamole](platform_infrastructure/guacamole) - Terminal infrastructure
- [Manual Deployment](platform_infrastructure/manual-deployment) - Manual setup steps

## Development

- [Development Overview](dev/) - Getting started with development
- [Local Setup](dev/local-setup) - Local environment
- [Full Setup](dev/setup) - Complete environment setup
- [Terraform](dev/terraform) - Infrastructure patterns
- [CI/CD](dev/ci-cd) - Pipeline configuration
- [Secrets](dev/secrets) - Secrets management
- [Cloud Adapters](dev/cloud-adapters) - Cloud abstraction layer
- [Principles](dev/principles) - Engineering philosophy
- [ADR Enforcement](dev/adr-enforcement) - Architecture guardrails and policy checks

## Planning & Notes

Internal planning documents and development notes.

- [Plans](plans/) - Implementation plans
- [Notes](notes/) - Development notes
