Made the EC2 `user_data.sh` portal redeploy force-remove containers (`docker rm -f`), matching `scripts/portal-deploy/deploy_portal.sh` (#1127), so both deploy paths are idempotent on redeploy.
