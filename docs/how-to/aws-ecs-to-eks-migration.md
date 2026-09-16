# Migrate an AWS deployment from ECS to EKS

This procedure preserves existing ECS deployments while moving platform
workloads to EKS. It is a controlled traffic cutover, not an in-place Terraform
move.

## Before the maintenance window

1. Back up and verify the database and object-store recovery path.
2. Confirm legacy ECS/ASG roots and the new EKS root use separate remote state
   keys. Do not add imports, moved blocks, or shared ownership.
3. Validate `shifter.yaml` with `backend: aws` and prepare an attested image
   file containing only `repository@sha256:<digest>` values.
4. Apply the environment's `platform/terraform/global/iam` stack, then verify
   the deploy role can manage only the scoped EKS/OIDC resources and can pass
   the bounded `shifter-<env>-eks-*` roles only to EKS.
5. Prepare the EKS input with explicit compatible add-on versions and distinct
   edge-client/provider-API CIDRs. Apply EKS prerequisites without directing
   production traffic to EKS.
6. Verify private placement, every managed add-on `ACTIVE`, effective
   exact-role IRSA (including sibling-role denial), strict NetworkPolicy on
   Deployment and Job pods, fail-closed admission denial,
   certificate/WAF/ALB-source restrictions, restricted chart render, and HTTPS
   health.

## Serialized cutover

There must be exactly one active writer/consumer set for shared queues,
outboxes, schedulers, and reconciliation loops.

1. Enter the maintenance window and stop legacy schedulers, queue consumers,
   outbox drainers, and other writers.
2. Confirm in-flight work is drained or durably recoverable.
3. Deploy EKS and verify health, but keep its consumers paused until the legacy
   set is confirmed stopped.
4. Start the EKS consumer set and verify database, queue, object-store, ECS
   range delivery, and Cognito/OIDC behavior.
5. Switch DNS/load-balancer traffic deliberately. Record the previous target
   and TTL so rollback remains bounded.

Never run legacy and EKS control planes concurrently against shared queues,
outboxes, schedulers, or reconciliation state.

## Rollback

Before irreversible retirement, stop the EKS consumer set, confirm it is
quiescent, restore the previous traffic target, then start the legacy consumer
set. Do not destroy the EKS root as a way to stop workloads, and do not mutate
legacy Terraform state during rollback.

Retire legacy portal roots only after the observation window, recovery
evidence, queue/outbox reconciliation, and operator approval. ECS range task
delivery remains supported and is not part of that retirement.

See [AWS EKS backend bundle](../technical/platform_infrastructure/aws-eks-bundle.md)
for the ownership and security model.
