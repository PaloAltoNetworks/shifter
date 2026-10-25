# GCP event capacity profiles

Use a versioned shared-service capacity profile before a scheduled GCP event.
The profile is selected once in `shifter.yaml`; the installation renderer then
projects the same identity into Terraform, Helm, the event gate, and drift
inspection. Do not maintain an event-only tfvars or Helm override.

The supported profiles are `gcp-shared-v1-p10`, `gcp-shared-v1-p30`,
`gcp-shared-v1-p50`, `gcp-shared-v1-p100`, `gcp-shared-v1-p200`,
`gcp-shared-v1-p300`, and `gcp-shared-v1-p500`. Every profile carries its own
strict gate budget, and the gate runs at that profile's participant count. Only
p30 has recorded qualification evidence so far. A larger profile is deployable,
but treat it as unqualified until its gate passes and the evidence is recorded.

### Large tiers and the quota they need

The large tiers continue the p50 to p100 growth rates. `guacamole-client` stays
at exactly one replica (#928 token affinity) and every participant's display
stream passes through it, so these tiers give that pod more CPU and memory. Each
SQL connection budget stays within Cloud SQL's default `max_connections` for the
instance memory (1,000 at 120 GB and above), and validation rejects a tier that
exceeds it.

| Profile | Portal pods min/max | guacd pods min/max | Access nodes min/max | guacamole-client CPU/memory limit | OpenVPN servers min/max | Cloud SQL | Redis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| p200 | 26 / 52 | 16 / 32 | 12 / 24 | 4 / 4Gi | 9 / 18 | `db-custom-32-122880`, regional | 32 GB |
| p300 | 38 / 76 | 24 / 48 | 18 / 36 | 6 / 6Gi | 13 / 26 | `db-custom-48-184320`, regional | 48 GB |
| p500 | 62 / 124 | 40 / 80 | 28 / 57 | 8 / 8Gi | 21 / 42 | `db-custom-64-245760`, regional | 80 GB |

Before selecting a large tier, confirm these quotas in the tenant's region and
request increases ahead of the event:

- **Compute Engine CPUs (E2).** Access nodes are `e2-standard-8` and OpenVPN
  servers `e2-standard-2`. At maximum, p200 needs 192 + 36 vCPUs, p300
  288 + 52, and p500 456 + 84. These figures exclude the GKE system and
  provisioner pools and the range VMs, which have their own capacity plan.
- **Cloud SQL.** The tier's machine type must be available in the region, and
  the regional (HA) instance doubles its footprint.
- **Memorystore.** The Redis size above, as a Standard (HA) instance.
- **Vertex AI.** Model quotas (tokens and requests per minute) scale with how
  many participants call models at once; request them separately per model and
  region.

## Preconditions

- The target is a deployed GCP tenant with the real Identity Platform/TOTP,
  range, Guacamole, GKE, Cloud SQL, Memorystore, and external load-balancer
  paths healthy.
- The event range image and example range pass the range functional smoke. This
  keeps the p30 gate compatible with the real GCP range path established by
  issue #1346.
- Thirty distinct participant accounts have a ready RDP target. Do not reuse an
  administrator session or one shared account.
- The operator can read Cloud Monitoring, GKE deployments, and backend-service
  health. The gate makes no provider or cluster mutations.

## Scale up

1. Set the profile in the tenant's installation config:

   ```yaml
   backend: gcp
   settings:
     shared_service_capacity_profile: gcp-shared-v1-p30
   ```

2. Validate and render the generated inputs:

   ```sh
   uv run --project shifter/installation shifter-config validate shifter.yaml
   uv run --project shifter/installation shifter-config render shifter.yaml \
     --output /tmp/shifter-event.auto.tfvars
   uv run --project shifter/installation shifter-config render-capacity shifter.yaml \
     --projection desired-state --output /tmp/shifter-event-capacity.json
   ```

3. Run the normal reviewed GCP deployment workflow with the rendered Terraform
   bridge. The deploy applies the profile's pod counts, resources, autoscaler
   bounds, and Guacamole connection ceiling, so a tier change through CI takes
   full effect. Do not edit a node pool, Deployment, HPA, BackendConfig, Cloud SQL
   instance, or Redis instance by hand. The p30 minimums themselves carry the
   event; autoscaling is supplemental headroom.

4. Wait for Terraform, GKE rollouts, HPAs, BackendConfigs, Cloud SQL, Redis,
   and the OpenVPN pool (when enabled) to stabilize. Guacamole client replicas must remain exactly one; portal and
   guacd are the horizontally scaled workloads.

5. Prove the effective state matches the selected profile:

   ```sh
   uv run python scripts/gcp/check_event_capacity_drift.py \
     --desired /tmp/shifter-event-capacity.json \
     --project <project> --region <region> --cluster <cluster> \
     --sql-instance <sql-instance> --redis-instance <redis-instance> \
     --vpn-pool <vpn-instance-group>
   ```

   Pass `--vpn-pool` with the `openvpn_pool.instance_group` Terraform output when
   participant OpenVPN is enabled; the check then compares the pool's machine
   type, minimum and maximum servers, and CPU target. Without it the pool fields
   are skipped. Exit 0 and `capacity drift: none` are required. Exit 1 is real drift. Exit 2
   means evidence was missing or malformed and is also a stop condition.

## Run the p30 public-path gate

Create a gitignored mode-0600 TOML file with exactly 30 entries. Each entry must
contain the real participant email, password, TOTP seed, and Identity Platform
API key. These values never belong on argv or in the report.

```toml
[[actor]]
email = "participant1@example.invalid"
password = "..."
totp_secret = "..."
api_key = "..."
user_type = "ctf_participant"
```

```sh
chmod 600 actors-p30.toml
cd uat/event-load-harness
uv sync --extra gcp
uv run event-load-harness \
  --target-url https://<tenant-host> --confirm-host <tenant-host> \
  --environment <environment> --profile guacamole-event-gate \
  --capacity-profile-id gcp-shared-v1-p30 \
  --concurrency 30 --ramp-seconds 30 --duration-seconds 120 \
  --actor-source manifest --actor-manifest actors-p30.toml \
  --metric-source gcp --region <region> \
  --gcp-project <project> --gcp-cluster <cluster> \
  --gcp-namespace shifter-platform --gcp-sql-instance <sql-instance> \
  --gcp-redis-instance <redis-instance> --gcp-backend-name <backend-service> \
  --report-path out/p30-envelope.md
```

After the client hold completes, the command waits the catalog-authored 240
seconds for the slowest required Cloud Monitoring series to become visible.
This wait is part of the gate; do not cancel it and substitute dashboard values.

The run passes only when all 30 real logins bootstrap a versioned Guacamole RDP
session, reach display synchronization, and hold continuously for at least 120
seconds. The report must also show p50/p95/p99 bootstrap latency and pass every
authored threshold: zero tunnel drops, relevant pod restarts, Redis evictions
and rejects, Cloud SQL failed connections, load-balancer 5xx/504/no-response
requests, and unhealthy backends; plus bounded guacd CPU, SQL/Redis connection
utilization, and load-balancer p95. Missing telemetry fails the gate.

## Scale down

Scale-down is deliberately separate from event qualification.

1. Preserve the gate report and confirm no active event or long-lived RDP
   sessions depend on the event capacity.
2. Select the normal lower profile in `shifter.yaml` and run the same reviewed
   deployment workflow. Never use `kubectl scale` or provider-console edits.
3. Allow the 300-second load-balancer drain and 330-second pod termination
   window to complete. HPA scale-down stabilization is 900 seconds.
4. Re-render desired state and rerun the drift checker. A clean lower-profile
   drift result is the completion signal. Cloud SQL storage is a non-shrinking
   floor: a disk retained from a larger profile is accepted when it is at least
   the selected profile's minimum; an undersized disk still reports drift.

If scale-up or the gate fails, keep the current profile while investigating.
Rollback means selecting the last known-good profile and deploying it through
the same path; it does not mean deleting resources mid-session.
