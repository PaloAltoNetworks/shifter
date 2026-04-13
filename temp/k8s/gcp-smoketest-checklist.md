# GCP Smoke Test Checklist

Use this against the live GCP rollout at `https://shifter.keplerops.com`.

## Human Public Auth Check

1. Open `https://shifter.keplerops.com/`
2. Confirm landing page loads over HTTPS
3. Open `https://shifter.keplerops.com/login/`
4. Confirm the page is the Identity Platform browser auth shell rather than a Django credential post target
5. Complete sign-in with a real `@paloaltonetworks.com` account
6. If prompted, complete email verification and TOTP enrollment
7. Complete the TOTP challenge
8. Confirm redirect to `https://shifter.keplerops.com/mission-control/`

## Agent Authenticated Check

```bash
gcloud container clusters get-credentials shifter-gcp-dev-gke \
  --location us-central1 \
  --project prod-rwctxzl6shxk

kubectl port-forward -n shifter-platform svc/portal-web 18080:8000
```

Then:

1. Open `http://localhost:18080/dev-login/`
2. Sign in with email `uat-admin@example.com`
3. Select `Admin (Mission Control + Django admin)`
4. Confirm `http://localhost:18080/mission-control/` loads
5. Confirm `http://localhost:18080/admin/` loads

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
