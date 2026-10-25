# Post-deploy range smoke (#218)

Operator/CI harness that provisions a real dev range through existing CMS/engine
services, verifies guest connectivity, and tears down via request-id ownership paths.

The smoke validates the **platform** (range provisioning, guest connectivity,
teardown), not scenario content. Each variant provisions a minimal range built
entirely from the base range AMIs. `linux` uses the `smoke_linux` scenario
(Kali attacker + Ubuntu victim, SSH probe) and `windows` uses `smoke_windows`
(Kali attacker + plain Windows victim, RDP probe). Every instance is
`os_type` kali/ubuntu/windows with `xdr_agent: false`, so **no XDR agent is
required**. XDR/agent install is scenario-specific content and is exercised by
real scenarios, not by the post-deploy smoke (#1422).

## Required environment

- `SMOKE_TEST_USER_EMAIL`: dedicated automation identity (for example
  `smoke-dev@paloaltonetworks.com`); created in Django on first run if missing.
  No mailbox or interactive login required; do not use a human operator account.
- AWS credentials with SSM access to the portal EC2 instance
- `ENV` (default `dev`) and optional `PORTAL_INSTANCE_TAG` (default `${ENV}-portal`)

For GCP, use an authenticated `kubectl` context for the target platform cluster
instead of AWS credentials. The harness derives a short-lived Job from the live
`portal-web` pod template in `shifter-platform`, retaining its exact image,
service account, access-pool placement and runtime configuration. The Job and
its temporary identity Secret are deleted on exit. This avoids relying on the
streaming `kubectl exec` transport through GKE Connect Gateway.

The GCP migration Job idempotently registers the immutable shipped smoke pack
through `bootstrap_inbox_catalog` before the release rolls out. It uses a
bounded, non-login system actor so first deployment does not depend on a human
administrator having signed in already. Pack registration and conformance still
use the normal ingestion services and fail closed on identity drift.

## Local usage

```bash
export ENV=dev
export AWS_PROFILE=<dev profile>
export SMOKE_TEST_USER_EMAIL=smoke-dev@paloaltonetworks.com
bash scripts/smoke-test.sh --variant linux
bash scripts/smoke-test-windows.sh
```

For a GCP product-path validation, invoke the same management command inside
the deployed portal:

```bash
bash scripts/smoke-test-gcp.sh --variant linux
```

The CI `post-deploy-smoke` job in `.github/workflows/_gcp-dev.yml` runs
`scripts/smoke-test-gcp.sh` after a successful gcp-dev deploy (#1638).

Do not substitute a direct provisioner/backend call: accepted evidence must
show the CMS-created `smoke_linux` range reached READY, the SSH probe succeeded,
and request-owned destroy completed. Record the target environment, request ID,
terminal status, probe result, and cleanup result without copying credentials
or guest secret values.

The management command prints `destroy requested` after the product accepts the
request; provider teardown continues asynchronously. For a manual acceptance
run, also wait for the named destroy Job in `shifter-jobs` to reach `Complete`
and verify the request's range-owned resources are absent. Do not delete those
resources directly to make the smoke pass. The wrapper's short-lived Job and
identity Secret in `shifter-platform` must also be absent after it exits.

Implementation lives in `cms/post_deploy_smoke/` and
`python manage.py run_post_deploy_smoke`.
