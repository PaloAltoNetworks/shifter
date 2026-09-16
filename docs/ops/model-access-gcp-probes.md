# GCP model broker onboarding and qualification probes

Owner: deployment operator with Engine/security owners. Scope: M06 / #2123,
PLAT-202. These instructions produce evidence; their presence is not evidence
that a deployment passed. M10 / #2127 owns the independent runtime result.
Keep the broker disabled until the M05 executable, M07 adapter and M08
admission/enrollment path are available in the attested release image.

## Project and identity onboarding

Use dedicated existing model projects with billing enabled and the
`shifter-deployment` label equal to `deployment.name`. Root
`settings.model_broker.model_projects` is the reviewed project-to-invocation
account inventory. Reject platform/dynamic-secret project reuse. Confirm
regional model availability, quota and organization-policy compatibility
with the approved catalog before enabling a cohort. The deployment operator
needs authority to enable APIs and create the exact GSAs, custom roles and
bindings; the broker does not inherit that operator authority.

After a reviewed Terraform apply, save output in a restricted local directory.
Terraform outputs can include sensitive values: do not print, upload or commit
the complete output. The compatibility renderer compares applied broker
coordinates with root intent before applying workload manifests. Run the
read-only project and effective-IAM probe using the broker GSA from that
readback:

```bash
uv run --project scripts/gcp python scripts/gcp/probe_model_broker.py \
  --config shifter.yaml \
  --broker-gsa '<applied-broker-gsa>' \
  --output model-project-onboarding.json
```

The probe checks ownership, billing, APIs, live invocation identity, absence
of user-managed keys, exact-target token permission and invocation permission.
It requires conclusive denials for management/key/actAs and representative
compute, secret, storage and endpoint-administration permissions. Unknown or
conditional Policy Troubleshooter results fail qualification. The operator
needs permission to inspect effective policy, including inherited policy.
Project-level negatives do not prove absence of resource-specific grants:
M10 must also inventory applicable resource policies and test actual denied
resources. A successful probe never proves regional model availability or
absence of every possible permission. Retain only its bounded result and
reviewed policy inventory, not credentials or raw provider responses.

## Private transport and source preservation

Use the actual deployment project and region, never infer them from an
account name. Resolve the project from the deployment configuration (the
`GCP_PROJECT_ID` for the target environment) and export it, for example
`export GCP_PROJECT=<your-project>`; the region is `us-central1`. Read-only
cluster inspection:

```bash
gcloud container clusters describe shifter-gcp-dev-gke \
  --project "$GCP_PROJECT" --region us-central1 \
  --format='yaml(currentMasterVersion,network,subnetwork,networkConfig.datapathProvider,privateClusterConfig.enablePrivateNodes,workloadIdentityConfig.workloadPool)'
kubectl -n shifter-platform get service model-broker -o yaml
kubectl -n shifter-platform get networkpolicy -o yaml
kubectl -n shifter-platform get endpointslice \
  -l kubernetes.io/service-name=model-broker -o yaml
```

Verify the kubeconfig points at that cluster before probing. Record release
SHA and image digest, GKE/CNI version, internal forwarding rule, LB backend
health and realized firewall targets/source ranges. The forwarding rule must
use the reserved VIP on TCP 443, internal passthrough semantics and the
configured regional/global-access setting. The Service must use
`externalTrafficPolicy: Local`; inspect both nodes hosting replicas. Evaluate
all selecting NetworkPolicies and VPC/hierarchical rules together. Controller
health checks may reach their health-check port; they must not become a
participant management or node-port grant.

On each selected VM, inspect the instance with `gcloud compute instances
describe` and a field-limited format for `canIpForward`, service accounts,
network interfaces and tags. Require `canIpForward=false`, no service account,
no external IP, a current Engine-owned subnet binding and only the expected
range tags. Machine-image inheritance and alternate NICs require actual
readback. Forwarding/VPN hosts and NAT/proxy paths are unqualified.

Run these cases from two independently admitted ranges and one unadmitted
subnet. Use the M05/M08 supported client and a bounded synthetic profile;
never put bearer tokens in shell arguments, history or evidence. Store client
credentials in an operator-approved private file or stdin mechanism. Use
verified TLS with the configured hostname and deployment CA, including when
pinning the VIP for a probe. Never use insecure verification flags.

| Probe | Required observation |
| --- | --- |
| Range A calls broker VIP:443 with its current capability | Verified TLS; Engine admits A; broker socket peer equals A's actual private source and belongs to Engine's current subnet binding. |
| Repeat against both replicas and across a draining rollout | The same source identity survives the actual LB/CNI path; no node/NAT address replaces it. |
| Range B replays A's capability | Rejected before provider dispatch or accounting charge, even with forged `Forwarded` / `X-Forwarded-For` naming A. |
| Unadmitted subnet calls VIP:443 | Network denial; no broker admission. |
| A connects to VIP:80, :8443 or :8444, neighboring VIP, peer range, node/pod management address | Denied; only exact broker VIP:443 is the new capability. |
| Strict `none` range requests broker enrollment | Admission/projection rejected; no NAT or broker egress exception. |
| Broker attempts database, Redis, Kubernetes API or arbitrary internet destination | Denied by effective policy; narrow Engine TLS/DNS/identity/provider paths remain available. |
| TLS hostname mismatch, untrusted/expired certificate or wrong control audience/subject | Rejected with no insecure fallback or paid provider probe. |

Source comparison unit tests cannot replace these observations. Export only
case IDs, safe binding references, pass/fail, timings and release identity.
Do not record tokens, prompts, completions, headers, body hashes or raw error
responses. If the live path does not preserve the peer, leave admission off
and repair the topology; forwarding headers are never an alternative identity.

## Rotation and release

Create separate versioned broker/control TLS Secrets and a versioned CA
ConfigMap through the existing secret-management procedure. Broker SAN is the
configured private hostname; control SAN includes
`model-access-control.shifter-platform.svc`. Never route certificate material
through Terraform or ordinary chart values. Renew before expiry and alert on
renewal failures. Change root Secret references to roll replicas; do not assume
that updating mounted bytes reloads the server TLS context.

For CA replacement, distribute overlapping trust first, roll both servers and
guests, verify new certificates and active streams, then remove old trust
only after old connections and pods drain. Probes must remain independent of
paid providers. Measure bounded drain and revocation with a synthetic stream;
150 seconds of pod grace includes endpoint withdrawal and the design's
120-second request maximum. Missing renewal, source evidence or authorization
service means admission stays disabled. Rollback drains/disables model access
and never restores guest provider credentials.

Attach project/IAM onboarding, safe transport case results, TLS rotation,
revocation/stream evidence and exact release identity to #2127. Operator
approval of those results precedes cohort enablement. See the
[deployment package](../architecture/model-access/gcp-packaging.md) and
[operating design](model-access.md) for ownership and migration boundaries.
