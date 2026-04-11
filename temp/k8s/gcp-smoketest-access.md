# GCP Shifter Smoke Test Access

Last updated: 2026-04-11

## Public App

- Base URL: `https://shifter.keplerops.com/`
- Login URL: `https://shifter.keplerops.com/login/`
- Mission Control: `https://shifter.keplerops.com/mission-control/`
- Django admin: `https://shifter.keplerops.com/admin/`

## Auth Model

- Provider: `Identity Platform`
- Corporate email restriction: `@paloaltonetworks.com`
- MFA: `TOTP` is required

## Bootstrap Operator

- Email: `bedwards@paloaltonetworks.com`
- Password source:
  - `GCP_BOOTSTRAP_ADMIN_PASSWORD` in `/home/atomik/src/shifter/.env`
  - same value is mirrored into the repo-root `.env` symlink
- Django privileges:
  - `is_staff=True`
  - `is_superuser=True`

## Current TOTP Enrollment

The bootstrap operator has already completed first-time MFA enrollment.

- TOTP enrollment is required; use your authenticator app after first login.
- Issuer: `Shifter`

Generate a current code with Python:

```bash
python3 - <<'PY'
import base64, hashlib, hmac, struct, time
secret = "REPLACE_WITH_AUTH_APP_SECRET"
key = base64.b32decode(secret, casefold=True)
counter = int(time.time() // 30)
msg = struct.pack(">Q", counter)
digest = hmac.new(key, msg, hashlib.sha1).digest()
offset = digest[-1] & 0x0F
code = (struct.unpack(">I", digest[offset:offset+4])[0] & 0x7fffffff) % 1_000_000
print(f"{code:06d}")
PY
```

Expected login flow:

1. Open `/login/`
2. Submit the corporate email and bootstrap password
3. Enter the current TOTP code
4. You should land on `/mission-control/`
5. `/admin/` should also be accessible after login

## Live Deployment Facts

- Public hostname: `shifter.keplerops.com`
- GCP ingress IP: `107.178.250.99`
- GKE managed certificate status at completion: `Active`
- Cloud Armor policy name: `shifter-gcp-dev-edge`

## Cluster Access

Project:

- `prod-rwctxzl6shxk`

GKE cluster:

- name: `shifter-gcp-dev-gke`
- location: `us-central1`

Get GKE credentials:

```bash
gcloud container clusters get-credentials shifter-gcp-dev-gke \
  --location us-central1 \
  --project prod-rwctxzl6shxk
```

Check platform workloads:

```bash
kubectl get pods -n shifter-platform
kubectl get ingress,managedcertificate -n shifter-platform
```

## GDC Workstation Access

The GDC workstation is private-only and uses IAP:

```bash
gcloud compute ssh root@cluster1-abm-ws0-001 \
  --tunnel-through-iap \
  --project prod-rwctxzl6shxk \
  --zone us-central1-a
```

Useful commands on the workstation:

```bash
shifter-gdc-kubectl get nodes
shifter-gdc-kubeconfig
```

## Suggested Smoke Test Targets

- Public landing page returns `200`
- Login form loads and enforces corporate email + MFA flow
- Authenticated Mission Control loads
- Django admin loads for the bootstrap operator
- `portal-web`, `worker-cms`, `worker-engine`, `worker-mc`, `ctf-scheduler`, `guacd`, and `guacamole-client` are all `Running`
