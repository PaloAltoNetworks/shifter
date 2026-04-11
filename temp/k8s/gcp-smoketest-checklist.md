# GCP Smoke Test Checklist

Use this against the live GCP rollout at `https://shifter.keplerops.com`.

## Credentials

- Email: `bedwards@paloaltonetworks.com`
- Password source: `/home/atomik/src/shifter/.env` via `GCP_BOOTSTRAP_ADMIN_PASSWORD`
- TOTP enrollment is required; use your authenticator app after first login.

## Quick TOTP Code

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

## Browser Smoke Test

1. Open `https://shifter.keplerops.com/`
2. Confirm landing page loads over HTTPS
3. Open `https://shifter.keplerops.com/login/`
4. Log in with the bootstrap operator
5. Complete the TOTP challenge
6. Confirm redirect to `https://shifter.keplerops.com/mission-control/`
7. Confirm `https://shifter.keplerops.com/admin/` loads for the same session

## Cluster Smoke Test

```bash
gcloud container clusters get-credentials shifter-gcp-dev-gke \
  --location us-central1 \
  --project prod-rwctxzl6shxk

kubectl get pods -n shifter-platform
kubectl get ingress,managedcertificate -n shifter-platform
```

Expected:
- all `shifter-platform` pods `Running`
- `platform-managed-cert` is `Active`
- ingress address is `107.178.250.99`

## GDC Access

```bash
gcloud compute ssh root@cluster1-abm-ws0-001 \
  --tunnel-through-iap \
  --project prod-rwctxzl6shxk \
  --zone us-central1-a
```

Then:

```bash
shifter-gdc-kubectl get nodes
shifter-gdc-kubeconfig
```
