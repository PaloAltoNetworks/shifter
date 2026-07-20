# Range Egress IP Allowlist

Scope: PLAT-220 (#775). Wave-2 platform requirement. This document records the
shape of the configuration surface, the default behavior on each backend, and
the mapping into cloud-native firewall syntax. The preflight artifact for the
implementation is at
[range-egress-ip-allowlist-preflight-775.md](range-egress-ip-allowlist-preflight-775.md).
ADR-017 records the platform-level rules this implementation is bound by.

PLAT-220's refinements (PLAT-221 scenario overrides, PLAT-222 composable sets +
admin UI, PLAT-223 RBAC) are intentionally out of scope here.

Issue #958 closed the renderer gap: `shifter-config render` now generates the
provider Terraform bridge tfvars directly from `shifter.yaml`, so the operator
no longer transcribes the allowlist into a second file (see [Operator
workflow](#operator-workflow) below). The renderer preflight is
[range-egress-allowlist-render-preflight-958.md](range-egress-allowlist-render-preflight-958.md).

Issue #1015 wired that renderer into the deploy paths: the AWS (`_range.yml`)
and GCP (`_gcp-dev.yml`) deploy workflows and `scripts/bootstrap/deploy.py`'s
GCP control-plane apply now run `shifter-config render` against the deployment's
`shifter.yaml` at plan/apply time, so the egress allowlist is single-source
end-to-end and is no longer carried as an independently maintained copy in a
deploy secret (see [CI and scripted deploys](#ci-and-scripted-deploys) below).
The CI-render preflight is
[range-egress-ci-render-preflight-1015.md](range-egress-ci-render-preflight-1015.md).

## Public surface

```yaml
# shifter.yaml
settings:
  range_egress:
    mode: allowlist
    allowed_cidrs:
      - 203.0.113.0/24
      - 198.51.100.42/32
```

`mode` is one of:

| mode          | behavior                                                                 |
| ------------- | ------------------------------------------------------------------------ |
| `status-quo`  | default. each backend keeps its existing posture (PLAT-220 is opt-in)    |
| `deny-all`    | block all egress; the documented per-backend exception lanes still apply |
| `allowlist`   | deny-all base + allow HTTPS (TCP 443) to the listed CIDRs                |

Omitting the `range_egress` block is equivalent to `mode: status-quo`.

`allowed_cidrs`:

- Each entry must be a syntactically valid CIDR with an explicit prefix length.
- `0.0.0.0/0` and `::/0` are rejected; allow-all is a separate mode (not
  defined; out of scope for PLAT-220).
- Host bits set are rejected; write the network address.
- Duplicate entries after canonicalisation are rejected.
- IPv4 and IPv6 are both accepted.
- The list must be non-empty when `mode` is `allowlist`; the list must be empty
  when `mode` is `status-quo` or `deny-all`.

Validation lives in `shifter/installation/range_egress.py`. Each backend's
Terraform module also revalidates the shape so direct `terraform apply` from an
operator's workstation rejects malformed values without going through
`shifter-config`.

## Where the values live

CIDRs are operator configuration (not secrets), but the per-deployment
allowlist is **not** committed to the repo:

| File / surface                                                                                  | Status                  |
| ---------------------------------------------------------------------------------------------- | ----------------------- |
| `shifter.yaml`                                                                                  | operator-authored; not committed by the repo |
| `shifter/installation/examples/{aws,gcp}.yaml`                                                  | committed; empty `status-quo` baseline |
| `platform/terraform/environments/{dev,prod}/range/terraform.tfvars`                             | committed; `victim_allowed_cidrs = []` baseline |
| `platform/terraform/environments/{dev,prod}/range/local.auto.tfvars.example`                    | committed; documented shape only |
| `platform/terraform/environments/{dev,prod}/range/local.auto.tfvars`                            | gitignored; operator's other per-deployment overrides (not the egress allowlist) |
| `platform/terraform/environments/{dev,prod}/range/victim_allowed_cidrs.auto.tfvars`             | gitignored; `shifter-config render` output (AWS egress bridge) |
| `platform/terraform/gcp/environments/gcp-dev/terraform.tfvars`                                  | committed; `range_egress_mode = "status-quo"`, empty allowlist |
| `platform/terraform/gcp/environments/gcp-dev/local.auto.tfvars`                                 | gitignored; operator's other per-deployment overrides (not the egress allowlist) |
| `platform/terraform/gcp/environments/gcp-dev/range_egress.auto.tfvars`                          | gitignored; `shifter-config render` output (GCP egress bridge) |

Two `.gitignore` rules prevent the prior committed forms from being
re-introduced:

```
victim_allowed_cidrs*.auto.tfvars
range_egress*.auto.tfvars
```

## AWS bridge

`platform/terraform/modules/range/vpc/firewall.tf` enforces the allowlist via
AWS Network Firewall rule groups. The relevant Terraform variable is
`victim_allowed_cidrs : list(string)` (internal name; the public name is
`settings.range_egress.allowed_cidrs`). When the list is non-empty and
`enable_network_firewall = true` (the existing dev/prod default), the module:

- Splits the CIDRs into chunks of 300 (AWS rule-length limit) and creates one
  `aws_networkfirewall_rule_group` per chunk with a Suricata rule
  `pass tcp $HOME_NET any -> $ALLOWED_IPS 443`.
- Inserts those rule groups into the firewall policy ahead of the existing
  victim-domain SNI allow rules, the DNS / NTP allow lanes, and the
  default-deny `drop ip $HOME_NET any -> $EXTERNAL_NET any`.

When `victim_allowed_cidrs` is empty, the existing NGFW-bypass / DNS / NTP
allow lanes still apply and unmatched egress is dropped; this is the
documented `status-quo` behavior. `enable_network_firewall = false` short-
circuits enforcement; the documented platform contract says this is the
operator's explicit opt-out from PLAT-220 on AWS.

## GCP bridge

`platform/terraform/gcp/modules/platform-core/main.tf` enforces the allowlist
via two `google_compute_firewall` resources on the range VPC. The two
Terraform variables are `range_egress_mode : string` and
`range_egress_allowed_cidrs : list(string)`. The resources are conditional:

| mode           | rules created                                                                                 |
| -------------- | --------------------------------------------------------------------------------------------- |
| `status-quo`   | none. range Cloud NAT egress is unchanged (the historical posture).                           |
| `deny-all`     | `range-egress-deny-all` only: priority 65534 EGRESS deny on `0.0.0.0/0`, protocol `all`.      |
| `allowlist`    | `range-egress-deny-all` + `range-egress-allow-allowlist`: priority 1000 EGRESS allow on TCP 443 to `destination_ranges = range_egress_allowed_cidrs`. |

Private Google Access (Google APIs, Container Registry, Artifact Registry)
rides the platform VPC's internal routing and is unaffected by the range VPC's
egress rules; the metadata server (`169.254.169.254`) is on the local link
and is not subject to firewall egress rules either.

## Cross-backend symmetry

The wire-level shape is identical on both clouds: HTTPS (TCP 443) to the
operator-declared CIDRs, deny-all base, status-quo as the documented
opt-in. The implementation differs (AWS Network Firewall Suricata rules
vs. GCP VPC firewall egress rules), but the platform contract operators
program against is the same `settings.range_egress` block.

## Out of scope

- Domain-based egress allowlists (`victim_allowed_domains`,
  `kali_allowed_domains` on the AWS module); domains and CIDRs are
  separate concepts; the AWS module already exposes
  `victim_allowed_domains` independently and GCP has no native domain-based
  egress filter at the VPC firewall layer. A future requirement can
  introduce a cross-cloud domain abstraction.
- Scenario-level overrides (PLAT-221), composable allowlist sets +
  admin UI (PLAT-222), and RBAC for allowlist management (PLAT-223). Those
  refinements extend the `settings.range_egress` surface; the platform-level
  default established here remains the fallback.
- A `shifter.yaml` -> provider Terraform bridge renderer was out of scope for
  the original #775 / PLAT-220 implementation; #958 delivered it as
  `shifter-config render`, preserving the public policy and backend bridge
  semantics documented here, and #1015 wired it into the deploy paths (see [CI
  and scripted deploys](#ci-and-scripted-deploys)). Both are now delivered, not
  follow-up scope.
- An explicit `allow-all` mode. The platform contract rejects `0.0.0.0/0`
  to keep operators from encoding allow-all as a sentinel CIDR. A future
  requirement can introduce a real allow-all mode with a documented
  rationale.

## Operator workflow

1. Author your `shifter.yaml` with `settings.range_egress.{mode,allowed_cidrs}`.
2. Render the provider Terraform bridge values from that single source with
   `shifter-config render`. The renderer reads the `backend` from `shifter.yaml`
   and emits the matching bridge variables (AWS `victim_allowed_cidrs`; GCP
   `range_egress_mode` + `range_egress_allowed_cidrs`), so you never transcribe
   the CIDRs a second time:
   - **AWS dev / prod range**:

     ```bash
     uv run --project shifter/installation shifter-config render shifter.yaml \
       --output platform/terraform/environments/<env>/range/victim_allowed_cidrs.auto.tfvars
     ```

   - **GCP gcp-dev**:

     ```bash
     uv run --project shifter/installation shifter-config render shifter.yaml \
       --output platform/terraform/gcp/environments/gcp-dev/range_egress.auto.tfvars
     ```

   Re-run it whenever the allowlist changes.
3. Run `terraform apply` from each env directory. Terraform auto-loads the
   rendered `*.auto.tfvars` alongside the committed `terraform.tfvars`.

The rendered `*.auto.tfvars` is gitignored and generated; never hand-edit or
commit it, and re-render rather than editing in place. It is a dedicated file
separate from any `local.auto.tfvars` that carries unrelated deployment
overrides, so re-rendering the allowlist never clobbers those.

## CI and scripted deploys

The CI and scripted deploy paths run the same `shifter-config render` so they
never consume a second copy of the allowlist (#1015). The deployment's
`shifter.yaml` reaches them as a GitHub Actions secret (or a resolved path for
the local scripted bootstrap); each path writes it to an ephemeral file and
renders the backend bridge tfvars before Terraform consumes the variables. A
missing config fails the deploy loud; it never silently falls back to
`status-quo`.

| Deploy path | Config source | Renders |
| ----------- | ------------- | ------- |
| `.github/workflows/_range.yml` (AWS `dev`/`prod`, plan + apply) | `SHIFTER_CONFIG_DEV_RANGE` / `SHIFTER_CONFIG_PROD_RANGE` secret (strict `inputs.is_dev` selection) | `victim_allowed_cidrs.auto.tfvars` in the env's range dir |
| `.github/workflows/_gcp-dev.yml` (GCP deploy) | `SHIFTER_CONFIG_GCP_DEV` secret | `range_egress.auto.tfvars` in the gcp-dev env dir |
| `scripts/bootstrap/deploy.py gdc-bootstrap` (GCP control-plane apply) | `--shifter-config` → `$SHIFTER_CONFIG` → repo-root `shifter.yaml` | `range_egress.auto.tfvars` in the gcp-dev env dir |

The config secret carries `shifter.yaml`, which holds secret *references* rather
than secret values; the deploy steps still treat it as sensitive (written by
shell redirection, never echoed, passed in argv, or uploaded as an artifact).
See [docs/dev/deploy-secrets.md](../dev/deploy-secrets.md) for the secret names
and the non-egress range overrides that stay in `TF_VARS_*_RANGE` /
`local.auto.tfvars`.

## Migration from the prior committed allowlist

The pre-PLAT-220 repo carried the operator's allowlist directly in
`platform/terraform/environments/{dev,prod}/range/victim_allowed_cidrs.auto.tfvars`
(and a copy under `platform/terraform/modules/range/vpc/`). Those files are
removed in this change. Before applying the updated repo against an existing
deployment, the operator must:

1. Recover the prior list from the deleted file (Git history, prior checkout,
   or the PANW Cortex documentation). The values were public IP CIDRs, not
   secrets, so Git history is fine.
2. Put the recovered list into `shifter.yaml` under
   `settings.range_egress.allowed_cidrs` (with `mode: allowlist`), then run
   `shifter-config render` for each affected environment to generate its
   `victim_allowed_cidrs.auto.tfvars` (see [Operator workflow](#operator-workflow)).
   Do **not** write the recovered list into `local.auto.tfvars` by hand: that
   re-creates the second drift-prone source this change removes.
3. Run `terraform plan` and confirm there is **no diff** in the
   `aws_networkfirewall_rule_group.victim_ips[*]` resources. Going from N
   chunks to fewer chunks (or zero) requires the policy update + rule-group
   delete to happen in the right order; the existing comment in
   `platform/terraform/modules/range/vpc/firewall.tf` describes the manual
   recovery path if Terraform shows the reduction.

For a fresh deployment, no migration is needed; the committed baseline is
empty. The operator authors `shifter.yaml`, runs `shifter-config render`, and
the first apply sets the allowlist from the rendered tfvars.
