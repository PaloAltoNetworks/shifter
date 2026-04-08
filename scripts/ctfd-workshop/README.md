# Standalone Workshop CTFd

This directory is the one-off ops path for tonight's standalone CTFd at `ctf.shifter.keplerops.com`. It does not depend on Shifter's native CTF feature set.

## Terraform

Create the instance from the dedicated stack:

```bash
cd platform/terraform/global/ctfd-workshop
AWS_PROFILE=panw-shifter-dev-workstation terraform init -backend-config=dev.s3.tfbackend
AWS_PROFILE=panw-shifter-dev-workstation terraform apply -var-file=dev.tfvars
```

After apply:

1. Create the external DNS `A` record for `ctf.shifter.keplerops.com` to the new Elastic IP.
2. Use the Terraform `certbot_command` output over SSM after DNS resolves.
3. Complete the CTFd setup wizard in the browser.
4. Generate an admin API token in CTFd and export it as `CTFD_TOKEN`.

## Seed Challenges

This seeds the 10 `agentic_workshop` challenges, static flags, challenge hints, the Box 0 walkthrough content, and baseline private registration settings:

```bash
export CTFD_TOKEN=<admin-token>
python3 scripts/ctfd-workshop/seed_ctfd.py --base-url https://ctf.shifter.keplerops.com
```

The canonical workshop box/challenge metadata lives in [agentic_workshop.json](/home/atomik/src/shifter/scripts/ctfd-workshop/agentic_workshop.json).

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
  --base-url https://ctf.shifter.keplerops.com \
  --csv participants.csv \
  --output participant-credentials.csv
```

Expected CSV columns:

- `name`
- `email`
- `password` (optional)
- `affiliation` (optional)

If `password` is omitted, the script generates one and writes it to the output CSV.
