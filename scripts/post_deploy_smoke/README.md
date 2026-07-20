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

## Local usage

```bash
export ENV=dev
export AWS_PROFILE=<dev profile>
export SMOKE_TEST_USER_EMAIL=smoke-dev@paloaltonetworks.com
bash scripts/smoke-test.sh --variant linux
bash scripts/smoke-test-windows.sh
```

Implementation lives in `cms/post_deploy_smoke/` and
`python manage.py run_post_deploy_smoke`.
