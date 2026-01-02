# Mission Control

Presentation layer. DRF API, Django views, WebSocket consumers.

## Responsibility

- HTTP endpoints (DRF API, Django views)
- WebSocket consumers (terminal, status updates)
- User authentication context
- Request/response formatting

Mission Control contains no business logic. It validates HTTP input, calls service functions, and formats responses.

## WebSocket Consumers

### SSHConsumer

Terminal access to range instances.

**URL:** `ws/terminal/<range_id>/<instance>/`

**Flow:**
1. Authenticate user from scope
2. Call `engine.connect_terminal(user, range_id, instance_type)`
3. Accept WebSocket
4. Pipe: WebSocket input → SSH, SSH output → WebSocket

**Close codes:**
- `4001` - Unauthenticated
- `4003` - Unauthorized (not owner)
- `4004` - Range not found or not ready
- `4005` - Connection details missing
- `4006` - SSH connection failed
- `4500` - Unexpected error

### RangeStatusConsumer

Real-time range status updates.

**URL:** `ws/range/<range_id>/status/`

**Flow:**
1. Authenticate user, verify ownership
2. Join Redis channel `range_{range_id}`
3. Forward status updates to browser
