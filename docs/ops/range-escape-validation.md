# GCP range escape validation runbook

The escape validation suite proves that the outer boundary of a GCP VM range cell
fails closed before the range is trusted for live fire. A GCP range backend is not
event ready until this validation passes (ADR-030-R5). Run it after a deploy and
before an event.

The suite runs bounded probes from participant context inside the range cell and
attempts the escape paths a participant or agent would try. It is read only: it
never provisions, destroys, or mutates network state, opens a listener, or edits
routes, DNS, or firewalls.

## What it validates

Each check names the exact boundary it probes, so a failure identifies which outer
boundary leaked:

| Boundary code | Expected result | Meaning |
| --- | --- | --- |
| `cross_range_private_ip` | unreachable | a peer range's private IPs are not reachable |
| `cross_range_dns` | no route | platform or cross-range names do not resolve to a useful route |
| `platform_pod_cidr` | unreachable | the platform pod network is not reachable |
| `platform_service_cidr` | unreachable | the platform service network is not reachable |
| `platform_node_ip` | unreachable | platform node IPs are not reachable |
| `platform_portal_private` | unreachable | portal-private endpoints are not reachable |
| `gke_gdc_api` | unreachable | the GKE or GDC API is not reachable |
| `metadata_server` | no useful credentials | the metadata server exposes no useful credentials |
| `internet_egress` | per policy | egress matches the configured ADR-017 policy |
| `management_ingress` | unreachable | a peer range cannot reach this range's management ports |

A reachable metadata server is a failure only when it returns useful credentials.
Internet egress is interpreted through the configured policy, not a fixed rule: an
approved destination is an expected pass, everything else is an expected fail.

## Prerequisites

- One or more provisioned, ready GCP ranges.
- A deployment config file (see below). Run the command from the portal
  management context.
- For a two-or-more-range run, at least one peer range provisioned at the same
  time. The peer range is the negative target for the cross-range and management
  ingress checks.

## Deployment config file

The platform network inventory and the egress policy are deployment facts. Supply
them once per deployment in a JSON file. The platform CIDRs come from the
Terraform outputs of the environment:

```
terraform -chdir=platform/terraform/gcp/environments/gcp-dev output gke_pods_cidr
terraform -chdir=platform/terraform/gcp/environments/gcp-dev output gke_services_cidr
terraform -chdir=platform/terraform/gcp/environments/gcp-dev output gke_nodes_cidr
```

Example `escape-config.json`:

```json
{
  "platform": {
    "pod_cidr": "10.4.0.0/14",
    "service_cidr": "10.8.0.0/20",
    "node_cidr": "10.128.0.0/20",
    "portal_private_endpoints": ["10.128.0.10:5432", "10.128.0.11:6379"],
    "gke_gdc_api_endpoint": "10.128.0.2",
    "private_dns_names": ["kubernetes.default.svc"]
  },
  "egress": {
    "mode": "deny-all",
    "allowed_cidrs": [],
    "canaries": ["198.51.100.10"],
    "allowed_canaries": []
  }
}
```

The `egress.mode` value matches the deployment's `settings.range_egress` policy
(`status-quo`, `deny-all`, `allowlist`, or `none`). The `canaries` are operator
owned targets expected to be unreachable; they prove egress is denied. Configure at
least one canary so the `internet_egress` boundary can be evaluated; without one
that check records a skip and the verdict fails closed. Under `allowlist` mode,
also set `allowed_canaries` to operator-owned, known-live targets that the
sanctioned lane should reach; these are expected to be reachable. The
`allowed_cidrs` list is the declared policy allowlist and is not probed directly,
because a policy range is not proof that any host inside it is live.

## Run against one range

```
python manage.py run_range_escape_validation \
  --request-id <RANGE_REQUEST_ID> \
  --config escape-config.json \
  --output escape-report.json
```

## Run against two or more ranges

Add one `--peer-request-id` per peer range. This enables the multi-range gate,
which fails if the peer checks are skipped:

```
python manage.py run_range_escape_validation \
  --request-id <RANGE_REQUEST_ID> \
  --peer-request-id <PEER_REQUEST_ID> \
  --config escape-config.json \
  --output escape-report.json
```

## Adapters

The probe runs in participant context through an adapter:

- `--adapter native` (default) runs the probe over the participant SSH channel on
  a native range VM.
- `--adapter polaris --container <name>` runs the probe inside a scenario
  participant container on a Docker-host range, using the Polaris reference
  adapter.

## Read the report

The report is a closed, versioned JSON document suitable for a CI or operator
gate. The top-level `verdict` is `passed` only when every required core check
passes, and, for a multi-range run, the peer checks pass rather than skip. Each
entry in `checks` carries the `boundary_code`, `status` (`pass`, `fail`, `skip`,
or `not_applicable`), the expected and observed outcomes, and a bounded
diagnostic. Diagnostics never contain credential material.

The command exits non-zero when the verdict is `failed` and lists the leaked
boundaries, so a CI or operator gate can block a range that leaks.

## Soundness and limitations

The suite is built so it cannot mistake "I could not test" for "the boundary is
closed":

- Every run includes a positive control (the participant reaching a known-live
  target). If the control does not pass, the probe environment is untrustworthy
  and the whole run fails closed rather than reporting a false pass.
- A missing tool or a probe that cannot run is recorded as an error and fails the
  gate; it is never counted as a secure block.
- A silent drop (timeout) is the only secure result for a should-be-unreachable
  boundary. A connection reset means the network path reached the host, so it
  fails the boundary even though the port was closed.
- Each network boundary is sampled across several addresses and ports rather than
  one endpoint, and cross-range DNS is checked against peer-owned names.
- The guest SSH host key from provisioning state is pinned, so an impostor server
  cannot return a forged all-secure result. A guest with no recorded host key
  fails the launch.

Known limitation: datagram (UDP) reachability beyond DNS name resolution is not
probed. Enforce UDP egress and cross-range UDP isolation with firewall policy and
verify it separately; the suite does not currently assert it.

## Catch a misconfigured firewall before deploy

The static plan-leak checker
(`shifter/engine/provisioner/gcp_range_cell_escape_checks.py`) inspects a rendered
range-cell plan for a cross-range or over-broad allow rule and reports the exact
leaked boundary without any cloud call. It runs in the provisioner test suite and
catches an intentionally misconfigured cross-range allow rule in a fixture.

## Related

- Design and boundary model: `docs/architecture/gcp-range-escape-validation-preflight-1347.md`
- Boundary controls: `docs/architecture/gcp-range-cell-boundary-controls-preflight-1345.md`
- Egress policy: ADR-017
