# Shifter Engine

Infrastructure lifecycle. Range provisioning, NGFW operations, terminal connections.

## Responsibility

- Range lifecycle (provision, cancel, destroy)
- NGFW lifecycle (provision, deprovision, instance management)
- Subnet allocation
- Scenario configuration
- SSH terminal connections
- Container task orchestration (via cloud adapter)

## Models

| Model | Purpose |
|-------|---------|
| `Request` | Provisioning request container (correlation via UUID) |
| `Range` | User's cyber range with lifecycle status and timestamps |
| `Instance` | Materialized VM instance with Pulumi/Terraform state |
| `App` | Materialized app (NGFW, etc.) with infrastructure state |
| `Subnet` | Allocated subnet with CIDR and routing configuration |

## Service Interface

### Range Operations

| Function | Purpose |
|----------|---------|
| `create_range(request_spec)` | Start provisioning from RequestSpec |
| `destroy_range_by_request(request_id)` | Destroy range by request UUID |
| `cancel_range_by_request(request_id)` | Cancel in-progress provisioning |
| `get_range_status(range_id)` | Get status, instances, progress |
| `pause_range(range_id)` | Pause range instances |
| `resume_range(range_id)` | Resume range instances |

### Terminal Operations

| Function | Purpose |
|----------|---------|
| `connect_terminal(user, instance_uuid)` | Get SSH connection to instance |
| `get_rdp_connection_info(user, instance_uuid)` | Get Guacamole RDP connection |

### NGFW Operations

| Function | Purpose |
|----------|---------|
| `create_ngfw(request_spec)` | Start NGFW provisioning |
| `destroy_ngfw(request_id)` | Destroy NGFW |
| `start_ngfw(request_id)` | Start stopped NGFW |
| `stop_ngfw(request_id)` | Stop running NGFW |
| `complete_ngfw_setup(request_id)` | Mark NGFW setup as complete |

### Internal Services

Not exposed to MC. Used within Engine.

| Module | Purpose |
|--------|---------|
| `allocation` | Subnet index allocation with row locking |
| `scenarios` | Scenario validation and instance config |
| `serialization` | Range to DTO conversion |
| `ecs` | Container task execution (uses cloud adapter internally) |
| `ssh` | Async SSH connection management |
| `secrets` | Secret retrieval (uses cloud adapter internally) |

## Event Handling

Engine receives events from the Provisioner via the message bus (SNS/SQS on AWS, Pub/Sub on GCP). The `engine/handlers.py` module processes these events:

```python
def process_range_event(message):
    """Update Range model from provisioner events."""
    # range.status.updated -> update Range.status, timestamps
    # range.provisioned -> audit log (state written directly by provisioner)
```

Engine handlers update Engine models only. Mission Control handlers (not Engine) broadcast to WebSocket clients.

See [Shifter Platform](.) for the full event flow diagram.

## Range warm pool (#28, ADR-039-R11)

The warm pool keeps system-owned, pre-provisioned range generations that an initial
launch can atomically claim, reducing cold-start latency without bypassing capacity,
tenancy, or lifecycle controls. Its architecture is fixed by
`docs/architecture/range-warm-pool-preflight-28.md` and the optional
`range-warm-activation/v1` capability in `docs/architecture/provider-neutral-range-substrate.md`.

Key seams:

- **Ledger (claim authority).** `engine.models.WarmRangeGeneration` is the row-plus-
  constraint claim authority. Its state (`provisioning`, `ready`, `claimed`,
  `unhealthy`, `retiring`, `terminal`) is *private* allocation state, deliberately
  distinct from `Range.Status`: a warm-prepared range may be Engine-`READY` while the
  pool treats it as claimable only when the ledger row is `ready`.
- **Atomic claim.** `engine.services.claim_ready_generation` transitions one ready,
  exact-`compatibility_digest` generation to `claimed` under
  `select_for_update(skip_locked=True)`, giving one-winner semantics, with a partial-unique
  `claimed_by_request_id` constraint as the database backstop. The CMS launch path
  wraps the claim with the ownership rehome and commits before enqueuing activation.
- **Compatibility.** `shared.warm_pool.compatibility` computes the canonical digest
  (registered package + lock digest + admitted placement/posture) that both the
  reconciler and the launch claim compare. Warm eligibility is RAES-native only (the
  ownership-neutral `operation_input`); legacy `user_id`-bearing intent is cold-only.
- **Activation.** The provisioner `raes-range activate` operation scrubs every
  pre-claim credential/VPN/access identity, realizes the claimant's fresh access, and
  negatively verifies the prior access is revoked (`shared.warm_pool.activation_input`,
  provisioner `raes_gcp_activate*`). GCE is warm-capable; AWS/GDC report the capability
  unsupported and cold-fall-back.
- **Reconciler.** `cms.services.reconcile_warm_pool` (worker
  `reconcile_warm_pool`) replenishes shortfalls, retires expired/incompatible/excess
  and unhealthy generations through canonical `destroy`, and releases capacity only
  after provider absence is observed. Capacity is drawn through the Engine ledger
  (`engine.services.admit_warm_generation_capacity`); warm ranges are first-class
  capacity consumers.
- **Observability.** `shared.warm_pool.metrics` publishes gauges and claim outcomes
  to the `Shifter/WarmPool` namespace; warm lifecycle events are audited under the
  `warm_*` `AuditAction` vocabulary.
