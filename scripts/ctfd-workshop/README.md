# Standalone Workshop CTFd

This directory is the one-off ops path for tonight's standalone CTFd at `ctf.shifter.example.com`. It does not depend on Shifter's native CTF feature set.

## Terraform

Create the instance from the dedicated stack:

```bash
cd platform/terraform/global/ctfd-workshop
AWS_PROFILE=panw-shifter-dev-workstation terraform init -backend-config=dev.s3.tfbackend
AWS_PROFILE=panw-shifter-dev-workstation terraform apply -var-file=dev.tfvars
```

After apply:

1. Create the external DNS `A` record for `ctf.shifter.example.com` to the new Elastic IP.
2. Use the Terraform `certbot_command` output over SSM after DNS resolves.
3. Complete the CTFd setup wizard in the browser.
4. Generate an admin API token in CTFd and export it as `CTFD_TOKEN`.

## Seed Challenges

This seeds the 10 `agentic_workshop` challenges, static flags, challenge hints, the Box 0 walkthrough content, and baseline private registration settings:

```bash
export CTFD_TOKEN=<admin-token>
python3 scripts/ctfd-workshop/seed_ctfd.py --base-url https://ctf.shifter.example.com
```

The canonical workshop box/challenge metadata lives in [agentic_workshop.json](/home/atomik/src/shifter/scripts/ctfd-workshop/agentic_workshop.json).

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

## Sync Range Flags

Run this after participant ranges are `ready` so the box flag files match CTFd:

```bash
python3 scripts/ctfd-workshop/sync_range_flags.py \
  --profile panw-shifter-dev-workstation \
  --region us-east-2 \
  <range-id-1> <range-id-2>
```

You can also provide `--range-id-file path/to/range_ids.txt`.

## Create Participants

When the participant CSV is ready, create users with:

```bash
python3 scripts/ctfd-workshop/create_users.py \
  --base-url https://ctf.shifter.example.com \
  --csv participants.csv \
  --output participant-credentials.csv
```

Expected CSV columns:

- `name`
- `email`
- `password` (optional)
- `affiliation` (optional)

If `password` is omitted, the script generates one and writes it to the output CSV.
