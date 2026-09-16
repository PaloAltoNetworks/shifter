# AWS Portal First-Image Ordering (#1030)

Status: decision record — documented, not fixed (retained rollback path)

Date: 2026-07-31

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1030>

This is a requirement-free decision record. It documents a first-deploy
ordering hazard in the retained AWS EC2/ASG portal path, why the active EKS
path does not have it, and why #1030 is closed as a documented rollback-path
caveat rather than a code change.

## The hazard

On a fresh AWS account, the first portal ASG instances can fail to bootstrap
because they try to pull a portal image tag that does not exist in ECR yet:

- The portal `image-tag` Parameter Store value is created by Terraform from
  `initial_image_tag`, which defaults to `latest`
  (`platform/terraform/modules/portal/ssm/variables.tf`), and the environment
  `ssm` module invocation does not override it.
- The ASG is created with `wait_for_capacity_timeout = "0"`
  (`platform/terraform/modules/portal/ec2/main.tf`), so instances boot as soon
  as the launch template exists, before the release workflow has built and
  published a real portal image.
- `user_data.sh` reads the `image-tag`/`image-digest` parameters once at boot
  and runs `docker pull`. On a fresh account there is no `latest` image, so the
  pull fails with `manifest unknown`, the `ERR` trap completes the launch
  lifecycle action as `ABANDON` (`platform/terraform/modules/portal/ec2/user_data.sh`),
  and the ASG relaunches into the same failure.
- The final deploy step then triggers an instance refresh that waits for
  existing ASG targets to become healthy. Because the bootstrap-failed
  instances have no container listening on port 8000, the refresh cannot make
  progress until a real image is seeded across the fleet by hand (SSM).

This was observed during the proof-tenant first standup on 2026-06-16 (see the
issue for the exact cloud-init evidence).

## Why this is a rollback-path caveat and not a fix

The AWS portal deploy has moved to EKS. The retained EC2/ASG path is kept for
controlled rollback only, and the two paths must not be conflated (ADR-044).

- The legacy ASG portal CI jobs (`plan`, `apply`, `deploy` in
  `.github/workflows/_shifter-platform.yml`) are gated on
  `environment == '__legacy-disabled__'`, so they never run for `dev`, `proof`,
  or `prod`.
- The active portal path is the `eks-deploy` job, which `needs: build` and
  deploys the exact portal image `@sha256` digest produced by that build (it
  renders the just-built `PORTAL_IMAGE_DIGEST` into the bundle inputs). Build
  precedes deploy and the deploy names the exact built digest, so the EKS path
  is digest-first and has no dependency on a pre-existing `latest` tag — the
  first-image ordering hazard cannot occur there.

The hazard therefore only affects the retained ASG path, which today is
reachable through manual/operator fresh-account standups documented in
[`../dev/aws-terraform-apply-order.md`](../dev/aws-terraform-apply-order.md).
Rather than reactivate and re-harden a retired control plane, #1030 is closed
by documenting the hazard and its manual mitigation for that path. See the
operator caveat in that runbook.

## Manual mitigation (retained ASG path only)

When standing up a fresh account through the retained ASG portal path, ensure a
real portal image exists and the release pointers name it before the fleet is
expected to be healthy:

1. Build and push a portal image to the environment's ECR repository.
2. Set the `image-tag` (and, for digest-pinned deploys, `image-digest`)
   parameters under `/shifter/<env>/portal/` to that real image before, or
   promptly after, the first Portal apply — do not rely on the `latest`
   default.
3. If instances have already bootstrap-failed, run the SSM deploy path
   (`scripts/portal-deploy/deploy_portal.sh`) against them, or replace them,
   once the image and pointers exist, before starting the instance refresh.

## Non-goals

- No change to `user_data.sh`, `scripts/portal-deploy/deploy_portal.sh`,
  `scripts/portal_deploy/portal_deploy.py`, the portal `ssm`/`ec2` Terraform
  modules, environment tfvars, or any workflow.
- No `initial_image_tag` change, bootstrap-image, or user_data
  retry/tolerance logic.
- No change to the canonical EKS/Helm path.
- No activation, cutover, or redesign of the legacy ECS/ASG control plane.
