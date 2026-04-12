## 2026-04-09 account cleanup for `prod-rwctxzl6shxk`

Purpose:
- Remove all live GDC/VM Runtime spike resources before re-testing bootstrap from a clean account state.

Removed resources:
- GKE Hub membership: `cluster1`
- Compute Engine instances:
  - `cluster1-abm-cp1-001`
  - `cluster1-abm-cp2-001`
  - `cluster1-abm-cp3-001`
  - `cluster1-abm-w1-001`
  - `cluster1-abm-w2-001`
  - `cluster1-abm-ws0-001`
- Static external addresses:
  - `cluster1-abm-cp1`
  - `cluster1-abm-cp2`
  - `cluster1-abm-cp3`
  - `cluster1-abm-w1`
  - `cluster1-abm-w2`
  - `cluster1-abm-ws0`
- Firewall rules:
  - `cluster1-allow-lb-traffic-rule`
  - `gdc-vmrt-spike-allow-internal`
  - `gdc-vmrt-spike-allow-ssh`
- Subnet: `gdc-vmrt-spike-us-central1`
- Network: `gdc-vmrt-spike`
- Instance templates:
  - `default-instance-template-20260409035322099900000001`
  - `default-instance-template-20260409035322241700000002`
- Service accounts:
  - `default-instance-template-u-sa@prod-rwctxzl6shxk.iam.gserviceaccount.com`
  - `baremetal-gcr@prod-rwctxzl6shxk.iam.gserviceaccount.com`
  - `gdc-vmrt-spike-bootstrap@prod-rwctxzl6shxk.iam.gserviceaccount.com`
- Project-wide Compute metadata key `ssh-keys`
- Cluster-resident test namespace: `vmrt-mixed-subnet`

Final verification state:
- No Compute Engine instances, disks, networks, firewall rules, addresses, routes, instance templates, buckets, or hub memberships remain.
- Remaining service account: only the default Compute Engine service account.

Bootstrap defects discovered during cleanup:
- `/home/tfadmin/bmctl-workspace` was created as `root:root`, which prevented `bmctl reset` from creating logs as `tfadmin`.
- `/home/tfadmin/.manifests` was also `root:root`, which prevented `bmctl reset` from extracting manifests as `tfadmin`.
- `tfadmin` did not have working Docker access for `bmctl`; reset failed with `please add yourself to group docker`.
- The cluster config referenced `/root/bm-gcr.json`, but the service account key behind it did not have enough permissions for teardown; `bmctl reset` failed on missing `compute.zones.list`.
- Bootstrap left `ssh-keys` in project-wide Compute metadata after cluster creation.

Implication for bootstrap work:
- The bootstrap path should either run all `bmctl` lifecycle operations in a consistently privileged context, or it must guarantee that `tfadmin` owns the workspace/manifests cache, has Docker access, and has valid ADC/service-account permissions for both create and reset flows.
