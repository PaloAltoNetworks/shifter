# Polaris CTFd Ops

Operational helpers for the standalone Polaris CTFd at `polaris.example.com`. These are out-of-band scripts; they do not depend on Shifter's native CTF feature set.

## Terraform

Create the instance from the dedicated stack:

```bash
cd platform/terraform/global/ctfd-workshop
AWS_PROFILE=panw-shifter-dev-workstation terraform init -backend-config=dev.s3.tfbackend
AWS_PROFILE=panw-shifter-dev-workstation terraform apply -var-file=dev.tfvars
```

After apply:

1. Create the external DNS `A` record for the CTFd hostname to the new Elastic IP.
   In Cloudflare, keep the record DNS-only for the first certbot run and put
   only the IP address in the target field, not an `http://` or `https://` URL.
2. Use the Terraform `certbot_command` output over SSM after DNS resolves.
   Verify `https://<ctfd-hostname>/login` reaches CTFd from outside AWS.
3. If the hostname should sit behind Cloudflare, switch the same `A` record to
   proxied after origin HTTPS works and set Cloudflare SSL/TLS mode to
   `Full (strict)`.
   Do not leave a Managed Challenge, Bot Fight Mode, Browser Integrity Check,
   or equivalent challenge action in front of the CTFd hostname unless the
   event explicitly accepts that participant and API traffic may be challenged.
   A smoke check to `https://<ctfd-hostname>/login` should return the CTFd login
   page, not a Cloudflare `cf-mitigated: challenge` response.
4. Complete the CTFd setup wizard in the browser.
5. Generate an admin API token in CTFd and export it as `CTFD_TOKEN`.

## Polaris Onboarding Pages + Start Here Warm-Up

This syncs the Polaris CTFd landing page (`index`), the quickstart page, and the `Start Here — Kali Warm-Up` challenge from:

- [scenario-dev/polaris/build/ctfd-pages](/home/atomik/src/shifter/scenario-dev/polaris/build/ctfd-pages)
- [scenario-dev/polaris/build/ctfd-onboarding.json](/home/atomik/src/shifter/scenario-dev/polaris/build/ctfd-onboarding.json)

It does **not** modify the range bake or any scenario box content.

```bash
export CTFD_TOKEN=<admin-token>
python3 scripts/ctfd-workshop/sync_polaris_ctfd_onboarding.py \
  --base-url https://polaris.example.com
```

If the core Polaris board has not been imported yet, rerun the sync after the main challenges exist so the warm-up challenge can wire its `next` link to `Company Info`.

## Full Polaris Board Sync

This syncs the full Polaris board, including the Start Here warm-up, Missions 1-9, pages, static flags, hint ladders, prerequisites, and tags from:

- [scenario-dev/polaris/build/ctfd-challenges.json](/home/atomik/src/shifter/scenario-dev/polaris/build/ctfd-challenges.json)
- [scenario-dev/polaris/build/ctfd-pages](/home/atomik/src/shifter/scenario-dev/polaris/build/ctfd-pages)
- [scenario-dev/polaris/build/ctfd-onboarding.json](/home/atomik/src/shifter/scenario-dev/polaris/build/ctfd-onboarding.json)

It does **not** modify the range bake or any scenario box content.

```bash
export CTFD_TOKEN=<admin-token>
python3 scripts/ctfd-workshop/sync_polaris_ctfd.py \
  --base-url https://polaris.example.com
```

Flag, hint, and tag rows are reconciled against the source JSON on every
challenge upsert, so re-syncs are idempotent. The source manifest is validated
before any CTFd write, and after sync the script reads flag and hint rows back
from CTFd and exits non-zero if any challenge that should have them has none.

### Bare-hex flag acceptance

Source flags written as canonical `FLAG{<16-hex>}` static entries sync to CTFd
as one row of `type: regex`, `data: case_insensitive`, and content
`^(?:FLAG\{<16-hex>\}|<16-hex>)$` (issue #705). Participants who copy only the
inner hex from a recovered artifact submit successfully, and the wrapped form
keeps working too. The repo source content stays canonical: walkthroughs,
challenge descriptions, the warm-up note, and the CTFd page copy continue to
show `FLAG{<16-hex>}` as the answer. Only the live CTFd row shape changes.

The 16-hex body length is the production contract, not a hint: manifest
validation rejects `FLAG{...}` static entries whose body is missing, malformed,
non-hex, or any length other than 16. A short body would derive a trivially
short bare-hex alias that could ship a 1-3 character accepted answer to CTFd,
so this check runs before any live mutation.

Flags already typed `regex` in the source JSON pass through unchanged, and
static entries whose content is not a canonical FLAG wrapper at all also pass
through as-is. Malformed wrappers (`FLAG{` open without a clean
`FLAG{<16-hex>}` close) fail manifest validation before any live write so a
silently mis-aliased flag cannot reach the board. The first re-sync after a
content version that predates this change deletes any stale static rows and
creates the aliased regex rows in the same pass; subsequent syncs are no-ops.

## Create Participants

When the participant CSV is ready, create users with:

```bash
python3 scripts/ctfd-workshop/create_users.py \
  --base-url https://polaris.example.com \
  --csv participants.csv \
  --output participant-credentials.csv
```

Expected CSV columns:

- `name`
- `email`
- `password` (optional)
- `affiliation` (optional)

If `password` is omitted, the script generates one and writes it to the output CSV.
