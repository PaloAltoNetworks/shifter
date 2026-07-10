# Post-deploy range smoke (#218)

Operator/CI harness that provisions a real dev range through existing CMS/engine
services, verifies guest connectivity, and tears down via request-id ownership paths.

## Required environment

- `SMOKE_TEST_USER_EMAIL` — dedicated automation identity (e.g.
  `smoke-dev@paloaltonetworks.com`); created in Django on first run if missing.
  No mailbox or interactive login required; do not use a human operator account.
- `SMOKE_LINUX_AGENT_ID` — required for the `linux` variant (`basic` scenario):
  its victim is a `from_agent` instance, so the launch needs a linux agent owned
  by the smoke user.
- `SMOKE_WINDOWS_AGENT_ID` / `SMOKE_LINUX_AGENT_ID` — required for the `windows`
  variant (`ad_attack_lab` scenario)
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
