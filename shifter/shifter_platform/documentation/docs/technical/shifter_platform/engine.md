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
