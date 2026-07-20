#!/bin/bash
# TechVault bake — phase 4: confirm the operational stack is fully up before
# Packer images the builder. Faithful port of the retired
# techvault-scenario-bake.yml container-count gate, but polled locally on the
# builder instead of over SSM from the runner.
#
# The techvault-operational contract settles at 30 long-running aptl-*
# containers. (aptl 4.1.2 also runs a one-shot aptl-cortex-index-init that
# exits 0 once Cortex is indexed, so it is not counted here.)
set -euo pipefail

echo "waiting for the stack to reach 30 running aptl containers..."
deadline=$(( $(date +%s) + 900 ))
while true; do
  count="$(docker ps --filter name=aptl- --filter status=running -q | wc -l)"
  echo "running aptl containers: ${count}"
  if [[ "${count}" -ge 30 ]]; then
    echo "stack is up (${count} containers)"
    break
  fi
  if [[ "$(date +%s)" -ge "$deadline" ]]; then
    echo "stack did not reach 30 running containers (last=${count})" >&2
    exit 1
  fi
  sleep 20
done
