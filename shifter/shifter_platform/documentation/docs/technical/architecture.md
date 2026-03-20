# Shifter Architecture

Enterprise, multi-user, extensible cyber range platform.

## Platform Infrastructure

Two AWS accounts: `dev` and `prod`.

```mermaid
graph TB
    subgraph Platform["Platform Infrastructure"]
        Global["Global<br/>(IAM, OIDC)"]
        Core["Core<br/>(ECR, base resources)"]
        Range["Range<br/>(VPC, networking)"]
    end

    Global --> Core
    Core --> Range
```

| Component | Location | Purpose |
|-----------|----------|---------|
| **Global** | `platform/terraform/global/` | IAM roles, OIDC providers, cross-account resources. |
| **Core** | `platform/terraform/modules/ecr/`, `platform/terraform/environments/` | ECR, base environment resources. |
| **Range** | `platform/terraform/modules/range/` | Range VPC, shared networking foundation. |
| **Portal*** | `platform/terraform/modules/portal/` | Shifter application infrastructure (ALB, ECS, RDS, S3). |

*Portal is a legacy name. This module deploys the Shifter Django application infrastructure.

### Identity

Cognito user pool configured with:
- Email as username
- MFA required (TOTP)
- Pre-signup Lambda for domain restriction (`@paloaltonetworks.com`)
- Email verification required

### Hosting

CI/CD via GitHub Actions with self-hosted runners. DNS hosted on Cloudflare (`dev.shifter.keplerops.com`, `shifter.keplerops.com`).

## Shifter (Django)

Django monorepo. Users interact via Mission Control; backend apps expose service interfaces.

```mermaid
graph TB
    subgraph Shifter["Shifter Platform"]
        MC["Mission Control<br/>(Presentation)"]
        SE["Shifter Engine<br/>(Range Management)"]
        CMS["Shifter CMS<br/>(Content Management)"]
        SA["Shifter Admin<br/>(Platform Management)"]
        CTF["CTF<br/>(Competitions)"]
        RR["Risk Register<br/>(Risk & Audit)"]
    end

    Users((Users)) --> MC
    Users --> CTF

    MC -->|service calls| SE
    MC -->|service calls| CMS
    MC -->|service calls| SA
    CTF -->|service calls| CMS
    SE -.->|references models| CMS
```

| Element | App | Purpose |
|---------|-----|---------|
| **Mission Control** | `mission_control` | Presentation layer. Single UI for all users. |
| **Shifter Engine** | `engine` | Range management. Owns Range lifecycle, references CMS assets. |
| **Shifter CMS** | `cms` | Content management. Assets, credentials, scenario catalog. Also includes `cms.experiments` (script execution) and `cms.scenario_editor` (template authoring). |
| **Shifter Admin** | `management` | Platform management. User profiles, Cognito integration. |
| **CTF** | `ctf` | Capture-the-flag competitions. Events, challenges, teams, scoring, magic-link auth. |
| **Risk Register** | `risk_register` | Risk tracking, API keys, centralized audit logging. |
| **Shared** | `shared` | Cross-cutting utilities: auth helpers, enums, schemas, exceptions. |
| **Documentation** | `documentation` | In-app documentation site. |

### Event-Driven Communication

Provisioner publishes status events to SNS. All domains subscribe via SQS and process events through domain-specific handlers.

```mermaid
sequenceDiagram
    participant P as Provisioner
    participant SNS as SNS
    participant SQS as SQS
    participant ENG as Engine Handlers
    participant CMS as CMS Handlers
    participant MC as MC Handlers
    participant R as Redis Channels
    participant B as Browser

    P->>SNS: publish event
    SNS->>SQS: fanout
    SQS->>ENG: process
    SQS->>CMS: process
    SQS->>MC: process
    ENG->>ENG: update Engine models
    CMS->>CMS: update CMS models
    MC->>R: broadcast
    R->>B: WebSocket push
```

- **Engine handlers**: Update `Range` status, timestamps
- **CMS handlers**: Update `RangeInstance`, `Instance`, `App` status
- **MC handlers**: Broadcast to WebSocket for real-time UI updates

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| UI separation | Mission Control is presentation only | Backend apps expose service interfaces; UI is Django templates. |
| API style | REST via Django REST Framework | Proven, simple, mature Django ecosystem support. |
| Identity | Cognito | AWS-native, supports MFA and domain restriction. |
| Domains | keplerops.com | Current DNS hosting via Cloudflare. |
