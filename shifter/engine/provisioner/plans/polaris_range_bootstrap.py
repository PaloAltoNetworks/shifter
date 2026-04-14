"""POLARIS range per-instance bootstrap plan.

The polaris VM AMI is baked from a working range-0 docker compose stack —
17 containers including a14-kali and a dns container that hardcodes
dc01.boreas.local to range 0's DC IP. When the AMI is launched into a
fresh user range, two things must happen before participants can use it:

1. The dns container's docker-compose.override.yml carries DC01_IP from
   bake time. Each user range has its DC at a *different* private IP
   (.11 of that range's subnet — different last octet across ranges).
   The override has to be regenerated with this range's actual DC IP and
   the dns container recreated so its zone file resolves dc01 correctly.

2. The a14-kali container has a per-bake authorized_keys for the bake-
   time terraform tls_private_key. Each user range has its own
   tls_private_key.instance generated at apply time. The container's
   /home/kali/.ssh/authorized_keys has to be replaced with this range's
   per-instance public key so the portal terminal UI can SSH in as kali.

Both regenerations run via SSM RunCommand against the polaris VM EC2
host. The dns + a14-kali container entrypoints (already in the AMI's
docker-compose stack) sed/echo the new env-var values into the in-
container files on startup, so we just rewrite the override file on the
host and `docker compose up -d --force-recreate` the two affected
containers.

This plan runs AFTER LinuxBootstrapPlan in the orchestrator dispatch
for any attacker instance whose ami_key is polaris-vm, gated by the
caller in main.py (no scenario_id plumbing needed).
"""

from typing import Any, ClassVar

from .base import SetupStep

# Bash run on the polaris VM Ubuntu host via SSM. Rewrites the bake-time
# docker-compose.override.yml with this range's DC IP + per-instance kali
# pubkey, then force-recreates the dns + a14-kali containers so their
# entrypoints pick up the new env vars and re-render their internal state.
POLARIS_RANGE_BOOTSTRAP_SCRIPT = """#!/bin/bash
set -euo pipefail

DC_IP="{{ dc_ip }}"
KALI_PUBKEY="{{ public_key }}"

if [[ -z "$DC_IP" ]]; then
  echo "polaris bootstrap: DC_IP is empty, refusing to rewrite override" >&2
  exit 1
fi
if [[ -z "$KALI_PUBKEY" ]]; then
  echo "polaris bootstrap: KALI_PUBKEY is empty, refusing to rewrite override" >&2
  exit 1
fi

cd /opt/polaris/scenario-dev/polaris/build

# Atomic rewrite via tmp + mv so docker compose never sees a partial file.
cat > docker-compose.override.yml.new <<COMPOSE_EOF
services:
  a14-kali:
    ports:
      - "22:22"
      - "3389:3389"
    environment:
      KALI_AUTHORIZED_KEY: "$KALI_PUBKEY"
  dns:
    environment:
      DC01_IP: "$DC_IP"
COMPOSE_EOF
mv docker-compose.override.yml.new docker-compose.override.yml

# Force-recreate only the two containers whose env vars changed. The
# other 15 stay running undisturbed.
docker compose up -d --force-recreate dns a14-kali

# Wait up to 60s for both containers to be Up before declaring success.
# `docker ps --format` uses Go template syntax (e.g. .Names, .Status)
# inside double-brace delimiters. The orchestrator's render pass uses a
# regex that requires word characters between the delimiters, so Go
# template tokens with a leading dot pass through untouched. (Don't
# describe Jinja-style placeholders inline in this comment — the
# renderer would see them too and demand a substitution variable.)
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  ps_out=$(docker ps --format '{{.Names}} {{.Status}}' || true)
  a14_up=$(echo "$ps_out" | grep -c '^a14-kali .*Up' || true)
  dns_up=$(echo "$ps_out" | grep -c '^dns .*Up' || true)
  if [[ "$a14_up" == "1" && "$dns_up" == "1" ]]; then
    echo "polaris bootstrap: a14-kali + dns up after attempt $attempt"
    break
  fi
  sleep 5
done

# Verify the kali container actually has the per-instance pubkey written
# (the a14 entrypoint reads $KALI_AUTHORIZED_KEY and writes the file).
for attempt in 1 2 3 4 5; do
  if docker exec a14-kali test -s /home/kali/.ssh/authorized_keys 2>/dev/null; then
    echo "polaris bootstrap: kali authorized_keys present"
    break
  fi
  sleep 3
done

echo "polaris bootstrap: complete"
exit 0
"""

# Pulls the latest scenario-dev/polaris/tests/ tree out of S3 and unpacks it
# under /opt/polaris/scenario-dev/polaris/tests/. The polaris-vm AMI bakes
# only the build/ subtree (docker compose stack), not the tests/ subtree,
# so the organizer-facing smoketest harness otherwise isn't available on
# freshly provisioned ranges. This step materialises it on every range so
# `bash /opt/polaris/scenario-dev/polaris/tests/run-all-smoketests.sh`
# works out-of-the-box without any per-range manual upload.
#
# The bucket + prefix is the one the dev-range-range-instance IAM role
# already whitelists for GetObject (shifter-dev-user-storage-e3462f0c).
# A new tarball is uploaded by the operator whenever the test harness or
# an individual smoketest is fixed; the download is idempotent so re-runs
# pick up the latest.
FETCH_POLARIS_TESTS_SCRIPT = """#!/bin/bash
set -euo pipefail

BUCKET="shifter-dev-user-storage-e3462f0c"
KEY="polaris/tests/polaris-tests.tar.gz"
DEST_ROOT="/opt/polaris/scenario-dev/polaris"
TARBALL="/tmp/polaris-tests.tar.gz"

mkdir -p "$DEST_ROOT"

# aws cli is preinstalled on the polaris-vm AMI base. It picks up the
# EC2 instance profile automatically via IMDSv2, so no explicit creds.
aws s3 cp "s3://$BUCKET/$KEY" "$TARBALL" --region us-east-2

if [[ ! -s "$TARBALL" ]]; then
  echo "polaris tests fetch: downloaded tarball is empty" >&2
  exit 1
fi

# Clear any stale tests/ from a previous bootstrap before extracting,
# so removed test files don't linger.
rm -rf "$DEST_ROOT/tests"

tar xzf "$TARBALL" -C "$DEST_ROOT"

if [[ ! -x "$DEST_ROOT/tests/run-all-smoketests.sh" ]]; then
  echo "polaris tests fetch: run-all-smoketests.sh missing after extract" >&2
  ls -la "$DEST_ROOT/tests" >&2 || true
  exit 1
fi

# Make every script in tests/ executable (tar may not preserve +x on a
# subset of *.py files depending on how the tarball was built).
find "$DEST_ROOT/tests" -type f \\( -name '*.sh' -o -name '*.py' \\) -exec chmod +x {} +

echo "polaris tests fetch: tests/ tree materialised at $DEST_ROOT/tests"
ls "$DEST_ROOT/tests/smoketests" | wc -l | xargs -I{} echo "polaris tests fetch: {} smoketest files available"
exit 0
"""

# Verification: prove a14-kali is up and dns resolves dc01 to this range's
# DC. If any check fails, the plan is reported as failed and the range
# provisioner aborts. The dig query runs from inside a14-kali because
# the alpine `bind` package on the dns container ships only the daemon
# (named) — `dig` lives in the separate `bind-tools` package and is not
# installed there. a14-kali has dig + ldap-utils + smbclient pre-baked
# and points its /etc/resolv.conf at the dns container by default, so
# `docker exec a14-kali dig` exercises the real participant resolution
# path end-to-end.
VERIFY_POLARIS_BOOTSTRAP_SCRIPT = """#!/bin/bash
set -euo pipefail

DC_IP="{{ dc_ip }}"

# 1. a14-kali container is running.
if ! docker ps --format '{{.Names}}' | grep -qx 'a14-kali'; then
  echo "polaris verify: a14-kali is not running" >&2
  exit 1
fi

# 2. dns container is running.
if ! docker ps --format '{{.Names}}' | grep -qx 'dns'; then
  echo "polaris verify: dns is not running" >&2
  exit 1
fi

# 3. dns container resolves dc01.boreas.local to THIS range's DC IP.
#    Query from inside a14-kali because the alpine `bind` package on the
#    dns container does not include dig (it's in the separate `bind-tools`
#    package). a14-kali points at the dns container via docker compose's
#    bridge DNS, so this exercises the real participant lookup path.
resolved=$(docker exec a14-kali dig +short dc01.boreas.local || true)
if [[ "$resolved" != "$DC_IP" ]]; then
  echo "polaris verify: dc01.boreas.local resolved to '$resolved', expected '$DC_IP'" >&2
  exit 1
fi

# 4. a14-kali has the per-instance kali pubkey installed.
if ! docker exec a14-kali test -s /home/kali/.ssh/authorized_keys; then
  echo "polaris verify: a14-kali /home/kali/.ssh/authorized_keys is missing or empty" >&2
  exit 1
fi

echo "polaris verify: dc01 -> $resolved, kali key installed"
exit 0
"""


class PolarisRangeBootstrapPlan:
    """Per-range polaris VM bootstrap.

    Runs after LinuxBootstrapPlan against the polaris VM EC2 host. Steps:

    1. Rewrite docker-compose.override.yml with this range's DC IP and
       per-instance kali pubkey.
    2. Force-recreate the dns and a14-kali containers so their
       entrypoints pick up the new env vars.
    3. Fetch the latest scenario-dev/polaris/tests/ tree from the
       shared dev-range-readable S3 bucket so the organizer smoketest
       harness is available on every freshly provisioned range.

    Verification:

    - dns container resolves dc01.boreas.local to the range-local DC IP
      (not the bake-time IP from range 0).
    - a14-kali container has /home/kali/.ssh/authorized_keys present.
    """

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="polaris_range_bootstrap",
            script=POLARIS_RANGE_BOOTSTRAP_SCRIPT,
            timeout_seconds=300,
            requires_reboot=False,
        ),
        SetupStep(
            name="polaris_fetch_tests",
            script=FETCH_POLARIS_TESTS_SCRIPT,
            timeout_seconds=120,
            requires_reboot=False,
        ),
    ]

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_polaris_range",
        script=VERIFY_POLARIS_BOOTSTRAP_SCRIPT,
        timeout_seconds=60,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Return template variables for the polaris range bootstrap script.

        Args:
            instance: Object with `dc_ip` and `public_key` attributes
                (the per-instance ssh public key from terraform's
                tls_private_key.instance).

        Returns:
            Dict with `dc_ip` and `public_key`.

        Raises:
            ValueError: If either is missing or empty.
        """
        dc_ip = getattr(instance, "dc_ip", None)
        if not dc_ip:
            raise ValueError(
                "PolarisRangeBootstrapPlan requires instance.dc_ip "
                "(polaris kali host needs the range's DC IP to rewrite "
                "the dns container's zone file)"
            )

        public_key = getattr(instance, "public_key", None)
        if not public_key:
            raise ValueError(
                "PolarisRangeBootstrapPlan requires instance.public_key "
                "(per-instance kali pubkey from tls_private_key.instance)"
            )

        return {
            "dc_ip": dc_ip,
            "public_key": public_key,
        }
