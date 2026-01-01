# Shifter Platform

Django application architecture for the Shifter cyber range platform.

## Domains

Four bounded contexts, each a Django app with distinct responsibilities.

```mermaid
graph TB
    subgraph Presentation
        MC[Mission Control]
    end

    subgraph Services
        MC --> CMS_SVC[cms.services]
        MC --> ENG_SVC[engine.services]
        MC --> MGT_SVC[management.services]
    end

    subgraph Domains
        CMS_SVC --> CMS[CMS]
        ENG_SVC --> ENG[Engine]
        MGT_SVC --> MGT[Management]
        ENG --> Redis[(Redis Channels)]
    end
```

| Domain | App | Responsibility |
|--------|-----|----------------|
| **Mission Control** | `mission_control` | Presentation layer. DRF API, Django views, WebSocket consumers. |
| **Shifter Engine** | `engine` | Infrastructure lifecycle. Range provisioning, NGFW operations. |
| **Shifter CMS** | `cms` | User content. Assets, credentials, scenario catalog. |
| **Shifter Management** | `management` | Platform administration. Audit logging, user management. |

## Model Ownership

| Domain | Models |
|--------|--------|
| **CMS** | `Asset`, `FileAsset`, `Credential`, `AgentConfig`, `SCMCredential`, `NGFWDeploymentProfile`, `OperatingSystem` |
| **Engine** | `Range`, `UserNGFW` |
| **Management** | `UserProfile`, `ActivityLog` |

## Service Layer

Domains expose Python service interfaces. No HTTP between apps.

```mermaid
graph LR
    Views[MC Views/API] --> CMS[cms.services]
    Views --> ENG[engine.services]
    CMS --> CMS_Models[(CMS Models)]
    ENG --> ENG_Models[(Engine Models)]
```

Mission Control imports and calls domain services:

```python
from cms.services import create_agent, get_storage_used
from engine.services import launch_range, destroy_range
```

Services own business logic. Views handle HTTP concerns only.

## Status Updates

Engine publishes status changes to Redis Channels. Mission Control subscribes via WebSocket consumers and pushes to browser.

```mermaid
sequenceDiagram
    participant P as Provisioner
    participant R as Redis
    participant MC as MC Consumer
    participant B as Browser

    P->>R: publish range.{id}.status
    R->>MC: range_status_update
    MC->>B: WebSocket message
```

Channel naming:
- `range.{range_id}.status` - range lifecycle updates
- `ngfw.{ngfw_id}.status` - NGFW lifecycle updates

## Domain Relationships

CMS defines *what* users can build. Engine defines *how* it runs.

```
CMS::AgentConfig ──referenced by──▶ Engine::Range
CMS::SCMCredential ──referenced by──▶ Engine::UserNGFW
CMS::NGFWDeploymentProfile ──referenced by──▶ Engine::UserNGFW
```

Foreign keys across domains are allowed. Referential integrity via database. Business logic via service calls.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Inter-domain communication | Python service calls | Same process, no serialization overhead. HTTP only at edge. |
| Cross-domain foreign keys | Allowed | Pragmatic Django. DB integrity without microservices complexity. |
| Status delivery | Redis pub/sub | Eliminates DB polling. Real-time updates to browser. |
| API location | Mission Control only | Single HTTP surface. Domains expose services, not endpoints. |
