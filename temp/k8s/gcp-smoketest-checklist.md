# GCP Smoke Test Checklist

Use this against the live GCP rollout at `https://shifter.keplerops.com`.

## Credentials

- Email: `bedwards@paloaltonetworks.com`
- Password source: `/home/atomik/src/shifter/.env` via `GCP_BOOTSTRAP_ADMIN_PASSWORD`

## Browser Smoke Test

1. Open `https://shifter.keplerops.com/`
2. Confirm landing page loads over HTTPS
3. Open `https://shifter.keplerops.com/login/`
4. Confirm the page is the Identity Platform FirebaseUI login widget rather than a Django credential post target
5. Log in with the bootstrap operator
6. If prompted, complete email verification and TOTP enrollment
7. Complete the TOTP challenge
8. Confirm redirect to `https://shifter.keplerops.com/mission-control/`
9. Confirm `https://shifter.keplerops.com/admin/` loads for the same session

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
