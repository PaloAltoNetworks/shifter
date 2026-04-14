# GCP Shifter Smoke Test Access

Last updated: 2026-04-11

## Public App

- Base URL: `https://shifter.keplerops.com/`
- Login URL: `https://shifter.keplerops.com/login/`
- Mission Control: `https://shifter.keplerops.com/mission-control/`
- Django admin: `https://shifter.keplerops.com/admin/`

## Auth Model

- Provider: `Identity Platform` with `FirebaseUI`
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

Expected login flow:

1. Open `/login/`
2. Use the FirebaseUI widget to submit the corporate email and bootstrap password
3. If this is the first login, verify the email and enroll TOTP when prompted
4. Complete the TOTP challenge
5. You should land on `/mission-control/`
6. `/admin/` should also be accessible after login

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
- Login shell loads the FirebaseUI widget and hands off auth to Identity Platform in the browser
- Corporate self-registration rejects non-`@paloaltonetworks.com` emails
- Verified email + enrolled TOTP are required before the Django session is created
- Authenticated Mission Control loads
- Django admin loads for the bootstrap operator
- `portal-web`, `worker-cms`, `worker-engine`, `worker-mc`, `ctf-scheduler`, `guacd`, and `guacamole-client` are all `Running`
