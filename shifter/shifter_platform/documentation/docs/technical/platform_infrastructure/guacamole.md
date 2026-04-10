# Guacamole RDP Integration

Apache Guacamole provides browser-based RDP access to range instances (Kali Linux and Windows).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Platform Network                               │
│  ┌───────────┐    ┌────────────────┐    ┌─────────────────────────────────┐ │
│  │           │    │                │    │      Guacamole Services         │ │
│  │   Load    │    │    Portal      │    │  ┌───────────────────────────┐  │ │
│  │  Balancer │───▶│    Django      │    │  │  guacamole-client (8080)  │  │ │
│  │           │    │                │    │  │  - JSON Auth Extension    │  │ │
│  │ /guacamole│───▶│────────────────│    │  │  - OIDC Extension         │  │ │
│  │    path   │    │                │    │  └───────────┬───────────────┘  │ │
│  └───────────┘    └────────────────┘    │              │ port 4822        │ │
│       │                  │              │  ┌───────────▼───────────────┐  │ │
│       │                  │              │  │     guacd (4822)          │  │ │
│       │                  │              │  │  - Protocol translation   │  │ │
│       │                  │              │  │  - RDP/VNC/SSH client     │  │ │
│       │                  │              │  └───────────┬───────────────┘  │ │
│       │                  │              └──────────────┼──────────────────┘ │
│       │                  │                             │                    │
│       │                  ▼                             │                    │
│       │        ┌─────────────────┐                     │                    │
│       │        │  Secret Store   │                     │                    │
│       │        │ - JSON_SECRET   │                     │                    │
│       │        │ - DB_CREDS      │                     │                    │
│       │        └─────────────────┘                     │                    │
│       │                                                │                    │
│       │        ┌─────────────────┐                     │                    │
│       │        │   PostgreSQL    │◀───────────────────▶│                    │
│       │        │ (session state) │                     │                    │
│       │        └─────────────────┘                     │                    │
└───────│────────────────────────────────────────────────│────────────────────┘
        │                                                │
        │                   Network Peering              │
        │                                                │
┌───────│────────────────────────────────────────────────│────────────────────┐
│       │                   Range Network                │                    │
│       │                                                ▼                    │
│       │     ┌──────────────────────────────────────────────────────┐       │
│       │     │              Range Subnet                            │       │
│       │     │  ┌────────────────────┐   ┌────────────────────┐     │       │
│       │     │  │ Kali/Windows       │   │ Victim (Win/Linux) │     │       │
│       │     │  │ - RDP: 3389        │   │ - RDP: 3389        │     │       │
│       │     │  │ - SSH: 22          │   │ - SSH: 22          │     │       │
│       │     │  └────────────────────┘   └────────────────────┘     │       │
│       │     └──────────────────────────────────────────────────────┘       │
└───────│────────────────────────────────────────────────────────────────────┘
        │
        ▼
   [ User Browser ]
```

On AWS, Guacamole runs as ECS Fargate services with an RDS PostgreSQL backend. On GCP, it runs as Kubernetes deployments with Cloud SQL. The Django integration and JSON Auth flow are identical on both clouds.

## Components

| Component | Location | Purpose |
|-----------|----------|---------|
| **guacamole-client** | Container service (ECS on AWS, K8s pod on GCP) | Web application serving HTML5 interface |
| **guacd** | Container service (ECS on AWS, K8s pod on GCP) | Protocol proxy (translates Guacamole protocol to RDP) |
| **PostgreSQL** | Managed database (RDS on AWS, Cloud SQL on GCP) | Session state and connection history |
| **JSON Auth Extension** | guacamole-client | Enables on-the-fly RDP connections via signed URLs |
| **OIDC Extension** | guacamole-client | Identity provider authentication for direct access |

## Network Traffic Flow

### ALB Routing

The Portal ALB routes based on path pattern:

| Path Pattern | Target | Port |
|--------------|--------|------|
| `/guacamole/*`, `/guacamole` | guacamole-client containers | 8080 |
| `/*` (default) | Portal Django | 443 |

Configuration: [alb.tf](../../../platform/terraform/modules/guacamole/alb.tf)

### Security Groups

```
Portal ALB ──────────────────▶ guacamole-client SG
   (any)                           (8080/tcp)
                                       │
                                       ▼
guacamole-client SG ────────────▶ guacd SG
   (egress 4822)                   (4822/tcp)
                                       │
guacd SG ──────────────────────▶ Range VPC CIDR
   (egress 3389, 22, 5900-5910)    (RDP, SSH, VNC)
                                       │
Range Instance SGs ◀───────────────────┘
   - kali_rdp_from_portal (3389/tcp from Portal VPC CIDR)
   - victim_rdp_from_portal (3389/tcp from Portal VPC CIDR)
```

### VPC Peering

Portal VPC ↔ Range VPC peering enables guacd (in Portal VPC) to reach range instances (in Range VPC) on their private IPs.

Routes:
- Portal private subnets → Range VPC CIDR via peering
- Range private subnets → Portal VPC CIDR via peering

---

## Django Integration (JSON Auth)

The Portal Django application generates signed Guacamole URLs for RDP connections without pre-configuring connections in the database.

### Flow Diagram

```
┌────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│   User     │    │  Portal Django   │    │  guacamole-client   │
│  Browser   │    │  (views.py)      │    │  (JSON Auth Ext)    │
└─────┬──────┘    └────────┬─────────┘    └──────────┬──────────┘
      │                    │                         │
      │ 1. Click RDP btn   │                         │
      │ POST /api/guacamole/rdp-url/                 │
      │ {instance_type: "kali"}                      │
      │───────────────────▶│                         │
      │                    │                         │
      │                    │ 2. Validate user's range│
      │                    │    Get instance IP      │
      │                    │    Get secret from env  │
      │                    │                         │
      │                    │ 3. Create JSON payload  │
      │                    │    Sign with HMAC-SHA256│
      │                    │    Encrypt with AES-128 │
      │                    │    Base64 encode        │
      │                    │                         │
      │ 4. Return URL      │                         │
      │ {url: "/guacamole/?data=..."}                │
      │◀───────────────────│                         │
      │                    │                         │
      │ 5. Open new tab    │                         │
      │ GET /guacamole/?data=<encrypted>             │
      │─────────────────────────────────────────────▶│
      │                    │                         │
      │                    │         6. Decrypt data │
      │                    │            Verify HMAC  │
      │                    │            Check expiry │
      │                    │            Create session
      │                    │                         │
      │ 7. Redirect to RDP client                    │
      │◀─────────────────────────────────────────────│
      │                    │                         │
      │ 8. WebSocket ──────────────▶ guacd ─────────▶ Range Instance
      │    (Guacamole protocol)       (RDP protocol)   (3389/tcp)
```

### Data Field Definitions

#### 1. RDP URL Request (Frontend → Django)

```json
{
  "instance_type": "kali"   // "kali" | "victim"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `instance_type` | string | Target instance: `"kali"` (attacker) or `"victim"` |

#### 2. RDP URL Response (Django → Frontend)

```json
{
  "url": "/guacamole/?data=<base64_encrypted_payload>"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Signed Guacamole URL with encrypted `data` parameter |

#### 3. JSON Auth Payload (Encrypted in `data` parameter)

```json
{
  "username": "user@example.com",
  "expires": 1704067200000,
  "connections": {
    "kali-42": {
      "protocol": "rdp",
      "parameters": {
        "hostname": "10.1.5.10",
        "port": "3389",
        "ignore-cert": "true",
        "security": "any",
        "resize-method": "display-update",
        "enable-font-smoothing": "true"
      }
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `username` | string | User's email (from Django session) |
| `expires` | integer | Expiration timestamp in milliseconds (Unix epoch) |
| `connections` | object | Map of connection_name → connection_definition |
| `connections.*.protocol` | string | Always `"rdp"` for RDP connections |
| `connections.*.parameters.hostname` | string | Range instance private IP |
| `connections.*.parameters.port` | string | RDP port (always `"3389"`) |
| `connections.*.parameters.ignore-cert` | string | Skip certificate validation (`"true"`) |
| `connections.*.parameters.security` | string | Security mode: `"any"`, `"nla"`, `"tls"`, `"rdp"` |
| `connections.*.parameters.resize-method` | string | Display resize method (`"display-update"`) |
| `connections.*.parameters.enable-font-smoothing` | string | Font smoothing (`"true"`) |

#### 4. Encryption Process

1. **Input**: JSON payload (above)
2. **Secret Key**: 128-bit key (32 hex characters) from `GUACAMOLE_JSON_AUTH_SECRET`
3. **Process**:
   ```
   json_bytes = JSON.stringify(payload)
   signature = HMAC-SHA256(key, json_bytes)
   signed_data = signature || json_bytes
   padded_data = PKCS7_pad(signed_data, 16)
   encrypted = AES-128-CBC(key, IV=0x00*16, padded_data)
   data_param = base64_encode(encrypted)
   ```
4. **Output**: Base64-encoded encrypted blob for URL `data` parameter

---

## Detailed Sequence: RDP Button Click to Session

```
┌──────────┐     ┌─────────────┐     ┌───────────────┐     ┌────────────────┐     ┌─────────┐     ┌────────────┐
│  Browser │     │terminal.html│     │ views.py      │     │ guacamole.py   │     │ guacd   │     │ Range Host │
│  (User)  │     │ (Frontend)  │     │ (Django API)  │     │ (Crypto Utils) │     │         │     │ (RDP 3389) │
└────┬─────┘     └──────┬──────┘     └───────┬───────┘     └───────┬────────┘     └────┬────┘     └─────┬──────┘
     │                  │                    │                     │                   │                │
     │ Click RDP button │                    │                     │                   │                │
     │─────────────────▶│                    │                     │                   │                │
     │                  │                    │                     │                   │                │
     │                  │ POST /api/guacamole/rdp-url/             │                   │                │
     │                  │ {instance_type: "kali"}                  │                   │                │
     │                  │ X-CSRFToken: <token>                     │                   │                │
     │                  │───────────────────▶│                     │                   │                │
     │                  │                    │                     │                   │                │
     │                  │                    │ Validate:           │                   │                │
     │                  │                    │ - User authenticated│                   │                │
     │                  │                    │ - Range status=READY│                   │                │
     │                  │                    │ - instance_type valid                   │                │
     │                  │                    │                     │                   │                │
     │                  │                    │ Get from Range:     │                   │                │
     │                  │                    │ - attacker_instance │                   │                │
     │                  │                    │   .private_ip       │                   │                │
     │                  │                    │   .os_type          │                   │                │
     │                  │                    │                     │                   │                │
     │                  │                    │ Get from settings:  │                   │                │
     │                  │                    │ - GUACAMOLE_JSON_AUTH_SECRET            │                │
     │                  │                    │ - GUACAMOLE_BASE_URL│                   │                │
     │                  │                    │                     │                   │                │
     │                  │                    │ create_guacamole_rdp_url()              │                │
     │                  │                    │────────────────────▶│                   │                │
     │                  │                    │                     │                   │                │
     │                  │                    │                     │ Build payload:    │                │
     │                  │                    │                     │ - username (email)│                │
     │                  │                    │                     │ - expires (+5min) │                │
     │                  │                    │                     │ - connections{}   │                │
     │                  │                    │                     │                   │                │
     │                  │                    │                     │ sign_and_encrypt: │                │
     │                  │                    │                     │ - HMAC-SHA256     │                │
     │                  │                    │                     │ - AES-128-CBC     │                │
     │                  │                    │                     │ - Base64 encode   │                │
     │                  │                    │                     │                   │                │
     │                  │                    │ url = /guacamole/?data=<b64>            │                │
     │                  │                    │◀───────────────────│                   │                │
     │                  │                    │                     │                   │                │
     │                  │ 200 OK {url: "..."} │                     │                   │                │
     │                  │◀───────────────────│                     │                   │                │
     │                  │                    │                     │                   │                │
     │                  │ window.open(url, '_blank')               │                   │                │
     │                  │─────────────────────────────────────────▶│                   │                │
     │                  │                    │                     │                   │                │
     │◀─────────────────────────────────────── New Tab Opens ──────▶                   │                │
     │                  │                    │                     │                   │                │
     │                  │        GET /guacamole/?data=<b64>        │                   │                │
     │                  │        (ALB routes to guacamole-client)  │                   │                │
     │ ────────────────────────────────────────────────────────────▶ (guacamole-client)│                │
     │                  │                    │                     │                   │                │
     │                  │                    │       JSON Auth Extension:              │                │
     │                  │                    │       - Base64 decode                   │                │
     │                  │                    │       - AES decrypt                     │                │
     │                  │                    │       - HMAC verify                     │                │
     │                  │                    │       - Check expiry                    │                │
     │                  │                    │       - Create session                  │                │
     │                  │                    │                     │                   │                │
     │◀──────────────────────────────────────────────────────────── Redirect to client │                │
     │                  │                    │                     │                   │                │
     │ WebSocket: /guacamole/websocket-tunnel                      │                   │                │
     │ ═══════════════════════════════════════════════════════════▶│                   │                │
     │                  │                    │                     │                   │                │
     │                  │                    │                     │ Guacamole Proto   │                │
     │                  │                    │                     │══════════════════▶│                │
     │                  │                    │                     │                   │                │
     │                  │                    │                     │                   │ RDP Connect    │
     │                  │                    │                     │                   │ 10.1.X.10:3389 │
     │                  │                    │                     │                   │═══════════════▶│
     │                  │                    │                     │                   │                │
     │◀══════════════════════════ RDP Session Established ════════════════════════════════════════════▶│
     │                  │                    │                     │                   │                │
```

---

## Code References

### Django Application Layer

| File | Purpose |
|------|---------|
| [guacamole.py](../../../shifter_platform/mission_control/guacamole.py) | Crypto utilities for JSON auth signing/encryption |
| [views.py:258-343](../../../shifter_platform/mission_control/views.py#L258-L343) | `guacamole_rdp_url()` API endpoint |
| [urls.py:40](../../../shifter_platform/mission_control/urls.py#L40) | URL routing for RDP API |
| [settings.py:307-314](../../../shifter_platform/config/settings.py#L307-L314) | `GUACAMOLE_JSON_AUTH_SECRET`, `GUACAMOLE_BASE_URL` settings |

### Frontend

| File | Purpose |
|------|---------|
| [terminal.html:34-43](../../../shifter_platform/templates/mission_control/terminal.html#L34-L43) | RDP button (Kali pane) |
| [terminal.html:60-69](../../../shifter_platform/templates/mission_control/terminal.html#L60-L69) | RDP button (Victim pane) |
| [terminal.html:113-149](../../../shifter_platform/templates/mission_control/terminal.html#L113-L149) | RDP button click handler |
| [terminal.css:101-156](../../../shifter_platform/static/css/terminal.css#L101-L156) | Button styling |

### Infrastructure (AWS)

| File | Purpose |
|------|---------|
| `platform/terraform/modules/guacamole/main.tf` | ECS cluster, CloudWatch logs, service discovery |
| `platform/terraform/modules/guacamole/ecs.tf` | Task definitions, services, auto-scaling |
| `platform/terraform/modules/guacamole/rds.tf` | PostgreSQL database, JSON auth secret |
| `platform/terraform/modules/guacamole/security.tf` | Security groups |
| `platform/terraform/modules/guacamole/alb.tf` | Target group, listener rule |
| `platform/terraform/modules/range/vpc/main.tf` | Range SG rules for RDP ingress |

### Infrastructure (GCP)

| File | Purpose |
|------|---------|
| `platform/k8s/gcp/base/guacd-deployment.yaml` | guacd K8s deployment |
| `platform/k8s/gcp/base/guacamole-client-deployment.yaml` | guacamole-client K8s deployment |
| `platform/terraform/gcp/modules/platform-core/main.tf` | Cloud SQL (shared), Secret Manager |

### Docker

| File | Purpose |
|------|---------|
| [engine/guacamole/Dockerfile](../../../engine/guacamole/Dockerfile) | Custom guacamole-client image with extensions |

---

## Configuration

### Environment Variables

#### guacamole-client Container

| Variable | Source | Description |
|----------|--------|-------------|
| `GUACD_HOSTNAME` | Hardcoded | Service discovery hostname for guacd |
| `GUACD_PORT` | Hardcoded | `4822` |
| `POSTGRESQL_HOSTNAME` | Terraform | Database instance address (RDS or Cloud SQL) |
| `POSTGRESQL_PORT` | Terraform | `5432` |
| `POSTGRESQL_DATABASE` | Hardcoded | `guacamole` |
| `POSTGRESQL_AUTO_CREATE_ACCOUNTS` | Hardcoded | `true` |
| `POSTGRESQL_USER` | Secret store | From `db_credentials` secret |
| `POSTGRESQL_PASSWORD` | Secret store | From `db_credentials` secret |
| `JSON_SECRET_KEY` | Secret store | 128-bit hex key for JSON auth |
| `OPENID_*` | Terraform | OIDC configuration (when enabled) |

#### Portal Django

| Variable | Source | Description |
|----------|--------|-------------|
| `GUACAMOLE_JSON_AUTH_SECRET` | Secret store | Must match `JSON_SECRET_KEY` above |
| `GUACAMOLE_BASE_URL` | Environment | Default: `/guacamole` |

---

## Secrets

| Secret Name Pattern | Purpose |
|---------------------|---------|
| `shifter-{env}-guacamole-db` | PostgreSQL credentials |
| `shifter-{env}-guacamole-json-auth` | JSON auth 128-bit key |

Stored in AWS Secrets Manager or GCP Secret Manager depending on the deployment target.

**Important**: The JSON auth secret must be wired to the Portal Django application deployment to set `GUACAMOLE_JSON_AUTH_SECRET` environment variable.

---

## Deployment Notes

### Secret Key Sync

The JSON auth secret must be identical in:
1. **guacamole-client container** (injected from secret store)
2. **Portal Django** (set as `GUACAMOLE_JSON_AUTH_SECRET` env var)

If these don't match, URL signatures will fail validation.

### RDP Button Visibility

The RDP button only appears for instances with GUI support:
- `os_type == "kali"` - Kali Linux (XFCE desktop)
- `os_type == "windows"` - Windows Server

Ubuntu instances (`os_type == "ubuntu"`) have no GUI, so no RDP button.

### Session Stickiness

The Guacamole target group has session stickiness enabled (24-hour cookie) to ensure WebSocket connections stay on the same guacamole-client task for the duration of an RDP session.

---

## Troubleshooting

### Common Issues

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| "Failed to generate RDP URL" | `GUACAMOLE_JSON_AUTH_SECRET` not set | Verify Django env var from Secrets Manager |
| "RDP not available for {os} instances" | Instance has no GUI | Expected for Ubuntu; check os_type in range_config |
| "No active range available" | User has no READY range | Must launch range first |
| Connection timeout in Guacamole | Security group missing | Verify `kali_rdp_from_portal` / `victim_rdp_from_portal` rules |
| "Invalid signature" in Guacamole logs | Secret key mismatch | Ensure identical keys in Guacamole and Django |
| "Token expired" | URL used after 5 minutes | Generate new URL (click RDP button again) |

### Log Locations

| Component | Log Group |
|-----------|-----------|
| guacd | `/ecs/{name_prefix}-guacd` |
| guacamole-client | `/ecs/{name_prefix}-guacamole-client` |
| RDS (PostgreSQL) | `/aws/rds/instance/{name_prefix}-guacamole-db/postgresql` |
| Portal Django | Application logs |
