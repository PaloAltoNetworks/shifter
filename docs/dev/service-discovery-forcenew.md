# Service Discovery ForceNew: Operational Rule

## Observed ForceNew Attribute

The Terraform AWS provider marks `health_check_custom_config.failure_threshold`
inside `aws_service_discovery_service` as a ForceNew attribute. Changing this
field causes Terraform to delete the existing Cloud Map service and create a new
one in its place.

This list is not exhaustive. The ForceNew set is determined by the provider
version in use; a provider upgrade may introduce additional ForceNew attributes
on this resource type.

## Why It Matters

ECS uses Cloud Map to route traffic between services. When ECS tasks are
registered in a Cloud Map service and Terraform attempts to delete that service,
the AWS API rejects the delete with a `ResourceInUse` error. The apply fails
mid-way, leaving infrastructure in a partial state.

## Operational Rule

Any Terraform plan that contains a delete action on
`aws_service_discovery_service` requires ECS task deregistration before the
apply runs:

1. Scale affected ECS services to `desiredCount=0`.
2. Wait for `runningCount` to reach 0.
3. Wait for Cloud Map `list-instances` to return zero instances.
4. Run `terraform apply`.
5. Restore each ECS service to its original `desiredCount`.

Steps 1-3 are the **drain** phase; step 5 is the **restore** phase.

## Implementation

`scripts/handle_sd_replacement/handle_sd_replacement.py` automates this:

```bash
# Before terraform apply (drain)
python3 scripts/handle_sd_replacement/handle_sd_replacement.py \
    drain --tf-plan tfplan --tf-outputs-from <terraform-dir>

# After terraform apply (restore)
python3 scripts/handle_sd_replacement/handle_sd_replacement.py \
    restore --snapshot sd_replacement_snapshot.json
```

The script reads the saved plan via `terraform show -json`, determines which ECS
services correspond to the affected Cloud Map services using the
`_SD_SUFFIX_TO_OUTPUT_KEY` mapping in the source file, and writes a
`sd_replacement_snapshot.json` with the original desired counts. The restore
step is idempotent: if the snapshot is empty or absent, it exits 0 without
calling AWS.

The deploy pipeline in `.github/workflows/_shifter-platform.yml` runs both
phases automatically around the `terraform apply` step.
