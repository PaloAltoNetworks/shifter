Pass `CLOUD_PROVIDER` to the portal deploy script's migrate and container
runs. `config._cloud.resolve_cloud_provider` (PLAT-2005) made
`CLOUD_PROVIDER` a required setting at import time and wired it into the ASG
boot path (`user_data.sh`) and the engine provisioner task, but not the AWS
deploy path. `deploy_portal.sh` built the migrate and run-container env
without it, so any deploy of the new image aborted at the migrate step with
`CLOUD_PROVIDER environment variable is required`. The deploy now publishes
the backend identity to Parameter Store (`/shifter/<env>/portal/cloud-provider`)
and reads it into the shared container env, matching the boot path. GCP is
unaffected: it injects `CLOUD_PROVIDER` through the rendered `platform-runtime`
ConfigMap.
