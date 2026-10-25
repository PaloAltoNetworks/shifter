# Windows domain-controller image ownership

The scenario-owned native ISO build, unattended answer files and directory seeds
have moved out of core with their image recipes. Pack authors maintain and qualify
those artifacts in their own repository; Shifter consumes declared, immutable
image identities through the supported image/preparation contract.

GCE range cells are the approved GCP live-fire backend. GDC VM Runtime remains a
development and validation backend and is not a fallback for a failed live-fire
launch. See [GCP guest images](gcp-guest-images.md) and the
[GCE range-cell runbook](../dev/gcp-range-cell-deploy.md).

Core's generic pre-promoted GCE DC template requires an explicit profile and
verifies the authored DNS and NetBIOS identity. It has no private domain default.
Keep scenario accounts, seeds, answer material and private build evidence outside
this repository. Use synthetic directory fixtures for shared platform regressions.
