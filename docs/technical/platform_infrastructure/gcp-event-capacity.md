# GCP shared-service event capacity contract

Issue #1816 establishes one immutable catalog in
`shifter/installation/capacity_profiles_gcp.py`. A profile ID encodes a version
and participant envelope. The resolver projects that one object into four
consumers:

- Terraform: access-node minimum/maximum, Cloud SQL tier/HA/disk, Redis tier and
  memory, plus the capacity identity label.
- Helm: portal and guacd minimum replicas/resources/HPAs/PDBs, the fixed
  single-replica Guacamole client, process counts, absolute tunnel ceilings,
  WebSocket keepalive, termination grace, backend timeout, and connection drain.
- Gate: concurrency, hold and latency budgets, ready guacd minimums, and
  saturation ceilings.
- Drift: an allowlisted desired-state document compared with live provider and
Kubernetes observations. Missing observations fail closed; raw cloud payloads
and secrets are not emitted. Cloud SQL disk capacity is a minimum because the
provider cannot shrink storage; drift accepts a retained larger disk after
profile scale-down but still rejects an undersized disk.

The installation setting `shared_service_capacity_profile` is the only selector.
Provider, deployment, traffic, and gate profiles remain distinct concepts. GCP
bootstrap merges the Helm projection into ordinary generated values, and the
normal release renderer reapplies that same projection to the Kustomize manifest
before every rollout. This keeps normal deployment ordering authoritative and
prevents a release from retaining the profile identity while silently restoring
static-base workload resources.

The p30 profile provisions five portal replicas, two guacd replicas, one
Guacamole client, regional `db-custom-4-15360` Cloud SQL, 8 GiB Standard HA
Redis, and access-node autoscaling from three to eight nodes. Portal and guacd
HPAs may add headroom, but their minimum replicas are sized to carry the gate
without a scale-up race. The Guacamole client remains one replica to preserve
the token-affinity contract from issue #928.

Database connection accounting is explicit: Django retains its qualified
`CONN_MAX_AGE=0` behavior, the Guacamole/MyBatis active JDBC pool is budgeted at
its fixed ten-connection limit, and the remaining Cloud SQL budget is reserved
for failover and operations. `POSTGRESQL_ABSOLUTE_MAX_CONNECTIONS` is a
Guacamole tunnel-concurrency guard; it is not misrepresented as the JDBC pool.

The strict gate reuses the range functional smoke's Identity Platform/TOTP,
target selection, Guacamole URL parsing, and wire protocol. A successful client
must observe `ready`, acknowledge a post-ready `sync`, and keep parsing the
tunnel for the full hold. Cloud Monitoring supplies restart, CPU, Cloud SQL,
Redis, and external HTTPS load-balancer evidence; bounded `kubectl get` and
`gcloud compute backend-services get-health` reads supply effective readiness
and backend health. No missing signal is converted to zero.

The binding architecture analysis is
[GCP shared-service event capacity preflight](../../architecture/gcp-shared-service-event-capacity-preflight-1816.md).
The operator procedure is [GCP event capacity profiles](../../ops/gcp-event-capacity.md).
