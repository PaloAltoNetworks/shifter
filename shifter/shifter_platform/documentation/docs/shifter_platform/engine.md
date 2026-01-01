# Shifter Engine

Infrastructure lifecycle. Range provisioning, NGFW operations, terminal connections.

## Responsibility

- Range lifecycle (provision, cancel, destroy)
- NGFW lifecycle (provision, deprovision, instance management)
- Subnet allocation
- Scenario configuration
- SSH terminal connections
- ECS task orchestration

## Models

| Model | Purpose |
|-------|---------|
| `Range` | User's cyber range instance with provisioned infrastructure |
| `UserNGFW` | User's VM-Series NGFW instance |

## Service Interface

| Function | Purpose |
|----------|---------|
| `create_range(range_config)` | Provision infrastructure for range |
| `destroy_range(range_id)` | Tear down range infrastructure |
| `cancel_range(range_id)` | Cancel in-progress provisioning |
| `get_range_status(range_id)` | Get current state, progress, instances |
| `connect_terminal(user, range_id, instance_type)` | Get SSH connection to instance |

### Internal Services

Not exposed to MC. Used within Engine.

| Module | Purpose |
|--------|---------|
| `allocation` | Subnet index allocation with row locking |
| `scenarios` | Scenario validation and instance config |
| `serialization` | Range to DTO conversion |
| `ecs` | ECS Fargate task execution* |
| `ssh` | Async SSH connection management* |
| `secrets` | AWS Secrets Manager retrieval* |

*Currently in `mission_control/services/`, to be moved.

## Status Publishing

Engine publishes status updates via Redis Channels.

```python
channel_layer.group_send(
    f"ngfw_{ngfw_id}",
    {
        "type": "ngfw.status.update",
        "status": "active",
        "progress": 100,
        "message": "Provisioning complete",
    }
)
```

Channel groups:
- `range_{range_id}` - range lifecycle updates
- `ngfw_{ngfw_id}` - NGFW lifecycle updates

