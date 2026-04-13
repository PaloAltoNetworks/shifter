# GCP Shifter Smoke Test Access

Last updated: 2026-04-11

## Public App

- Base URL: `https://shifter.keplerops.com/`
- Login URL: `https://shifter.keplerops.com/login/`
- Mission Control: `https://shifter.keplerops.com/mission-control/`
- Django admin: `https://shifter.keplerops.com/admin/`

## Auth Model

- Provider: `Identity Platform` with browser-side auth SDK flow
- Corporate email restriction: `@paloaltonetworks.com`
- MFA: `TOTP` is required

## Human Public Auth UAT

- Public corporate auth is a human-UAT check.
- The expected flow is:
  1. Open `/login/`
  2. Use the browser auth shell with a `@paloaltonetworks.com` identity
  3. Complete email verification and TOTP enrollment if prompted
  4. Complete the TOTP challenge
  5. Land on `/mission-control/`

## Agent Authenticated UAT Path

Use the localhost-only admin path for agent-run Mission Control, API, and range
coverage:

```bash
gcloud container clusters get-credentials shifter-gcp-dev-gke \
  --location us-central1 \
  --project prod-rwctxzl6shxk

kubectl port-forward -n shifter-platform svc/portal-web 18080:8000
```

Then use:

- URL: `http://localhost:18080/dev-login/`
- Email: `uat-admin@example.com`
- User type: `admin`

Expected result:

- `http://localhost:18080/mission-control/` returns `200`
- `http://localhost:18080/admin/` returns `200`

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
- Login shell loads and hands off auth to Identity Platform in the browser
- Corporate self-registration rejects non-`@paloaltonetworks.com` emails
- Human public auth reaches Mission Control after verification and TOTP
- Localhost admin path reaches Mission Control and Django admin
- `portal-web`, `worker-cms`, `worker-engine`, `worker-mc`, `ctf-scheduler`, `guacd`, and `guacamole-client` are all `Running`
