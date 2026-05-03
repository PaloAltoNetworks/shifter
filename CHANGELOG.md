# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.95.0] - 2026-05-03

### Fixed

- **80+ Dependabot security alerts cleared** across every package manager
  in the repo. Python (uv): bumped Django to 6.0.4, cryptography to
  47.0.0, cbor2 to 6.0.1, pyOpenSSL to 26.1.0, pyasn1 to 0.6.3, pytest
  to 9.0.3, python-dotenv to 1.2.2, Pygments to 2.20.0, requests to
  2.33.1, ujson to 5.12.0, urllib3 to 2.6.3, filelock to 3.25.2,
  virtualenv to 21.2.0. Node (npm): bumped hono to 4.12.16,
  @hono/node-server to 1.19.14, path-to-regexp to 8.4.2, flatted to
  3.4.2, picomatch (v2) to 2.3.2 and (v4) to 4.0.4, brace-expansion to
  2.1.0, minimatch (v3) to 3.1.5 and (v9) to 9.0.9, ajv (v6) to 6.15.0
  and (v8) to 8.20.0. Pinned `cryptography==46.0.7` and `protobuf==5.29.6`
  in `shifter/engine/provisioner/requirements.txt`.

### Changed

- **Full dependency refresh on every uv- and npm-managed manifest**
  beyond the security bumps above. `uv lock --upgrade` ran on
  `shifter/shifter_platform/`, `shifter/engine/provisioner/`,
  `scripts/check_layer_imports/`, `scripts/bootstrap/`,
  `shifter/cyberscript/`, and `shifter/packer/` — pulling in the latest
  patch/minor versions of ~40 transitive packages including pydantic
  2.13.3, mypy 1.20.2, ruff 0.15.12, gunicorn 25.3.0, mozilla-django-oidc
  5.0.2, redis 7.4.0, boto3 1.43.2, grpcio 1.80.0, and protobuf 7.34.1.
  `npm update --package-lock-only` ran on the four MCP servers
  (`mcp/{ops,planner,ngfw}/`), `shifter/shifter_platform/`, and
  `platform/terraform/gcp/modules/platform-core/functions/identity-platform/`.
- **Terraform AWS provider major bump** `~> 5.0` → `~> 6.0` across all
  17 root configurations and provisioner modules. The 16 `modules/*`
  subdirectories had already moved to aws 6.x via looser constraints;
  this aligns the consumers (`environments/{dev,prod}`,
  `global/{iam,github-runner,se-admins,tssummit,tssummit-ranges,
  ctfd-workshop,dev-box}`, `scripts/polaris-aws-range/`,
  `temp/ngfw-bootstrap-test/`) so everything resolves to **aws 6.43.0**.
- **Terraform `required_version` standardized to `>= 1.5.0`** across all
  17 root configs (was an inconsistent mix of `>= 1.0` and `>= 1.5.0`).
- **CI Terraform action bumped 1.7.1 → 1.13.3** in `_core.yml`,
  `_range.yml`, and `_shifter-platform.yml` — required by the
  `use_lockfile` migration below (S3 native locking landed in 1.10).
- **Terraform S3 backend state locking migrated from DynamoDB to S3
  native** (`use_lockfile = true`). All inline `backend "s3"` blocks
  (`environments/{dev,prod}/{,portal,range}/backend.tf`,
  `global/iam/backend.tf`) and all `.s3.tfbackend` files dropped
  `dynamodb_table = "..."` in favour of `use_lockfile = true`. The
  `engine-state` module's `aws_dynamodb_table.engine_locks` resource
  is unrelated to terraform state locking and was left intact (it
  serves the Shifter engine application).
- **Environment backend.tf files converted to partial-backend pattern.**
  The six `environments/{dev,prod}/{,portal,range}/backend.tf` files
  used to hard-code the bucket UUID inline; they now ship with
  `OVERRIDDEN_VIA_BACKEND_CONFIG` placeholders and the real values come
  from `<env>.s3.tfbackend` at init time, matching the existing
  `global/iam/` convention. Single source of truth for the bucket
  name; backend.tf is never modified by automation.
- **CI workflows now pass `-backend-config=${env}.s3.tfbackend`** to
  `terraform init` (was bare `terraform init`). Required by the
  partial-backend conversion above.
- **`scripts/bootstrap/deploy.py` rewritten for the new pattern.** The
  walkthrough now writes `.s3.tfbackend` files for env, portal, and
  range (instead of overwriting `backend.tf`), emits
  `use_lockfile = true`, and never touches `backend.tf`. Bootstrap
  steps renumbered 1/3, 2/3, 3/3 (was 1/4..4/4) since DynamoDB table
  creation is gone. The unused `dynamodb_table_exists` and
  `create_dynamodb_table` helpers are kept for now in case someone
  needs to reintroduce DynamoDB locking. `_update_global_backend_configs`
  now also matches the `REPLACE_AT_BOOTSTRAP` literal so freshly
  templated `.tfbackend` files get filled in at bootstrap time.
- **`.terraform.lock.hcl` files now tracked in git** (was ignored by
  the root `.gitignore` plus two nested `.gitignore` files in
  `platform/terraform/global/dev-box/` and
  `scripts/polaris-aws-range/`). All 30 lock files committed at
  aws 6.43.0; the `temp/` tree remains intentionally excluded.
- **All `.s3.tfbackend` files templated.** Bucket UUIDs replaced with
  `REPLACE_AT_BOOTSTRAP` so a fresh bootstrap produces matching
  configs without leaving stale UUIDs in the repo. Three new
  `dev.s3.tfbackend` files added under `environments/dev/`,
  `environments/dev/portal/`, and `environments/dev/range/` (those
  three previously had no `.tfbackend` and relied entirely on inline
  config).

### Removed

- **Empty stub directories** `platform/terraform/modules/pulumi-provisioner/`
  and `platform/terraform/modules/pulumi-state/` — they contained only
  stale `.terraform.lock.hcl` files with no `.tf` content, leftover
  from a deleted module.
- **Stale terraform state in `temp/ngfw-bootstrap-test/`** —
  `terraform.tfstate` and `terraform.tfstate.backup` deleted (no
  corresponding live infrastructure).

## [3.95.5] - 2026-05-03

### Fixed

- **Lint failures surfaced by ruff 0.15 upgrade in 3.95.0.** Pre-commit
  only lints staged files, so these pre-existing violations didn't
  surface until CI ran ruff over the whole tree on the first
  `aws-dev` deploy attempt.
  - `UP042` × 18 across `shifter/shifter_platform/ctf/enums.py`,
    `shifter/shifter_platform/cms/experiments/schemas.py`, and
    `shifter/cyberscript/enums.py`: rewrote `class Foo(str, Enum)` to
    `class Foo(StrEnum)`. Runtime semantics preserved on Python 3.12+
    (StrEnum members are still `str` subclasses; `MyEnum.FOO == "foo"`
    still evaluates True).
  - `E501` × 1 in `shifter/engine/provisioner/plans/polaris_range_bootstrap.py:219`:
    broke the inline `python3 -c '…'` invocation onto its own
    multi-line shell variable so the surrounding `docker exec` line
    stays under 120 chars without changing runtime behaviour.

## [3.95.4] - 2026-05-03

### Added

- **`platform/terraform/global/github-runner/README.md`** documenting
  the actual setup (manual EC2 + SSM registration), the registration
  token semantics (single-use registration, long-lived runner
  credentials after — no per-job re-auth), the AL2023 dependency
  gotcha, and a clean removal procedure.

### Fixed

- **Runner `user_data` now installs libicu + .NET 6 runtime libs
  directly via `dnf`** (`libicu krb5-libs zlib lttng-ust openssl-libs`),
  so a freshly provisioned runner can register on the first
  `./config.sh` call. The bundled `./bin/installdependencies.sh`
  doesn't recognise Amazon Linux 2023 (matches `ID="amzn"` /
  `ID_LIKE="fedora"` and aborts with `Can't detect current OS type`),
  so without these packages registration fails with
  `Libicu's dependencies is missing for Dotnet Core 6.0`. Future
  runner replacements no longer need a manual second SSM pass.

## [3.95.3] - 2026-05-03

### Changed

- **`platform/terraform/global/github-runner/dev.tfvars`** updated for
  the fresh aws-dev account `788327019743`: VPC `vpc-07d0a461204c02a06`,
  public subnet `subnet-0e7da35c92d13cd1d` (us-east-2a). Was pointing
  at IDs from the previous dev account.
- **`scripts/runner-deploy.sh`** cleaned up. Stale `Prerequisites` block
  about a GitHub App + `/shifter/github-runner/key-base64` /
  `webhook-secret` SSM params removed (artifact of an abandoned
  philips-labs/terraform-aws-github-runner approach; current module is
  plain EC2 + manual registration). `rm -rf .terraform.lock.hcl` reduced
  to `rm -rf .terraform/` so the now-tracked lockfile survives. Stale
  `terraform output webhook_endpoint`/`runner_labels` (don't exist)
  replaced with `runner_instance_ids`/`ssm_commands`. Top-of-file
  comment now documents the actual manual-registration flow.

### Removed

- **Cruft zips under `global/github-runner/`** (`webhook.zip`,
  `runners.zip`, `runner-binaries-syncer.zip`, `tfplan`) — leftovers
  from the abandoned philips-labs auto-scaler attempt. None were
  referenced by the current `main.tf`.

## [3.95.2] - 2026-05-03

### Fixed

- **`terraform_deploy` now passes `-backend-config=<env>.s3.tfbackend`**
  to `terraform init`. Was running bare `terraform init -reconfigure`,
  which would have failed against the new partial backends (placeholder
  bucket inline → real value supplied via `-backend-config`). Affects
  the `terraform` and `full` subcommands; bootstrap-only flow was
  unaffected because it inits IAM separately.

### Added

- **Bootstrap script now actually commits and pushes** the filled-in
  `.s3.tfbackend` files at the end of `bootstrap` and `full` commands
  (the README listed this as automated but the code did not implement
  it — stale doc → real behaviour). New `walkthrough_git_commit`
  function stages env-scoped paths only (`global/iam/<env>.s3.tfbackend`,
  `environments/<env>/{,portal,range}/<env>.s3.tfbackend`,
  `environments/<env>/portal/main.tf`, plus any other
  `global/**/<env>.s3.tfbackend` rewritten by the bootstrap), shows
  `git status --porcelain` of those paths, prompts to commit (yes / no /
  manual), commits with `Bootstrap <env>: fill in state bucket <bucket>`,
  then prompts separately to push to `origin/<current-branch>`. Runs in
  both `bootstrap` and `full` flows.

## [3.95.1] - 2026-05-03

### Changed

- **`global/dev-box/` converted to partial-backend pattern.** The
  inline `backend "s3"` block hard-coded `shifter-dev-infra-b7113d6f-…`
  as the bucket — the only file in the repo that still did so. Replaced
  with `OVERRIDDEN_VIA_BACKEND_CONFIG` placeholders + new
  `dev.s3.tfbackend` file, matching the rest of the tree. README updated
  with the `-backend-config=dev.s3.tfbackend` init flag.

### Fixed

- **Bootstrap regex was env-blind and could clobber the wrong
  environment's bucket.** `_update_global_backend_configs` matched
  both `shifter-infra-<uuid>` and `shifter-dev-infra-<uuid>` regardless
  of the `--env` flag, so a `--env prod` run would have rewritten
  `dev-box/main.tf`'s dev bucket reference with the prod bucket.
  Tightened the regex to anchor on the current env's bucket prefix
  (`shifter-infra` for prod, `shifter-<env>-infra` otherwise) plus the
  `REPLACE_AT_BOOTSTRAP` placeholder. Also dropped the `*.tf` walker
  since every `*.tf` backend block is now partial (placeholder bucket,
  real value supplied via `-backend-config` at init).

## [3.94.0] - 2026-04-14

### Added

- **`polaris` cyberscript scenario** (`shifter_platform/cms/scenarios/templates/polaris.yaml`).
  Two-instance POLARIS range (polaris-vm host + Windows DC) that drives
  the full 38-flag BOREAS.LOCAL CTF through the production
  `cms.services.create_range` → `engine.services.create_range` → ECS
  Fargate provisioner path, replacing the one-shot
  `scripts/polaris-aws-range/` terraform. Pins `instance_type: m5.2xlarge`
  on the polaris-vm kali instance so the 17-container docker compose
  stack (Kali XFCE + xrdp + BIND + AD tools) gets the headroom it needs
  instead of falling back to the provisioner's `KALI_INSTANCE_TYPE=t3.large`
  global default.
- **Per-instance `instance_type` scenario override.** Additive field on
  `cms.scenarios.schema.InstanceConfig` and `cyberscript.schemas.range.InstanceSpec`;
  the provisioner's `build_tf_vars` (`shifter/engine/provisioner/main.py`)
  now honours a per-instance `instance_type` when set, falling back to
  the existing role/os-based env-var defaults otherwise. Every existing
  scenario yaml is unaffected (field is optional, default `None`).
- **`PolarisRangeBootstrapPlan`** (`shifter/engine/provisioner/plans/polaris_range_bootstrap.py`).
  Runs after LinuxBootstrapPlan on the polaris-vm host via SSM:
  rewrites `docker-compose.override.yml` with the range's actual DC IP
  and the per-instance kali SSH public key, force-recreates the `dns`
  and `a14-kali` containers so their entrypoints pick up the new env
  vars, then fetches the latest `scenario-dev/polaris/tests/` tree from
  `shifter-dev-user-storage-e3462f0c` so the organizer smoketest harness
  is materialised at `/opt/polaris/scenario-dev/polaris/tests/` on every
  freshly provisioned range without requiring an AMI rebake. Verify step
  proves the dns container resolves `dc01.boreas.local` to the range's
  real DC (not the bake-time range-0 IP) and that the a14-kali
  `authorized_keys` is present.
- **`shifter/.dockerignore`.** Excludes local dev cruft (`**/.env`,
  `__pycache__`, `.venv`, `.git`, IDE folders) from the portal image
  build context. Without this the local `shifter_platform/.env` —
  which sets `AWS_ENDPOINT_URL=http://localhost:4566` for LocalStack —
  was getting copied into `/app/.env`, and `settings.py`'s `load_dotenv()`
  poisoned the deployed portal's boto3 clients so every SQS/S3/SNS call
  tried to hit `localhost:4566` and failed.

### Fixed

- **POLARIS A0 smoketest flag 6 Kursk line extraction regression.**
  Commit `0ca1a18c0` added `poppler-utils` to the `a14-kali` Dockerfile,
  which made `pdftotext` available in the container. The A0 smoketest's
  `command -v pdftotext >/dev/null` branch fires first, and pdftotext's
  paragraph-based layout splits "Kursk Heavy Industries - actuator
  assemblies" onto a separate output line from "$12,000,000", so
  `grep -i kursk | head -1` only caught the company name and the check
  failed even though the PDF content is correct. Smoketest now prefers
  `pdf2txt.py` (pdfminer — what the walkthrough tells participants to
  use, and what produces a single-line output), falls back to pdftotext
  with ±3-line grep context so the split layout still correlates. Range
  content unchanged — participants following the walkthrough were never
  affected; only the organizer smoketest harness was.
- **`kali.sh.tpl` and `linux_bootstrap.py CONFIGURE_SSH_SCRIPT` assume
  a `kali` user exists on the host.** On the polaris-vm AMI (Ubuntu with
  the a14-kali docker container publishing SSH, not a real Kali host)
  there is no `kali` system user, so `chown -R kali:kali /home/kali/.ssh`
  and `systemctl start xrdp` would abort the bootstrap. Both templates
  now guard with `id $user` / `systemctl list-unit-files xrdp.service`
  presence checks and continue cleanly when the host isn't a real Kali
  box.

## [3.93.0] - 2026-04-13

### Fixed

- **polaris user_data IMDS credential race during cold first boot.**
  When the instance profile attaches but IMDS hasn't finished propagating
  credentials, the first `aws s3 cp` fails with
  `fatal error: Unable to locate credentials` and cloud-init's final
  stage exits non-zero — exactly what we hit on range 1 of the 3-range
  smoke bring-up. `user_data.sh.tpl` now polls `aws sts get-caller-identity`
  up to 30 times (4s spacing = 120s ceiling) before the S3 download, so
  the instance waits out the propagation window instead of failing hard.
- **polaris `dns` container zone file was hard-coded to
  `dc01 → 10.1.100.11`**, which is correct for range 0 but wrong for
  every subsequent range — range 1's kali resolved the AD DC name to
  range 0's DC and would have attacked the wrong forest. BIND zone file
  now has a `__DC01_IP__` placeholder, and the container has a new
  `entrypoint.sh` that `sed`-substitutes `$DC01_IP` (passed from
  `docker-compose.override.yml` via user_data) before exec'ing `named`.
  `user_data.sh.tpl` writes the override with `DC01_IP` set to the
  range's a2 private IP, plumbed through from the `aws_instance.polaris`
  `templatefile()` call via a new `a2_private_ip` per-range input
  (`each.value.a2_ip` in `ranges.tf`).

### Added

- **`scripts/polaris-aws-range/register_ranges_parallel.sh`** — batch
  registers every range in `terraform output range_indices` by pulling
  the per-index polaris instance id + subnet id + subnet cidr + private
  IP from `terraform output -json`, staging `register_range.py` once on
  the portal EC2, and running it per-range with the matching `POLARIS_*`
  env vars. Emits one JSON object per range on stdout
  (`{"attacker_uuid","range_id","range_index","participant_email"}`)
  so follow-up tooling (playwright harness, CTF invite) can consume
  the mapping without re-querying terraform.

## [3.92.0] - 2026-04-13

### Fixed

- **a14-kali xfce4-screensaver auto-lock during idle RDP sessions** —
  `xfce4-screensaver` (and `xfce4-power-manager`) are hard `Depends:` of
  `kali-desktop-xfce`, so `apt purge` is off the table. Instead, the
  Dockerfile now `dpkg-divert`s the two `/etc/xdg/autostart/*.desktop`
  entries and removes the originals, so the screen-locker daemon never
  spawns inside the xrdp session. `xset s off / s noblank / -dpms` is
  baked into both `xsession` and `startwm.sh` as belt-and-suspenders.
  Proven end-to-end on the live polaris VM: dpkg-divert list shows both
  `.desktop -> .distrib` diversions, `ps auxw` shows no
  `xfce4-screensaver` / `xfce4-power-manager` processes, `xset q -display
  :10` reports `timeout: 0`, and a fresh Playwright RDP click lands on a
  fully-rendered Xfce desktop with no unlock prompt.

### Changed

- **`a14-kali` operator SSH key injection moved from a one-shot
  `user_data` `docker exec` into the container entrypoint**, driven by a
  `KALI_AUTHORIZED_KEY` environment variable passed through
  `docker-compose.override.yml`. The old path ran once at first boot and
  silently left the container without an authorized_keys file after any
  `docker compose up -d --force-recreate a14-kali`, which broke the
  portal Terminal UI's SSH path. Now every container start re-asserts
  the key at correct ownership + perms (kali:kali 600).
- **`scripts/polaris-aws-range/` terraform module split into
  `main.tf` + `shared.tf` + `ranges.tf`**. Shared SG + IAM role + instance
  profile live in `shared.tf` as single global resources (one SG name
  per VPC, one IAM role name per account — same permissions every
  range would use anyway). Per-range resources (subnet, route table,
  routes, route-table association, polaris VM, A2 DC) live in
  `ranges.tf` behind `for_each = local.range_subnets`, which derives
  each range's /28 + pinned `.10` / `.11` private IPs from
  `cidrsubnet(var.polaris_cidr_block, 4, tonumber(idx))` and
  `cidrhost(...)`. `var.range_indices` defaults to `["0"]` so the
  single-range smoke still applies unchanged, and N-range deploys are
  just `terraform apply -var 'range_indices=["0","1","2"]'`. Outputs
  reformatted into maps keyed by range index.

### Added

- **`scripts/polaris-aws-range/a2_cold_bootstrap_parallel.sh`** — fan-out
  wrapper that runs one `a2_cold_bootstrap.sh` per A2 instance id in
  parallel, writes a per-instance log under `POLARIS_BOOTSTRAP_LOG_DIR`,
  and emits a success/failure summary + non-zero exit if any child
  fails. Reads targets from the command line OR from
  `terraform output -json range_a2_instance_ids` when called with no
  args. Safe to run N-wide because `a2_cold_bootstrap.sh` is per-instance
  idempotent and every SSM command is scoped to its target id.

## [3.91.0] - 2026-04-13

### Added

- **`scripts/polaris-aws-range/polaris_ctf_setup.py`** — creates an
  ACTIVE `CTFEvent` for `scenario_id=polaris_manual_test` and invites
  one participant through the real
  `ctf.services.participant.invite_participant`, which in turn
  auto-creates the Django User (with `username=email`), adds the user
  to `CTF_PARTICIPANT_GROUP`, and generates the
  `secrets.token_urlsafe(32)` invite token. Emits JSON on stdout with
  event_id, participant_id, and invite_token so the caller can wire
  the range + build the magic-link URL.
- **`scripts/polaris-aws-range/polaris_ctf_attach.py`** — reads
  `POLARIS_CTF_PARTICIPANT_ID` and `POLARIS_CMS_RANGE_INSTANCE_ID` from
  the environment and patches `CTFParticipant.range_instance_id`,
  `range_status="ready"`, and `status=ParticipantStatus.ACTIVE`. Lets
  us hand a participant a range that was registered manually (via
  `register_range.py`) instead of the normal
  `cms.services.create_range` pipeline.
- **`scripts/polaris-aws-range/polaris_ctf_cleanup.py`** —
  hard-deletes the CTFParticipant + CTFEvent + Django User created by
  the smoke test, after soft-destroying the participant's engine
  Range and cms RangeInstance rows so the dashboard doesn't keep a
  stale entry if the email is reused. Matches the explicit
  expectation that smoke-test rows leave no trace behind.
- Proved the full CTF magic-link flow end-to-end in the dev portal:
  `/ctf/register/?token=<t>` → Django login → redirect to
  `mission-control:dashboard` → participant-only nav (CTFd instead of
  Assets/Docs, no Launch-a-Range panel) → Terminal connects to the
  participant's Range 7 Kali → `whoami && hostname && dig +short
  dc01.boreas.local` returns `kali / operator / 10.1.100.11` → RDP
  button opens Guacamole to the same Kali Xfce desktop. Uses the live
  polaris range (`i-00474db099dd5344c` / 10.1.100.10) and the A2 DC
  (`i-0dc2a5a473c5058c6` / 10.1.100.11) from 3.90.0's cold rebuild.

## [3.90.0] - 2026-04-13

### Added

- **`scripts/polaris-aws-range/a2_cold_bootstrap.sh`** — end-to-end
  automation for promoting a fresh Windows Server 2022 EC2 to
  `BOREAS.LOCAL`. Waits for SSM agent, installs AD-Domain-Services +
  DNS via a wrapper that also queues the dc01 rename and registers a
  SYSTEM scheduled task for `a2_setup.ps1`, reboots, retries
  `Install-ADDSForest` on the renamed box, waits for the promotion
  reboot, then re-runs `a2_setup.ps1` idempotently against the live
  DC. Replaces the ad-hoc manual SSM steps that were required after
  `terraform apply` in 3.88.0. The run_powershell_file helper builds
  SSM `send-command` parameters via a python3 heredoc +
  `--cli-input-json file://...`; the previous printf-based
  PowerShell escape dance mangled `$`/`\` and failed at
  Install-ADDSForest with "Unexpected token '\$b'".
- **`scripts/polaris-aws-range/reset.sh`** — force-clean helper that
  bypasses `docker compose down --remove-orphans` (which leaks the
  `a15-ops-eng` container on re-up in compose v2.29) by directly
  `docker rm -f`-ing any `build_*` containers + pruning the
  `build_*` networks before `docker compose up -d`. Idempotent
  against a warm polaris VM.
- **`scripts/polaris-aws-range/user_data.sh.tpl`** now masks the
  shifter-ubuntu base-AMI services that collide with Kali's
  published ports: `ssh`, `xrdp`, `xrdp-sesman`, `apache2`, `smbd`,
  `nmbd`, `mysql`, `vsftpd`. Without this the host sshd holds port
  22 before docker-compose can publish `a14-kali` on the same port,
  so the portal Terminal UI landed on the Ubuntu host instead of
  Kali. Operator access to the VM is SSM Session Manager; host sshd
  is unused.
- **`kali_authorized_key` terraform variable** (`variables.tf`,
  `main.tf`, `user_data.sh.tpl`) — the portal Terminal UI key-auths
  into `a14-kali` as `kali` using a private key stored in Secrets
  Manager. `user_data` now injects the matching public key into
  `/home/kali/.ssh/authorized_keys` after `docker compose up -d`, so
  a cold `terraform destroy` + `apply` cycle no longer needs a
  manual SSM follow-up to re-wire portal terminal access.
- **`register_range.py` accepts `POLARIS_*` environment variables**
  for every per-run parameter (instance id, subnet id, subnet cidr,
  kali private ip, ssh secret ARN, etc.), so the cold-rebuild
  operator path is `docker exec -e POLARIS_KALI_INSTANCE_ID=... -i
  portal python - < register_range.py` — no source edit per cycle.

## [3.89.0] - 2026-04-13

### Fixed

- **rockyou.txt was gzipped on Kali by default.** The flag-17 Kerberoast
  chain in `flags-07-19-front-office.md` runs `john --wordlist=/usr/share/
  wordlists/rockyou.txt --format=krb5tgs` — Kali's default install ships
  only `/usr/share/wordlists/rockyou.txt.gz` (~50 MB compressed vs ~140
  MB decompressed), so the walkthrough command 404s out of the box and
  the participant has to `gunzip -k` first. `a14/Dockerfile` now
  explicitly adds `john`, `wordlists`, `ldap-utils`, `smbclient` to the
  apt install list and runs `gunzip -k /usr/share/wordlists/rockyou.txt.gz`
  at image-build time so the documented path works on first try.
- **A16 missing `strings` / `file` / `xxd`.** Flag 30's GPG chain
  walkthrough says "`strings full_integration_sim.mp4` reveals the
  Simulation ID header" and other lab flags use `strings` for binary
  triage on A16. `a16/Dockerfile` now installs `binutils file xxd` so
  those commands exist on the box.

## [3.88.0] - 2026-04-13

### Added

- **A2 Windows Server 2022 AD DC now deployed in-range.** New terraform
  `aws_instance.a2_dc` launches a stock
  `Windows_Server-2022-English-Full-Base` AMI into the same `10.1.100.0/28`
  polaris subnet at `10.1.100.11`, using the shared instance profile +
  security group. Minimal user-data (`a2_user_data.ps1.tpl`) sets the
  Administrator password, disables Windows Firewall on all profiles, and
  enables RDP; everything AD-specific then runs through SSM RunCommand so
  failures are observable/re-runnable.
- **`scripts/polaris-aws-range/a2_setup.ps1`** — idempotent post-promotion
  PowerShell that creates the POLARIS OUs, 17 domain users (with passwords
  matching the A1 mail / A3 wiki reuse chain), Lab-Access / Project-L /
  Research-Coordination / Engineering-Support / SCADA-Admins /
  Security-Staff groups, nests Project-L under
  `Research-Coordination -> Engineering-Support` for flag 14, pins
  `msDS-SupportedEncryptionTypes=4` (RC4-only) on svc-backup + svc-scada so
  GetUserSPNs returns `$krb5tgs$23$` hashes that `hashcat -m 13100` /
  john's `krb5tgs` format can crack, assigns Replicating Directory Changes
  + Replicating Directory Changes All on svc-backup (flag 17 DCSync chain),
  creates the `\\dc\badgelogs` share (Petrov anomaly CSV with flag 16) and
  the DA-only `\\dc\admin_flag` share (flag 17 pass-the-hash target), and
  sets the Project-L `info` attribute to `FLAG{2f8b4a6c1d9e7053}`.
- **`shifter/development/range/polaris-test-kali`** Secrets Manager entry
  (Windows side) — just a note: the Administrator password
  (`CortexSavesTheDay!`) is hard-coded in the terraform variable
  `a2_administrator_password` because the range is dev-only and the CTF
  narrative depends on participants reading that cleartext from
  walkthrough/shifter portal metadata.

### Fixed

- **POLARIS compose DNS now has recursion + forwarders** (named.conf in
  `scenario-dev/polaris/build/dns/`). Previously `recursion no`, so every
  non-`boreas.local` / non-`boreas-systems.ctf` lookup from inside the
  compose containers returned SERVFAIL — which meant `apt update` inside
  a14-kali (and any other container) could not resolve external archives.
  Recursion is scoped to `172.20.0.0/16 + 127.0.0.1` via `allow-recursion`
  so this server cannot be used as an open resolver from outside the range.
- **`dc01.boreas.local` DNS record.** Zone files in `build/dns/` now point
  at `10.1.100.11` (the new in-range A2 EC2) instead of the legacy
  `10.100.0.4` external-GCP-VM placeholder. `00-range-access-docker.md`,
  `flags-07-19-front-office.md`, `isolation-smoketest.sh`, and
  `A2-smoketest.sh` all updated to match.
- **a14-kali PDF extraction tools.** `a14/Dockerfile` now installs
  `poppler-utils` + `python3-pdfminer` at image-build time AND drops a
  `/etc/profile.d/polaris-tools.sh` that puts `/opt/tools/bin` on PATH for
  interactive SSH / `docker exec` login shells. Previous a14 image had
  `pdfminer.six` installed inside `/opt/tools/` but `pdf2txt.py` was not on
  PATH in login shells (the `ENV PATH=` line in the Dockerfile only
  affects the PID 1 environment), so the flags 1/8/9/13/19 PDF-extraction
  steps documented in the walkthroughs silently fell back to a hand-rolled
  ASCII85+Flate decoder. Symlinks `/usr/local/bin/pdf2txt.py` and
  `/usr/local/bin/impacket-smbclient.py` added for stability.
- **Flag 15 walkthrough wording** (`flags-07-19-front-office.md`) — now
  explicitly says Kowalski's "creds backup" email is in **INBOX** (he sent
  to his own address; Dovecot has no Sent folder for that user). Previous
  "(Kowalski sent it to himself)" parenthetical was ambiguous and led at
  least one walkthrough-runner to check a non-existent Sent folder first.
- **Flag 31 walkthrough path** (`flags-31-36-bunker.md`) — the
  pre-populated `/root/scan_results.txt` short-circuit is now the primary
  step; the live `nmap -sV -p 502,9100 172.20.50.0/24` is documented as
  the fallback because the service-version probe is slow over the splice
  pivot and can time out under automation.

## [3.87.0] - 2026-04-13

### Added

- **`scripts/polaris-aws-range/`** — terraform + bootstrap for a one-VM
  manual POLARIS range inside the existing dev range VPC. Creates a new
  `/28` subnet (`10.1.100.0/28`) with a dedicated route table that
  bypasses the domain-filtered Network Firewall (so `docker build` and
  `apt install` can reach the internet during bake), one `m5.2xlarge`
  Ubuntu instance, a permissive SG allowing VPC-internal + portal-peering
  ingress on 22/3389, and an instance profile that can read the polaris
  build tarball + SSM session manager.
- **`scripts/polaris-aws-range/user_data.sh.tpl`** — cloud-init bootstrap
  that installs Docker + the v2 compose plugin binary, masks host `ssh`
  / `apache2` / `smbd` / `vsftpd` / `xrdp` / `mysql` services (the
  `shifter-ubuntu-*` base AMI ships them pre-installed and they compete
  for the ports we need to publish from the Kali container), pulls the
  polaris build tarball from S3, writes a `docker-compose.override.yml`
  that publishes a14-kali's 22 + 3389 to the host, runs
  `docker compose up -d`, and starts everything under a systemd unit.
- **`scripts/polaris-aws-range/register_range.py`** — idempotent manual
  range registration script: fetches DB + Django + Cognito secrets from
  Secrets Manager, soft-destroys any stale ready-range rows for the dev
  user, and creates engine `Range` + cms `RangeInstance` rows pointing at
  the polaris VM with an attacker (kali) instance spec. Runs inside the
  portal docker container via SSM Run Command so no portal code change
  is needed to turn a hand-built range into a portal-visible one.
- **S3 bucket** `shifter-polaris-bake-158151907940` — byte-stable
  `polaris/build-v1.tar.gz` of the `scenario-dev/polaris/build/` tree
  (includes `_shared/` GPG chain and research-analyst keypair so flag 30
  stays deterministic across rebuilds).
- **Secrets Manager entry** `shifter/development/range/polaris-test-kali`
  holds the RSA private key the portal SSHes with. Secret ARN matches
  the `shifter/*/range/*` wildcard the `dev-portal-ec2-role` already
  allowlists — no IAM policy change required.

## [3.86.0] - 2026-04-12

### Fixed

- **Flag 37 walkthrough payload** — the documented sudo-arg-injection
  example `--host "x; cat /root/.scada/hmi.json"` did not actually
  work because `scada_diag.sh` `eval`s `curl -sS http://$HOST:8080/ping`
  — so without a trailing comment the injection expands into
  `cat /root/.scada/hmi.json:8080/ping` and `cat` errors on the
  concatenated filename. Walkthrough now shows the working form with
  the trailing `#` that comments out the `:8080/ping` suffix.
- **A9 nmap service-detection** — `nmap -sV -p 502,9100 172.20.50.0/24`
  in flag 31 step 1 failed with `could not locate nse_main.lua`
  because the alpine `nmap` package doesn't ship the NSE data files
  as a dependency. A9 Dockerfile now adds `nmap-scripts` alongside
  `nmap`, so `-sV` runs cleanly. Pre-populated `/root/scan_results.txt`
  remains as the sanctioned alternative.
- **Flag 30 step 2 (`gpg-agent.conf` read)** — walkthrough previously
  said `cat /home/e.vasik/.gnupg/gpg-agent.conf` without naming an
  account. `~e.vasik/.gnupg/` is mode 700, so the A16 `research-analyst`
  key cannot read it. Walkthrough now explicitly pivots to A6 as
  `e.vasik` (`Reactor#Core9`, discoverable from the A1 mailbox trail)
  for that hop.
- **Flag 26 openpyxl host** — walkthrough previously said "in Python:
  openpyxl → check sheet_state" without specifying where Python runs.
  A16 does not ship openpyxl; A6 does. Walkthrough now explicitly says
  run the Python snippet from inside the SSH session on A6 as
  `p.nielsen` (where `python3-openpyxl` is preinstalled), with a note
  that `scp`-ing the xlsx back to Kali is the fallback if the tester
  prefers to parse locally.

### Changed

- **A7 Gitea stripped from the `shared` network — lab-only.** Previously
  A7 was multi-homed on `shared` + `lab`, letting Kali reach Gitea
  directly and bypass the Lab pivot for flags 24 and 29. A7 now only
  lives on `lab` (172.20.30.20); every Gitea interaction must go
  through the A16 research-analyst pivot, matching every other Lab
  asset. `docker-compose.yml`, DNS zone files
  (`dns/db.boreas.local`, `dns/db.boreas-systems.ctf` both now resolve
  `git.boreas.local` → 172.20.30.20), walkthrough flag 24/29/30 steps,
  bunker walkthrough prerequisites (bunker flags now explicitly
  require A7 content to have been cloned earlier during the Lab
  phase, since A9 and Kali cannot reach A7), `00-range-access-docker.md`
  reachability table, and `isolation-smoketest.sh` all updated.
- **A16 Dockerfile** gains `git`, `curl`, and `gnupg` so it can run the
  full A7 cloning + flag 30 GPG decrypt chain as the on-ramp container.
  `run-all-smoketests.sh` now routes the A7 smoketest through
  `a16-research-analyst` instead of `a14-kali`.
- **A14 smoketest** no longer asserts A7 Gitea is directly reachable
  from Kali (that's a design-forbidden path now); it asserts A15,
  A16, and the splice-link to A9 instead.
- **Fixed the Gitea anonymous-clone false-negative** in
  `A7-smoketest.sh`: the previous "anonymous clone of private repo
  should fail" assertion was being evaluated from `a14-kali` which had
  cached credentials in its filesystem — moving the runner to the
  freshly-built `a16-research-analyst` container makes the anonymous
  clone actually anonymous, so the hygiene check passes correctly.

### Proofs

- **Full smoketest sweep**: 18 / 18 asset sweeps PASS (including A7
  now), isolation smoketest 90 / 90 boundary assertions PASS.
- **Lab full E2E via A16**: all 12 Lab flags (38 + 20–30) recovered
  end-to-end from inside a14-kali, pivoting only via the real
  participant chain `SSH p.shah@analyst01 → {ssh, psql, git, gpg}`.
  No docker-exec into any Lab target. Flag 30's full A6 → A8 → A7 →
  gpg-decrypt chain works through A16 including pulling the encrypted
  file from research-analyst on A6, psql as `vasik` (Reactor#Core9)
  for the compartment_b key blob, `.netrc`-authed git clone of
  `aurora/weapons-integration` for the passphrase, and gpg
  `--import` + `--decrypt` all inside Shah's shell on A16.
- **SCADA chain via A15**: flag 37 / 18 / 19 recovered end-to-end via
  `SSH s.ivanov@ops-eng01` → sudo-arg-injection → `hmi.json` loot →
  inline Modbus writes from the A15 shell → critical-failure page.

## [3.85.0] - 2026-04-12

### Added

- **POLARIS CTF range: A15 Ops Engineer Workstation** and **A16 Research
  Data Analyst Workstation** introduced as dedicated Front Office pivot
  hosts, with two new flags (37, 38) that gate the SCADA and Lab chains
  respectively. Total flag count: 36 → 38.
  - A15 (`ops-eng01.boreas.local`, 172.20.10.50 + 172.20.40.20) — Sergei
    Ivanov's workstation. Multi-homed on `corporate` + `scada`. Attack
    chain: OSINT (A0 leadership + A4 HR org_chart) → `Welcome1` default
    password → SSH as `s.ivanov` → `sudo -l` reveals
    `/opt/ops/scada_diag.sh` NOPASSWD → sudo arg-injection exploits the
    unquoted `curl` sink → read root-owned `/root/.scada/hmi.json` which
    contains both `svc-scada / Sc@da#2025!` and **flag 37**
    (`FLAG{5c3e7a9f1b8d4602}`, Hard, 200pts, M3). A15 has `pymodbus`
    preinstalled so flags 18 and 19 execute from inside the A15 shell.
  - A16 (`analyst01.boreas.local`, 172.20.10.60 + 172.20.30.60) — Priya
    Shah's research data analyst workstation. Multi-homed on `corporate`
    + `lab`. Deliberately simpler chain than A15 (no privesc): OSINT
    (A4 HR only, NOT A0) → `Welcome1` default → SSH as `p.shah` → read
    `~/.reports/ANALYST_TOKEN` for **flag 38**
    (`FLAG{8b2d4f1a0c5e7396}`, Medium, 100pts, M2). Home dir also
    carries `~/.pgpass` (lab_general), a passphrase-less SSH key +
    `~/.ssh/config` alias for `research-analyst@eng-ws01.boreas.local`
    on A6, and an example `daily_integration_report.py`.
  - New `research-analyst` read-only posix account on A6 (key-only
    auth; public key pre-generated at `_shared/research-analyst-key/`
    and COPY'd into A6 during image build). Can read `/opt/builds/`,
    `/home/r.tanaka/simulations/standard/`, and `/tmp/.deleted/`.
    **Cannot** read `/home/r.tanaka/simulations/midnight/`,
    `/home/p.nielsen/designs/`, or `/home/jenkins/.credentials` (now
    chmod 600). Flags 25, 26, 28 still require independent
    nielsen/tanaka cred discovery; flag 20 still requires jenkins.
- **New smoketests**: `tests/smoketests/A15-smoketest.sh` walks the
  flag 37 compromise chain from inside `a14-kali`, validates the
  sudo-arg-injection root path, extracts the hmi.json loot, and
  proves A15 → `scada-gw` HMI + Modbus reachability.
  `tests/smoketests/A16-smoketest.sh` walks the flag 38 chain, then
  validates A16 → A8 psql and A16 → A6 `research-analyst` SSH pivots
  plus the read/no-read scope of the `research-analyst` account.

### Changed

- **A3 intranet reduced to `corporate`-only.** Legacy multi-home onto
  `scada` and `lab` (used as a one-box pivot shortcut) has been
  removed from `docker-compose.yml`. A3 is once again what its
  hostname says: a corporate wiki server. SCADA reach is now A15,
  Lab reach is now A16.
- **`svc-scada` credential single-sourced through A15.** The
  `service_account_vault.pdf` on A4 no longer lists the `svc-scada`
  password in plaintext — the row now points at "held by ops, see
  ivanov" as a breadcrumb. The only participant path to
  `Sc@da#2025!` is the flag 37 privesc chain.
- **A4 org chart updated** to include Sergei Ivanov (Ops Engineer —
  Plant Systems) and Priya Shah (Senior Research Data Analyst). These
  are the HR-share breadcrumbs for A15 + A16 discovery.
- **A1 mail server seeded** with Sergei Ivanov's inbox (HR
  welcome-back reset confirmation + Dariusz thread about the SCADA
  cred cache). `s.ivanov / Welcome1` added to the A1 user list and
  Dovecot passdb.
- **A0 leadership page** adds Sergei Ivanov under a new "Department
  Leads" section; contact page adds a Plant Operations mailto.
- **A6 entrypoint** creates the `research-analyst` user, drops the
  pre-generated public key into its `authorized_keys`, enforces
  `jenkins/.credentials` at mode 600, and makes `/tmp/.deleted/`
  world-traversable for the flag 30 chain.
- **Flags 18 + 19 walkthrough** rewritten to run from inside the A15
  SSH session after flag 37 rather than hand-waving a pivot. All
  Modbus writes, HMI fetches, and maintenance-manual lookups are
  routed through A15 or Kali as appropriate.
- **Flags 20–30 walkthrough** rewritten to use A16 as the Lab
  on-ramp. Each flag section now names its specific SSH/psql target
  and which account is required. Flag 38 section added at the top
  as the Lab entry point.
- **Isolation smoketest** updated for the new topology: A3 no longer
  reaches scada/lab; A15 reaches corporate+scada only; A16 reaches
  corporate+lab only; A14 has permitted reach to A15 + A16 on
  corporate and to A9 via the pre-wired `splice-link`.
- **`run-all-smoketests.sh`** updated to route the A5 smoketest
  through `a15-ops-eng`, and A6/A8 smoketests through
  `a16-research-analyst`, instead of `a3-intranet`. A15 and A16
  smoketests added.
- **Design docs**: new `design/assets/A15-ops-workstation.md` and
  `design/assets/A16-research-analyst.md`. `design/architecture.md`,
  `design/assets/A3-web-app.md`, `design/assets/A5-scada-generator.md`,
  `design/assets/A6-engineering-workstation.md`, and
  `design/shared-constants.md` updated to reflect the new topology,
  flag table (38 total), pivot ownership, and employee credential
  index.

## [3.84.0] - 2026-04-12

### Fixed

- **Walkthroughs brought current to live range state.** The four
  flag-group walkthroughs and the range-access doc came over from
  `shifter-k8s/temp/tests/smoketests/` in the last consolidation
  and had drift from multiple old test environments baked in.
  All corrections:
  - `00-range-access.md` deleted — fully stale, documented the old
    VM-based test environment (localhost ports, loose Python
    processes, `/tmp/*-content/` file paths).
  - `00-range-access-docker.md` — Administrator row updated to say
    "use PTH" with pointer to `smbclient.py -hashes`; Gitea
    `e_vasik` password `TestPass123!` → `Reactor#Core9`;
    credentials table reconciled with actual AD password reuse;
    "Managing the Range" section rewritten to use the new
    `tests/setup.sh` / `tests/reset.sh` / `tests/run-all-smoketests.sh`
    orchestration + `-p range` project naming against the compose
    file at `build/docker-compose.yml`.
  - `flags-01-06-osint.md` flag 2: `org_chart.txt` → `org_chart.pdf`
    with `exiftool`/`pdfinfo` Author extraction; flag 6: quarterly
    and annual reports `.txt` → `.pdf` with `pdftotext`/`pdf2txt.py`
    extraction path.
  - `flags-07-19-front-office.md` flag 16: removed
    `/tmp/badge.csv` parenthetical leftover from the VM env;
    flag 17: rewritten around pass-the-hash (`smbclient.py -hashes`)
    since Administrator's cleartext is random.
  - `flags-20-30-lab.md` flags 24, 29, 30: Gitea password
    `TestPass123!` → AD-pattern passwords (`e_vasik:Reactor#Core9`,
    `d_kowalski:P@ssw0rd123`) with `.netrc` guidance to dodge
    URL-encoding `#`/`@`.
  - `flags-31-36-bunker.md` — every IP reference corrected.
    Bunker network was documented as `172.20.40.x` (wrong,
    that's actually the SCADA network) and controllers as
    `10.10.40.x` (wrong, that's from the VM env). All fixed to
    `172.20.50.x` / hostnames (`tail-ctrl`, `leg-ctrl`,
    `arms-ctrl`, `brain-main`) with `splice-relay` at 172.20.50.5.
    Scan range `10.10.40.0/24` → `172.20.50.0/24`.

- **Build-content IP drift** in parallel with the walkthroughs:
  - `A4-file-share/build_documents.py`: network_diagram.pdf VLAN
    subnets and server_inventory.xlsx per-host IPs switched from
    `10.10.x.x` VM-era IPs to `172.20.x.x` docker network IPs so
    the OSINT content participants find matches what they'll
    actually route to.
  - `A1-mail-server/build_mail.py`: Kowalski's SCADA VLAN ticket
    email `scada-gw.internal (10.10.40.10)` → `(172.20.40.10)`.
  - `A13-brain/server.py`: `subsystems` command output — the
    controller/brain table showing connected hosts — switched
    from `10.10.40.x` to `172.20.50.x`.
  - `A9-splice-landing/modbus_client.py` help text examples and
    `README.txt` relay description: `10.10.40.x` → `172.20.50.x`.
  - `A9-splice-landing/scan_results.txt` (the pre-populated JTF-2
    nmap output participants find on A9): full IP rewrite.

- **a1-mail Roundcube serving at web root.** The Debian roundcube
  package's `/etc/apache2/conf-enabled/roundcube.conf` ships the
  `Alias /roundcube` line commented out, so a fresh install
  serves the Apache default page at `/` with Roundcube
  effectively unreachable. `a1/Dockerfile` now changes the
  default site DocumentRoot to `/var/lib/roundcube/public_html`
  and adds a roundcube-root conf via `a2enconf` so
  `http://mail.boreas.local/` lands directly on the Roundcube
  login page (required by the A1 smoketest and the walkthrough).

### Changed

- **Design doc content-directory paths updated** (approved by
  user). 15 design docs under `design/assets/A*.md` had
  "Content directory: `docs/ctf/mechag/A*-*/`" lines left over
  from before the consolidation. All 15 rewritten to point at
  `scenario-dev/polaris/build/A*-*/`. `benchmark-report.md`
  similarly rewritten (design doc filenames are now at
  `scenario-dev/polaris/design/assets/A*.md` instead of
  `docs/ctf/mechag/A*.md`).

- **`tests/setup.sh` + `tests/reset.sh`** taught about the new
  nested layout: `COMPOSE_FILE` env override with default
  `$RANGE_DIR/build/docker-compose.yml` and legacy flat-layout
  fallback to `$RANGE_DIR/docker-compose.yml`. Project name
  explicitly pinned to `range` via `-p range` so network and
  container names stay stable across layout moves.

### Verified

- Golden rebuild + full sweep against the new nested layout on
  `ctf-range-builder`: **16/16 PASS**, `NORTHSTORM full range: PASS`.
- Final `reset.sh` run leaves a5/a10/a11/a12/a13 in clean
  pre-unlock state for participant use.

## [3.83.0] - 2026-04-12

### Changed

- Consolidated all POLARIS / NORTHSTORM scenario work into
  `scenario-dev/polaris/`. Prior to this, scenario artifacts
  were scattered across `docs/ctf/`, `docs/ctf/mechag/`, and
  a sibling `shifter-k8s/temp/` worktree. New layout:
  - `scenario-dev/polaris/design/` — authoritative spec (source
    of truth): `architecture.md`, `range-diagram.md`,
    `benchmark-report.md`, `shared-constants.md`, plus per-asset
    design docs under `design/assets/`.
  - `scenario-dev/polaris/build/` — `docker-compose.yml`,
    `ctfd-challenges.json`, `dns/`, `a0/`-`a14/` (Dockerfiles +
    runtime configs), and `A0-boreas-website/`-`A14-kali/`
    content dirs (intact to avoid touching Dockerfile COPY paths).
  - `scenario-dev/polaris/tests/` — `setup.sh`, `reset.sh`,
    `run-all-smoketests.sh`, `isolation-smoketest.sh`,
    flattened `smoketests/` (A0-smoketest.sh … A14-smoketest.py),
    and `walkthroughs/` (copied from `shifter-k8s/temp/tests/smoketests/`
    — the four flag-group happy-path guides plus range-access
    prereqs).
  - `scenario-dev/polaris/notes/` — spike notes and
    HANDOFF/BUILD-TODO (copied from `shifter-k8s/temp/`).
  - `scenario-dev/polaris/README.md` — entry point with layout
    map and "getting started" deploy/test commands.
- Moves were `git mv` wherever possible to preserve history.
  Files from `shifter-k8s/` are copies (different repo, no
  shared git history).
- `run-all-smoketests.sh` updated: new variables `SMOKETESTS_DIR`,
  `RESET_SCRIPT`, `ISOLATION_SCRIPT` with sane defaults for the
  new layout and fallback to the old flat layout if detected.
  Per-test paths switched from `<Content-Dir>/smoketest.ext`
  to `A<N>-smoketest.ext` reflecting the flattened tests/smoketests/.
- `docs/ctf/` and `docs/ctf/mechag/` are now empty and removed.

### Known drift (deferred, needs approval per design-is-source-
of-truth rule)

- 15 design docs under `design/assets/A*.md` still reference
  `docs/ctf/mechag/A*-*/` as the "Content directory". Those
  references are now stale — the content dirs moved to
  `scenario-dev/polaris/build/A*-*/`. Paths are semantic per
  feedback_design_is_source_of_truth.md so they need user
  approval before editing the design to match the new layout.

## [3.82.0] - 2026-04-12

### Fixed

- Close out remaining repo path drift for a1, a3, a4, a5. These
  four Dockerfiles still used the old single-context build
  pattern (`COPY server.py`, `COPY build_mail.py`, etc) with
  files that only existed on the range VM via duplication, not
  in the repo. Migrated all four to parent-context builds to
  match a0/a6/a7/a8/a9/a10/a11/a12/a13/a14:
  - `a1/Dockerfile`: COPYs from `A1-mail-server/build_mail.py`
    and `a1/{postfix-main.cf,dovecot-local.conf,entrypoint.sh}`.
  - `a3/Dockerfile`: COPYs from `A3-web-app/server.py`.
  - `a4/Dockerfile`: COPYs from `A4-file-share/build_documents.py`
    and `a4/{smb.conf,entrypoint.sh}`.
  - `a5/Dockerfile`: COPYs from `A5-scada-generator/server.py`.
  - `docker-compose.yml`: a1-mail, a3-intranet, a4-fileshare,
    a5-scada all switched to `context: .` with `dockerfile:
    ./aN/Dockerfile`. All 14 docker-managed services in
    docker-compose.yml now use the parent-context convention
    (dns is self-contained and stays `build: ./dns`).

  Golden rebuild verification: full teardown,
  `docker compose build` from clean, `docker compose up -d`,
  `run-all-smoketests.sh` → 16/16 PASS, final `reset.sh` for
  clean participant state. Range is now reproducible from a
  fresh repo clone for every service.

## [3.81.0] - 2026-04-12

### Added

- `docs/ctf/mechag/setup.sh`: NORTHSTORM range setup orchestrator.
  Runs `docker compose build` + `up -d`, waits for all 15 services
  to report Running, then polls key readiness ports (a7 gitea
  3000, a1 IMAP 143, a3 80, a4 445, a0 80) via a14-kali before
  returning. Single entry point to take a freshly-synced
  `/home/atomik/range/` to a live range.
- `docs/ctf/mechag/reset.sh`: sticky-state reset. Force-recreates
  the five services with one-shot unlock state (a5-scada thermal
  runaway, a10/a11/a12 flag-register unlocks, a13-brain for
  parity), then polls each one's primary port on its own
  container's localhost until the embedded server is actually
  accepting connections. localhost polling avoids the
  cross-network unreachability problem where a single probe
  container couldn't see every docker bridge.
- `docs/ctf/mechag/run-all-smoketests.sh`: full-range test
  sweep orchestrator. Calls reset.sh pre-flight, then copies
  each per-asset smoketest into its designated runner container
  (a14-kali / a3-intranet / a9-splice) in the correct pivot
  order, executes with the correct interpreter (bash / python3 /
  sh), captures per-asset PASS/FAIL, then runs the host-side
  isolation smoketest, and aggregates a final summary. Proven
  deterministic with three consecutive 16/16 PASS runs against
  the live range (15 asset smoketests + isolation sweep = 475
  underlying checks).

### Changed

- VM cleanup pass on `/home/atomik/range/`: removed stale
  file duplicates left over from before the parent-context
  Dockerfile migration. Top-level copies of build-a6-content.sh
  and build-gpg-chain.sh, plus per-asset copies of build
  scripts / server.py / 01-init.sql / bare-repos.tar.gz /
  bootstrap.sh / content files that now live in the A*-
  content directories. `/home/atomik/range/a*/` now contains
  only the Dockerfile and runtime configs.

## [3.80.0] - 2026-04-12

### Added

- `docs/ctf/mechag/isolation-smoketest.sh`: cross-cutting
  network isolation smoketest (70 checks) that validates the
  full NORTHSTORM topology boundary enforcement. Runs from
  the range host. For every (source, target) pair the design
  specifies, tests TCP reachability via `docker exec` +
  python3 sockets. Every designed pivot path proven to work,
  every forbidden path proven to fail. Covers a14-kali
  (shared+corporate), a3-intranet (THE PIVOT: corporate+
  scada+lab), a7-gitea (shared+lab), a1-mail/a4-fileshare
  (corporate only), a6-workstation (lab only), a5-scada
  (scada only), and a9-splice/a13-brain (bunker-ot only).
  Result: 70/70 PASS. The docker bridge topology enforces
  the design boundaries purely by network attachment,
  without iptables ACLs.

## [3.79.0] - 2026-04-12

### Fixed

- A14 Kali repo path drift (last of the A* assets):
  `a14/Dockerfile` COPYs content files from context root but
  they live in `A14-kali/`, and it referenced `modbus_client.py`
  which only exists in `A9-splice-landing/`. Moved `a14-kali`
  compose build context to `.` with `dockerfile: ./a14/Dockerfile`
  and updated all Dockerfile COPY paths. Now builds from a
  fresh repo checkout.

### Added

- `docs/ctf/mechag/A14-kali/smoketest.sh`: A14 attack platform
  readiness smoketest (47 checks). A14 has no flags (it's the
  participant's attack box, not a target) so the smoketest
  verifies the platform is ready for use: home directory
  content (README, mission_brief.pdf/.txt, flag_submit.sh,
  modbus_scan.py, Claude system prompt), kali user and
  sshd/xrdp services running, standard Kali offensive tools
  (nmap, msfconsole, sqlmap, john, hashcat, gobuster, ffuf,
  nc, curl, wget, python3, smbclient), full Impacket suite
  at /opt/tools/bin (GetUserSPNs, secretsdump, psexec,
  smbclient.py, lookupsid), Python libraries (pymodbus,
  impacket, pdfminer.six, openpyxl, pdf2txt.py), Claude Code
  CLI, TCP reachability of all 7 permitted targets (A0, A1,
  A3, A4, A7, A2 via GCP, DNS), internal DNS resolution, and
  AXFR zone transfer returning the _flag TXT record (flag 5
  discovery path).

## [3.78.0] - 2026-04-12

### Fixed

- A13 repo path drift: `a13/Dockerfile` COPYs `server.py`
  from context root. Moved `a13-brain` compose build context
  to parent dir.

### Added

- `docs/ctf/mechag/A13-brain/smoketest.py`: A13 Mecha-Godzilla
  brain end-to-end smoketest (17 checks). Runs from a9-splice.
  Executes the full boss chain: TCP connect on port 9100,
  receive 8-byte binary challenge, derive XOR key via
  `SHA256("AHS-T-00482" + "AHS-L-00483" + "AHS-A-00484")[:8]`
  (from A10/A11/A12 serials), send handshake response,
  authenticate as `vasik` with `BRAIN_AUTH_TOKEN` from A7
  navigation-controller config (not vasik's AD password),
  run `status` and extract flag 35 from the SYSTEM
  AUTHORIZATION TOKEN line, run `schematic` verifying
  LEVIATHAN ASCII art, run `ai status` verifying DORMANT
  state awaiting primary power, reject wrong override code,
  and submit the full override code `7741-MN07-AL42`
  (assembled from A0 registration / A6 MIDNIGHT-7 sim ID /
  A8 assembly log metadata) to extract flag 36 with the
  OPERATION NORTHSTORM COMPLETE seizure message.

## [3.77.0] - 2026-04-12

### Fixed

- A12 repo path drift: `a12/Dockerfile` COPYs `server.py`
  from context root. Moved `a12-arms` compose build context
  to parent dir.

### Added

- `docs/ctf/mechag/A12-arms-controller/smoketest.py`: A12
  arms controller end-to-end smoketest (17 checks). Runs
  from a9-splice. Verifies default register reads (joints,
  actuator force, mode 0=stowed, primary effector status=0
  offline / max=2400 MW / draw=1800 MW, kinetic caliber
  500mm, 12 rounds/mag), flag zero pre-unlock, wrong
  challenge write rejected before diagnostics, diagnostics
  enable via coil 50, rolling nonce appears on input reg 60
  (4-digit), XOR nonce with PO-2847 (cross-zone intel from
  A4), confirmation readback reg 201 = 1, and ASCII decode
  of reg 100-121 matching `FLAG{f0d8b2e6a4c71935}`.

## [3.76.0] - 2026-04-12

### Fixed

- A11 leg controller Modbus server was silently dropping
  response PDUs for any read that spanned the ankle position
  registers. Root cause: `LEFT_JOINTS` and `RIGHT_JOINTS`
  initialised ankle position/target to `-5` (degrees). Modbus
  holding registers are uint16; pymodbus 3.12 refuses to pack
  negative Python ints and fails silently with no response,
  no log entry. Changed init to `[0, 0, 15, 15, 5, 5]`
  (leg straight, ankles neutral). Confirmed A9's earlier
  probes happened to use reads that didn't cross the negative
  offset, which is why this only surfaced under the A11
  smoketest's exhaustive register reads.
- A11 repo path drift: `a11/Dockerfile` COPYs `server.py` from
  context root. Moved `a11-leg` compose build context to
  parent dir.

### Added

- `docs/ctf/mechag/A11-leg-controller/smoketest.py`: A11 leg
  controller end-to-end smoketest (19 checks). Runs from
  inside a9-splice. Verifies default register reads (joints,
  hydraulic pressures, gait mode 0=stationary, step length
  4200mm, cycle 85s, per-leg mass 24000t, max force 200t
  matching PO-2847), flag registers zero pre-unlock, wrong
  sequence rejection, correct gait sequence 0->1->2->0 to
  reg 30 releasing calibration code 4783 on input reg 60,
  challenge write to reg 99 with calibration code, and
  ASCII decode of reg 100-121 matching `FLAG{c7a1e3f9d0b52864}`.

## [3.75.0] - 2026-04-12

### Fixed

- A10 repo path drift: `a10/Dockerfile` COPYs `server.py` from
  context root but the file lives in `A10-tail-controller/`.
  Moved `a10-tail` compose build context to parent dir.

### Added

- `docs/ctf/mechag/A10-tail-controller/smoketest.py`: A10 tail
  controller end-to-end smoketest (13 checks). Runs from inside
  a9-splice (bunker OT entry point). Verifies default register
  reads (motor positions, torque, mode=1 balance, length=120m,
  mass=8500t), flag registers zero pre-unlock, the flag 32
  unlock sequence (write reg 20=3 diagnostic mode, then write
  reg 99=482 serial-derived challenge), ASCII decode of
  registers 100-121 matching `FLAG{9b3e7c1d0f5a2846}`, mode
  reset on wrong challenge, and all 10 motor enable coils ON.
  Device identification test deferred to A9 smoketest which
  already covers A10/A11/A12 via modbus_client.py devid.

## [3.74.0] - 2026-04-12

### Fixed

- A9 repo path drift (same pattern as A6/A7/A8):
  `a9/Dockerfile` COPYs README, scan_results, modbus_client.py
  from context root but they live in `A9-splice-landing/`.
  Moved `a9-splice` docker-compose build context to `.` with
  `dockerfile: ./a9/Dockerfile` so the build works from a
  fresh repo checkout.

### Added

- `docs/ctf/mechag/A9-splice-landing/smoketest.sh`: A9 splice
  landing box end-to-end smoketest (17 checks). Runs from
  inside a9-splice (the only container on bunker-ot so no
  pivot available). Verifies the JTF-2 field relay artifacts
  (README POLARIS FIELD RELAY text, scan_results nmap dump,
  modbus_client.py), the field tool set (python3, nmap,
  ncat, tcpdump, ssh, pymodbus), TCP reachability of all 4
  bunker hosts (A10-A13), Modbus FC 43 device identification
  queries against A10/A11/A12 returning the expected
  ProductName values (AHS-TAIL-7741, AHS-LEG-MN07,
  AHS-ARM-AL42), and the flag 31 concatenation answer string
  `AHS-TAIL-7741AHS-LEG-MN07AHS-ARM-AL42` that CTFd accepts.

## [3.73.0] - 2026-04-12

### Fixed

- A8 repo path drift (same pattern as A6/A7): `a8/Dockerfile`
  COPYs `01-init.sql` from context root but the file lives in
  `A8-research-database/`. Moved `a8-database` docker-compose
  build context to `.` with `dockerfile: ./a8/Dockerfile` so
  the build works from a fresh repo checkout.

### Changed

- `a3/Dockerfile`: added `postgresql-client` so a3-intranet can
  run `psql` against A8 as the designed pivot host (A8 is on
  lab VLAN 30, not reachable from a14-kali directly).

### Added

- `docs/ctf/mechag/A8-research-database/smoketest.sh`: A8
  research database end-to-end smoketest (16 checks). Runs
  from a3-intranet via psql. Verifies lab_general auth via
  A3 /.env discovery path, compartment isolation
  (lab_general denied on compartment_b/c, lab_mfg denied on
  compartment_b), flag 21 in compartment_a.structural_specs
  frame_dorsal_plate row, both flag 27 paths (vasik direct
  via AD password reuse + SECURITY DEFINER SQL injection in
  research_public.search_research as lab_general) with
  verification that the function actually has SECURITY
  DEFINER, flag 28 via JSONB path
  `metadata->'integration'->>'flag'` in compartment_c.assembly_log
  as lab_mfg (A6 .pgpass pivot), A13 override-code piece
  AL42 via `metadata->'integration'->>'code'`, and A6 flag 30
  chain prerequisite (Vasik GPG private key base64 blob in
  compartment_b.key_storage).

## [3.72.0] - 2026-04-12

### Fixed

- A7 Gitea bootstrap drift (design vs build mismatch):
  - `bootstrap.sh` user creation was missing `login_name` in the
    POST payload, so Gitea stored users with empty login_name
    and basic-auth failed ("user's password is invalid"). Added
    `login_name` + `source_id` to the POST, plus a PATCH fallback
    that corrects existing users on re-runs.
  - Gitea user passwords were all hardcoded to `TestPass123!`
    with no discovery path. Updated to match the A1/A2/A6 AD
    credentials (e_vasik/Reactor#Core9, r_tanaka/SimEngine#42,
    p_nielsen/Hydraulics1, m_webb/Welcome1, d_kowalski/P@ssw0rd123)
    so the password-reuse pattern participants discover in the
    Front Office also unlocks Gitea. k_yamamoto and f_okoye
    (Lab-Access members without prior AD mapping) get
    Sensor2025 / AIModel2025 respectively.
- A7 repo path drift: `a7/Dockerfile` COPYs `bootstrap.sh` and
  `bare-repos.tar.gz` but they live in `A7-source-repo/`. Moved
  `a7-gitea` docker-compose build context to `.` with
  `dockerfile: ./a7/Dockerfile` and updated COPY paths so the
  image can be built from a fresh repo checkout.

### Added

- `docs/ctf/mechag/A7-source-repo/smoketest.sh`: A7 end-to-end
  smoketest (20 checks) runnable from a14-kali (A7 is
  multi-homed on shared+lab so a14-kali reaches it directly via
  shared). Verifies Gitea API, public org/repo discovery,
  visibility boundaries (anonymous cannot see `aurora` org or
  its repos; anonymous cannot clone private repos), authenticated
  clone of all 4 aurora repos, flag 24 via `git log -p` on
  navigation-controller removed CI token, flag 29 via
  `git show <parent>:schematic.svg` recovery on leviathan-assembly,
  LEGACY_PASSPHRASE cross-asset breadcrumb for A6 flag 30 in
  weapons-integration/src/crypto_config.py, deploy_combat_ai.yml
  playbook in manufacturing-orchestrator, and password-reuse
  validation for r_tanaka and p_nielsen.

## [3.71.0] - 2026-04-12

### Fixed

- A6 repo drift: `build-a6-content.sh` and `build-gpg-chain.sh`
  existed on the range VM but were never committed to the repo,
  so `a6/Dockerfile` could not build from a fresh clone. Added
  both scripts to `A6-engineering-workstation/` alongside
  `build_cog_xlsx.py`, moved `a6-workstation` docker-compose
  build context to `.` with `dockerfile: ./a6/Dockerfile`, and
  updated the Dockerfile COPY paths so it can reach both the
  build dir (`a6/`) and the content dir
  (`A6-engineering-workstation/`) at build time. Rebuilt and
  recreated a6-workstation on the range successfully.

### Changed

- `a3/Dockerfile`: added `openssh-client`, `sshpass`, and
  `ca-certificates` so a3-intranet functions as a realistic
  post-compromise pivot host. This is the only practical path
  for a14-kali to reach the Lab VLAN (30) and SCADA VLAN (40)
  per the design (A3 is the only asset multi-homed to all
  three). Rebuilt and recreated a3-intranet.

### Added

- `docs/ctf/mechag/A6-engineering-workstation/smoketest.sh`:
  A6 engineering workstation end-to-end smoketest (22 checks).
  Runs from inside a3-intranet and uses SSH pivot to reach
  eng-ws01.boreas.local on lab VLAN 30. Verifies jenkins /
  r.tanaka / p.nielsen logins, flag 20 in jenkins .credentials,
  flag 22 in /opt/builds/latest/reactor_interface_spec, flag 23
  as string in stress_test_44.dat binary (with bipedal
  cross-references in logs 28/31/44), flag 25 in
  MIDNIGHT-7_results.dat plus MN07-INTEG-20251028 simulation
  ID (A13 override code piece), flag 26 in the hidden
  Integration sheet of center_of_gravity_analysis.xlsx
  extracted via stdlib `zipfile`, restricted perms on
  r.tanaka/simulations/midnight and p.nielsen/designs,
  p.nielsen .pgpass A8 cred breadcrumb, flag 30 prerequisites
  (encrypted file + public key + gpg-agent.conf hint), and
  simulation.log narrative content. Flag 30's full decryption
  chain requires A7 passphrase + A8 private key blob so it's
  deferred to the cross-asset verification task.

## [3.70.0] - 2026-04-12

### Added

- `docs/ctf/mechag/A5-scada-generator/smoketest.py`: A5 SCADA
  generator HMI + Modbus PLC end-to-end smoketest (19 checks).
  Runs from inside a3-intranet (the multi-homed corporate+scada
  pivot — A14 cannot reach A5 directly per design). Uses only
  stdlib (socket + urllib) so it needs no pymodbus install in
  the container. Verifies: flag 18 in dashboard footer;
  architecture page reveals Modbus port 502 / HR 100 interlock
  / HR 200 maintenance key; system logs contain D. Kowalski
  sensor drift incident; `svc-scada` / `Sc@da#2025!` auth gated
  on /control with wrong-password rejection; raw Modbus TCP
  reads the register map; wrong maintenance key to HR 200 is
  rejected; correct key 7734 bypasses HR 100 interlock and
  disables thermal safety; fuel=100 + cooling=0 triggers
  thermal runaway; flag 19 on the destroyed CRITICAL page.
  Test is idempotent for destroyed containers (extracts flags
  from the final page) but requires a fresh a5-scada container
  to re-prove the attack chain.

## [3.69.0] - 2026-04-12

### Added

- `docs/ctf/mechag/A4-file-share/smoketest.sh`: A4 file share
  end-to-end smoketest (33 checks). Exercises every share ACL and
  every flag path from the a14-kali container: anonymous read of
  Public share and flag 11 from `cafeteria_menu_april.pdf` PDF
  Author metadata; authenticated read of HR as `v.harlan` with
  flag 9 on page 2 of `chen_james_termination.pdf` Case Reference
  Number field; Procurement read with PO-2847 "Special
  Instructions" cross-reference followed into
  `specs/actuator_requirements_v4.pdf` for flag 13; IT share
  anonymous-deny plus `svc-fileshare` (A1 Kowalski creds pivot)
  authenticated read of `backup_verification.log` for flag 15;
  Executive share read. Verifies design-specified share contents
  (network_diagram, server_inventory, PO-3102/3455, reactor
  invoice, org chart, Chen NDA, board minutes, budget summary).

## [3.68.0] - 2026-04-12

### Fixed

- `docs/ctf/mechag/a3/Dockerfile`: create `/var/www/docs` base
  directory with two placeholder files. Without this, both the
  legit `/download?file=*` feature and the design-specified path
  traversal attack (`/download?file=../../../etc/passwd`) failed
  because Python's `os.path.realpath` lexically normalizes `..`
  components on non-existent paths (resolving `/var/www/docs/..`
  to `/var/www` then `/var` etc), so the traversal target
  resolved to `/var/etc/passwd` instead of `/etc/passwd`. Fix
  makes both legit downloads and the intended attack path work.

### Added

- `docs/ctf/mechag/A3-web-app/smoketest.sh`: A3 intranet/wiki
  end-to-end smoketest (24 checks). Verifies public pages,
  username enumeration via `/forgot`, flag 7 in `/.env` and
  `/config.bak` (plus A8 research DB cred breadcrumb),
  admin/admin login, flag 12 in `/wiki/project-coordination`
  HTML comment, all 4 wiki pages, IT KB internal hostnames
  (dc01, scada-gw), LEVIATHAN Assembly Schedule draft visible
  in admin panel with `[MOVED TO SECURE SYSTEM]` body, SQL
  injection via `/search` dumping the users table, and path
  traversal in `/download` reading `/etc/passwd`. Runnable from
  the a14-kali container.

## [3.67.0] - 2026-04-12

### Added

- `docs/ctf/mechag/A1-mail-server/smoketest.py`: A1 end-to-end
  smoketest (27 checks). Exercises IMAP auth for all 6 mailboxes,
  Roundcube webmail login flow, flag 10 retrieval from Kowalski's
  welcome email, flag 8 extraction from Vasik's PDF attachment via
  `pdf2txt.py`, the A4 cred pivot breadcrumb (svc-fileshare /
  F1l3Sh@r3Svc! in Kowalski's "creds backup" email), and every
  narrative thread the design specifies (MIDNIGHT-7, PO-2847,
  Petrov anomaly, Kursk shipment, Novikov reactor). Runnable from
  the a14-kali container.
- `docs/ctf/mechag/A2-domain-controller/smoketest.sh`: A2 Windows
  DC end-to-end smoketest (22 checks). Sweeps AD ports on
  `dc01.boreas.local`, verifies `e.vasik` (A1 password reuse)
  authenticates, Kerberoasts svc-backup via `GetUserSPNs.py`,
  cracks the hash offline with john to `Password1`, DCSyncs the
  Administrator NTLM hash via `secretsdump.py`, pass-the-hashes
  into `\\dc01\admin_flag\` for flag 17, retrieves flag 16 from
  `\\dc01\badgelogs\access_log_march_2026.csv` (Petrov Underground
  Hatch entries), and confirms flag 14 via LDAP `(cn=Project-L)`
  info attribute. Also verifies the Engineering-Support >
  Research-Coordination > Project-L group nesting.

## [3.66.0] - 2026-04-11

### Changed

- A0 Boreas Systems website rebuilt to match `A0-boreas-website.md`
  design spec. Replaces the Flask prototype with `nginx:alpine` serving
  static HTML + reportlab-generated PDFs via a multi-stage build:
  - `a0/Dockerfile` now multi-stage (`python:3.12-slim` content-builder
    feeding `nginx:alpine`), `a0/nginx.conf` added.
  - `docker-compose.yml` a0-website build context moved to `.` with
    `dockerfile: ./a0/Dockerfile` so the image can COPY from both
    `a0/` and `A0-boreas-website/`.
  - `A0-boreas-website/site/`: 14 static HTML pages + CSS (home,
    about, leadership with CSS-gradient avatars, careers,
    careers_apply, contact, news, status, robots.txt, admin/, portal/,
    old/index, old/clients, internal/index).
  - `A0-boreas-website/build_pdfs.py`: reportlab generator for
    org_chart.pdf (flag 2 in Author metadata), boreas-Q1-2025.pdf,
    boreas-Q2-2025.pdf, and boreas-annual-2025.pdf with the Kursk
    Heavy Industries $12,000,000 line buried in 40 expense items.
  - `/internal/` uses a hand-written `index.html` so the annual
    report PDF lives on disk but is not listed — participants must
    fuzz the filename pattern to find it.
  - `A0-boreas-website/smoketest.sh` added — 22-check end-to-end
    attacker-perspective test runnable from the a14-kali container.

### Removed

- `A0-boreas-website/server.py` — obsolete Flask prototype.

## [3.65.0] - 2026-04-11

### Added

- NORTHSTORM CTF range carry-over from the `shifter-k8s` branch onto
  the new `polaris-ctf` branch. Brings in:
  - All 16 mecha-asset build directories under
    `docs/ctf/mechag/{a0..a14,dns}/` (Dockerfiles, entrypoints,
    content, Modbus servers, scenario assets).
  - All 14 design content folders under
    `docs/ctf/mechag/A0-boreas-website/` … `A9-splice-landing/`
    (mission briefs, prepared scripts, fixture data).
  - `docs/ctf/mechag/docker-compose.yml`,
    `ctfd-challenges.json`, `shared-constants.md`.
- A14 Kali container rebuilt against the AWS packer scripts in
  `shifter/packer/scripts/kali/`: `kali-linux-headless` metapackage,
  XFCE + xrdp on 3389, sshd on 22, Claude Code CLI via npm, kali user,
  CTF content overlay under `/home/kali/`. Mission brief generated as
  PDF (`docs/ctf/mechag/A14-kali/mission_brief.pdf`).
- Project DNS sidecar verified end-to-end: AXFR-enabled BIND with
  `boreas-systems.ctf` and `boreas.local` zones, multi-homed onto
  shared/corporate/lab networks.

### Changed

- All 15 mecha asset design docs (`docs/ctf/mechag/A0-…A9-…md`) and
  `docs/ctf/northstorm-architecture.md` updated to match the
  shifter-k8s branch state. A14-kali design no longer specifies
  per-participant rate limiting (false constraint), uses the `kali`
  user (matching the AWS AMI), and documents RDP access in place of
  the ttyd/Guacamole sidecar approach.

## [3.64.0] - 2026-04-11

### Changed
- GCP control-plane deployment cut over to a Helm-based release under `platform/charts/shifter/` with layered values (`values.yaml`, `values-gcp-dev.yaml`, `values-gcp-prod.yaml`) plus bootstrap-generated runtime overrides
- `gdc-bootstrap` now deploys the GCP control plane through the Helm chart instead of the previous raw-manifest path
- `AGENTS.md` has a new "Ground Control Context" section pointing to `.ground-control.yaml`
- `.mcp.json` `ground-control` block now sets `GH_REPO=Brad-Edwards/shifter`

### Added
- `.ground-control.yaml` declaring the `aphelion` Ground Control project, shifter's local lint command (ADR guard), SonarCloud key (`Brad-Edwards_shifter`), and plan rules reference
- `.gc/plan-rules.md` containing ADR guard, guardrail discipline, architectural defaults, and stack-native checker requirements as "plans MUST..." bullets for the `/implement` skill plan phase
- Chart-managed GKE `BackendConfig` for the portal Service so Google Cloud ingress health checks are explicitly pinned to `/health/`
- Environment-scoped Helm values files for `gcp-dev` and `gcp-prod`
- Live bootstrap proof notes for the Helm-based GCP control-plane path in `temp/k8s/gcp-feature-audit.md`
- Terraform-managed GCP Identity Platform auth for `gcp-dev`, including bootstrap-owned first-operator creation and runtime-configured bootstrap admin elevation

### Fixed
- Fixed agentic workshop scenario configs
- GCP bootstrap rerun safety for substrate stages: bootstrap key reuse, secret-version churn avoidance, SSH metadata drift checks, and staged bundle replacement
- Engine migration consistency for `SubnetAllocation` so GCP bootstrap can run the platform database migrations cleanly on a fresh control plane
- GCP bootstrap now leaves a usable externally reachable Shifter platform after control-plane bring-up, including healthy portal ingress and expected Mission Control login redirect behavior
- AWS auth continuity while adding GCP identity support: AWS keeps the existing Cognito/OIDC path and GCP uses a provider-seamed first-party Identity Platform login flow

## [3.63.0] - 2026-04-09

### Added
- Kubernetes manifest validation: kubeconform schema checks and kube-linter security/best-practice enforcement in pre-commit and CI
- Checkov Kubernetes framework scanning for CIS benchmark checks on `platform/k8s/` manifests (soft-fail)
- Cloud factory parity check (`cloud-factory-seam`) enforcing ADR-005-R1: every cloud adapter in `cloud/aws/` must have a counterpart in `cloud/gcp/`
- TFLint `tflint-ruleset-google` plugin for GCP-specific Terraform linting
- Image registry check ensuring Kustomize overlay images reference Artifact Registry (`pkg.dev`)
- Pod Security Standards labels (`restricted` profile) on Kubernetes namespace manifests
- PSS namespace labels architecture check in pre-commit Stage 4 (ADR-006-R1)
- ADR-006: Kubernetes workloads must meet Pod Security Standards
- ADR-004-R5 (kubeconform + kube-linter) and ADR-004-R6 (tflint-ruleset-google) rules
- CI jobs: `k8s-lint`, `k8s-schema`, `security-k8s` in quality workflow
- Time-bounded exceptions for known K8s manifest gaps (securityContext, NetworkPolicies) expiring 2026-07-08

## [3.62.1] - 2026-04-06

### Fixed
- ADR guard argparse ambiguity: positional `checks` arg replaced with `--checks` named option to prevent `--files nargs="+"` from swallowing check names
- Claude post-edit hook no longer runs `guardrail-docs` check, which is a changeset-level check incompatible with per-file hook context

### Added
- Ground Control project context in AGENTS.md for the `/implement` workflow

## [3.62.0] - 2026-04-05

### Added
- Enforce magic link token expiration at login — expired tokens are now rejected (PLAT-101)
- Configurable magic link expiration via `MAGIC_LINK_EXPIRY_HOURS` setting (default 24 hours)
- Configurable single-use tokens via `MAGIC_LINK_SINGLE_USE` setting (default multi-use)
- Rate limiting on invitation generation endpoints (50 per hour per organizer)

## [3.61.0] - 2026-04-05

### Added
- Time-boundary enforcement on flag submissions rejects attempts before event start or after event end, regardless of event state (CTF-702)
- Countdown timer on participant event page showing time until event start or end
- Client-side local timezone display for event start and end times on participant event page

## [3.60.0] - 2026-04-05

### Added
- Scheduled reminder notifications at configurable intervals before event start (CTF-1005)
- `reminder_hours` field on CTFEvent for organizer-configurable reminder intervals (default: 24h, 1h)
- `event_timezone` field on CTFEvent for timezone-aware start times in reminder emails
- Access URL included in reminder emails linking to participant event page
- Timezone-aware event start time display in reminder email templates
- Per-challenge connection info for range-integrated challenges (CTF-115)
- `target_instance_name` and `target_port` fields on CTFChallenge to map a challenge to a specific range service
- Participant challenge detail view now resolves the configured target against the participant's ready range and displays the host:port inline

### Changed
- Scheduler `_handle_send_reminder` handler now calls `send_reminder()` (was a stub)
- `_schedule_event_tasks` creates one SEND_REMINDER task per configured interval with `hours_before` metadata

## [3.59.0] - 2026-04-05

### Added
- Shared email templating and delivery service in `shared.email` (PLAT-103)
- `render_template()` for rendering HTML+text email template pairs with variable substitution
- `send_email()` for synchronous delivery with error logging (never raises)
- `send_email_async()` for fire-and-forget background delivery via thread pool
- CTF notification service now delegates to the shared email service

## [3.58.0] - 2026-04-05

### Added
- Per-event email template customization: organizers can override default email templates for any notification type (CTF-805)
- `CTFEmailTemplate` model with unique constraint per event and notification type
- Admin page listing template override status per notification type
- API endpoint for CRUD operations on custom email templates

## [3.57.0] - 2026-04-04

### Added
- Event force delete: permanently delete an event and all associated resources regardless of state (CTF-704)
- Force delete cascades to range instances, participants, challenges, submissions, scores, and scheduled tasks
- Confirmation page requiring organizer to type event name before force deleting
- API endpoint for programmatic force delete with confirmation_name validation
- Danger zone section on event detail page linking to force delete

## [3.56.2] - 2026-04-04

### Fixed
- Enforce registration deadline when inviting or bulk-importing participants (CTF-007)

## [3.56.1] - 2026-04-04

### Added
- Organizer email notifications on automated event start/end transitions (CTF-1004)
- Email templates for event start and event end organizer notifications
- `notify_organizer_event_start()` and `notify_organizer_event_end()` notification service functions
- Tests for scheduler event start/end handlers and organizer notifications

## [3.56.0] - 2026-04-04

### Added
- Scoreboard visibility toggle: organizers can hide the scoreboard from participants until ready (CTF-004)
- `scoreboard_visible` boolean field on CTFEvent model (default True)
- Participant scoreboard view and API return hidden state when scoreboard is not visible
- Admin scoreboard shows banner when scoreboard is hidden from participants
- Scoreboard visibility checkbox in event create/edit form

## [3.55.0] - 2026-04-02

### Added
- Bracket support: group participants into named brackets (e.g. beginner, intermediate, advanced) with separate scoreboards per bracket (CTF-405)
- `CTFBracket` model with event-scoped name uniqueness and soft delete
- `bracket` foreign key on `CTFParticipant` for bracket assignment
- Bracket CRUD service (`ctf/services/bracket.py`) with assignment validation
- `bracket_id` filter parameter on `get_scoreboard()` and `get_team_scoreboard()`
- `bracket_name` field in scoreboard response entries
- Bracket tabs on participant and admin scoreboard views
- Admin bracket management views (list, create, edit, delete)
- API endpoint for assigning/removing participant brackets
- Bracket column in admin participant list
- `CTFBracketAdmin` in Django admin with participant count
- `CTFBracketForm` for bracket creation/editing

## [3.54.0] - 2026-04-02

### Added
- Scoreboard freeze support: organizers can set a freeze time after which participants see frozen standings while organizers see real-time scores (CTF-403)
- `scoreboard_freeze_at` field on CTFEvent model with validation
- `is_scoreboard_frozen` convenience property on CTFEvent
- `freeze_at` parameter on `get_scoreboard()` and `get_team_scoreboard()` scoring functions
- Freeze time input on event creation/edit form
- Freeze status banners on participant and admin scoreboard views
- Freeze indicator in scoreboard API JSON responses

## [3.53.1] - 2026-04-02

### Fixed
- Team scoreboard solve count now counts unique challenges solved instead of total submissions (CTF-402)
- Participant scoreboard template context variable mismatch preventing scoreboard from rendering (CTF-402)
- Participant scoreboard auto-refresh reading wrong JSON key from API response (CTF-402)
- Participant scoreboard now displays team-specific columns (Members) when team mode is active (CTF-402)

## [3.53.0] - 2026-04-02

### Added
- Per-participant score timeline API and charts showing cumulative score progression over event duration (CTF-408)
- Score timeline chart on participant scoreboard page (own timeline) and admin participant detail page (any participant)
- `get_score_timeline()` service function in CTF scoring module

## [3.52.0] - 2026-04-01

### Added
- Per-iteration progress logging during throttled range provisioning — logs "N/M (X ready, Y failed)" after each provision (CTF-905)
- Test suite for `provision_event_ranges_throttled()` covering happy path, partial failure, delay clamping, and graceful shutdown (CTF-905)

## [3.51.0] - 2026-03-30

### Added
- Organizer dashboard: quick-access event controls (pause, end, cancel) for active events (CTF-1301)
- Organizer dashboard: participant count with registration breakdown (CTF-1301)
- Organizer dashboard: range provisioning status overview with ready/provisioning/error counts (CTF-1301)
- Organizer dashboard: recent activity feed showing last 15 submissions across active events (CTF-1301)

## [3.50.0] - 2026-03-29

### Added
- Browser-based RDP access buttons on CTF participant range page (CTF-904)

## [3.49.0] - 2026-03-29

### Added
- Next challenge navigation: optional per-challenge FK to suggest follow-up after solving (CTF-121)
- Organizer dropdown on challenge form to configure next challenge
- Participant "Next:" link in solved alert with non-blocking navigation

## [3.48.0] - 2026-03-29

### Added
- Hint purchase confirmation showing actual penalty cost and resulting challenge value (CTF-304)
- Warning when hint purchase would reduce challenge to minimum 1-point floor (CTF-304)

## [3.47.0] - 2026-03-29

### Changed
- Progressive ordered hints system replacing single hint per challenge (CTF-003)
- `CTFHint` model with per-hint text, penalty, and order for sequential unlock
- `CTFHintUsage` model tracks which hints each participant has unlocked
- Cumulative penalty calculation (sum of unlocked hint penalties, capped at 100%)
- Organizer hint management via API (add/remove hints on challenge detail page)
- Participant progressive hint UI with sequential unlock and penalty display
- Data migration converts existing single-hint challenges to CTFHint records

### Removed
- Legacy `hint` and `hint_penalty` fields from CTFChallenge
- Legacy `hint_used` field from CTFSubmission

## [3.46.0] - 2026-03-28

### Added
- Participant challenge ratings on a 1-5 scale (CTF-120)
- `CTFChallengeRating` model with unique constraint per participant per challenge
- `rating_visibility` event-level config: public, organizer-only, or disabled
- API endpoint `POST /api/challenges/<id>/rate/` for submitting ratings
- Average rating and count displayed in admin and participant challenge detail
- Rating visibility dropdown in event admin form

## [3.45.0] - 2026-03-28

### Added
- Controlled vocabulary topic taxonomy for CTF challenges (CTF-119)
- `CTFTopic` model for global knowledge areas and attack techniques (e.g. SQL Injection, Privilege Escalation)
- Topics distinct from categories (event-scoped enum) and tags (freeform, event-scoped)
- Topic filtering on participant challenge listing via `?topic=` query parameter
- Topics displayed as badges on challenge cards and admin detail pages
- Topics included in challenge API responses (list and detail)

## [3.44.0] - 2026-03-28

### Added
- Official solution writeups on CTF challenges (CTF-117)
- `solution` TextField on CTFChallenge for rich-text Markdown content
- Solutions visible to organizers at all times, revealed to participants after event ends
- Solution editing in admin challenge form, display in admin challenge detail
- Solution field in challenge API detail response

## [3.43.0] - 2026-03-27

### Added
- Freeform metadata tags on CTF challenges for secondary filtering (CTF-113)
- `CTFChallengeTag` model scoped to events with unique constraint per event
- Tag filtering on participant challenge listing via `?tag=` query parameter
- Tags displayed as badges on challenge cards and admin detail pages
- Tags included in challenge API responses (list and detail)
- Comma-separated tag input on admin challenge form

## [3.42.0] - 2026-03-26

### Added
- Configurable attempt limit behavior per event: lockout (permanent) or timeout (temporary with cooldown) (CTF-112)
- `attempt_limit_mode` field on CTFEvent selects behavior when max attempts reached
- `attempt_limit_cooldown_seconds` field on CTFEvent controls timeout duration before attempts reset
- Submission Limits section in event admin form for managing cooldown and attempt limit settings
- Attempt limit fields exposed in event API GET response

## [3.41.0] - 2026-03-26

### Added
- Configurable time-based submission rate limiting per event (CTF-114)
- `submission_cooldown_seconds` field on CTFEvent controls minimum delay between flag submissions per participant per challenge
- Rate-limited responses include `Retry-After` header and retry details for client display

## [3.40.0] - 2026-03-26

### Added
- Automatic challenge release scheduling via the CTF scheduler (CTF-111)
- `RELEASE_CHALLENGE` scheduled task type transitions HIDDEN challenges to VISIBLE at their configured `release_time`
- Challenge create/update automatically manages release task lifecycle (create, reschedule, cancel)
- Event rescheduling recreates challenge release tasks for all eligible challenges

## [3.39.0] - 2026-03-26

### Added
- Challenge visibility control with three states: visible, hidden, locked (CTF-110)
- Organizers can hide broken challenges mid-event or stage challenges before making them visible
- Locked challenges appear in participant lists but block submissions

## [3.38.0] - 2026-03-26

### Added
- Range lifecycle management tied to event state (CTF-902) — ranges are destroyed when events end (if auto_cleanup) or are cancelled
- Manual stop, start, and restart APIs for organizer range management
- Provisioning retry with exponential backoff (3 retries, 30s base delay)
- Organizer email notification on provisioning failures
- Context-appropriate range action buttons in organizer UI (stop/start/restart/destroy per status)

### Changed
- Enforced strict service layer boundaries — all cross-layer imports must go through `layer.services` only
- Added `ctf` to architecture-as-code checkers (`check_layer_imports`, `check_model_fks`)
- Replaced `management.UserProfile.active_ctf_event` ForeignKey with soft-reference UUIDField (zero cross-layer FKs)
- Moved `get_s3_client` and `sanitize_s3_filename` from `cms.assets.s3` to `shared.s3`
- Moved `range_status_changed` signal from `ctf.signals` to `cms.signals` (CMS emits, CTF receives)
- Removed duplicated Guacamole URL generation from CTF — participants use the platform's existing RDP access flow
- Fixed 13 cross-layer import violations across cms, mission_control, and ctf

## [3.37.0] - 2026-03-25

### Changed
- Completed event statistics for CTF analytics dashboard (CTF-1304) — added active participants (submission-based), challenges with zero solves, average score, median score, incorrect submissions, and event duration metrics
- Fixed `active_participants` in `get_event_statistics()` to count participants with at least one submission instead of filtering by status
- Expanded analytics template from 4 to 8 stat cards

## [3.36.0] - 2026-03-24

### Changed
- CTF event lifecycle expanded to 7-state machine: draft, registration, active, paused, ended, cancelled, archived (CTF-701)
- Renamed event status "scheduled" to "registration" and "completed" to "ended"
- Event transitions enforced via centralized VALID_TRANSITIONS map
- Added pause_event, resume_event, archive_event service functions

## [3.35.1] - 2026-03-22

### Fixed
- `reconcile_ranges` now detects all running range EC2 instances, including those with custom Name tags or hyphenated roles, by filtering on `shifter:range_id` tag instead of Name tag pattern (#796)
- `reconcile_ranges` now flags orphan instances when engine_instance exists but has no associated range (NULL range_status from LEFT JOIN)

## [3.35.0] - 2026-03-22

### Added
- File attachments for CTF challenges (CTF-001) — organizers can upload downloadable files (binaries, pcaps, images, etc.) to challenges; participants download via presigned S3 URLs
- Challenge prerequisites (CTF-001) — challenges can require other challenges to be solved first, with BFS cycle detection, locked challenge display, and submission gating
- `CTFChallengeFile` model with S3 storage, SHA256 integrity, size/extension validation (50 MB max, 10 files per challenge)
- `CTFChallengePrerequisite` model with same-event validation, self-reference prevention, and circular dependency detection
- Attachment service (`add_challenge_file`, `remove_challenge_file`, `get_challenge_files`, `get_download_url`)
- Prerequisite service functions (`add_prerequisite`, `remove_prerequisite`, `get_prerequisites`, `get_dependents`, `check_prerequisites_met`)
- API endpoints for file management and prerequisite management
- Admin challenge detail UI sections for managing files and prerequisites
- Participant challenge views show downloadable files and prerequisite lock/gate UI

### Changed
- `get_available_challenges()` accepts optional `participant_id` to exclude challenges with unmet prerequisites
- `submit_flag()` checks prerequisites before accepting submissions
- `delete_challenge()` cascades soft-delete to prerequisite links where the challenge is required

## [3.34.0] - 2026-03-22

### Changed
- **Terraform**: Rename remaining `pulumi_state_*`, `pulumi_locks_*`, `pulumi_secrets_*` variable names in `modules/engine-provisioner/variables.tf` to `engine_state_*`, `engine_locks_*`, `engine_secrets_*`
- **Terraform**: Rename remaining `pulumi_state_*`, `pulumi_locks_*`, `pulumi_secrets_*` output names in `environments/*/range/outputs.tf` to `engine_*` equivalents
- **Terraform**: Update all `data.terraform_remote_state.range.outputs.pulumi_*` references in `environments/*/portal/main.tf` to match renamed outputs
- **Terraform**: Rename Terraform resource identifiers (with `moved` blocks) in `modules/engine-state/` (`aws_s3_bucket.pulumi_state` → `engine_state`, `aws_kms_key.pulumi_secrets` → `engine_secrets`, `aws_dynamodb_table.pulumi_locks` → `engine_locks`, plus sub-resources)
- **Terraform**: Rename Terraform resource identifiers (with `moved` blocks) in `modules/engine-provisioner/` (`aws_ecs_cluster.pulumi` → `engine`, `aws_ecs_task_definition.pulumi_provisioner` → `engine_provisioner`, `aws_iam_role_policy.pulumi_state` → `engine_state`)
- **Terraform**: Update comments and descriptions referencing "Pulumi" to "engine" in `modules/engine-provisioner/iam.tf` and `variables.tf`

### Removed
- **Terraform**: Remove deprecated `pulumi-*` SSM parameters from `modules/portal/ssm/main.tf` (confirmed no application code references them; `engine-*` parameters already active)

## [3.33.0] - 2026-03-22

### Changed
- **Platform**: ECS modules (`engine/ecs.py`, `cms/experiments/ecs.py`) now propagate `CloudTaskError` instead of catching it and re-raising as `botocore.exceptions.ClientError`
- **Platform**: `engine/services.py` callers (`pause_range`, `resume_range`) catch `CloudTaskError` instead of `ClientError`
- **Platform**: Extract `_get_engine_ecs_config()` helper in `engine/ecs.py` to DRY up config reading from 3 internal functions

### Fixed
- **Terraform**: Portal `ecr_repository_url` uses `try()` fallback for foundation output rename (`engine_provisioner_ecr_url` || `pulumi_provisioner_ecr_url`) so portal plan succeeds regardless of foundation apply order

### Removed
- **Platform**: Remove `from botocore.exceptions import ClientError` from `engine/ecs.py` and `cms/experiments/ecs.py`

## [3.32.0] - 2026-03-22

### Changed
- **Platform**: Rename `PULUMI_ECS_CLUSTER_ARN`, `PULUMI_TASK_DEFINITION_ARN`, `PULUMI_ECS_SECURITY_GROUP_ID`, `PULUMI_PRIVATE_SUBNET_IDS` to `ENGINE_*` prefix across settings, application code, tests, Terraform SSM, deployment scripts, and CI/CD
- **Platform**: Rename `PULUMI_BACKEND_URL` to `STATE_BUCKET_URL` in task definition and local provisioner script
- **Platform**: Settings use fallback pattern (`ENGINE_*` || `PULUMI_*`) for zero-downtime transition
- **Terraform**: Rename module directories `modules/pulumi-provisioner/` to `modules/engine-provisioner/` and `modules/pulumi-state/` to `modules/engine-state/`
- **Terraform**: Rename module blocks `pulumi_provisioner` to `engine_provisioner`, `pulumi_state` to `engine_state`, `pulumi_provisioner_ecr` to `engine_provisioner_ecr` with `moved` blocks for state continuity
- **Terraform**: Rename variables `pulumi_provisioner_repository_name` to `engine_provisioner_repository_name`, `pulumi_container_tag` to `engine_container_tag`, and SSM module variables `pulumi_ecs_*`/`pulumi_task_*`/`pulumi_private_*` to `engine_*`
- **Terraform**: Rename outputs `pulumi_provisioner_ecr_*` to `engine_provisioner_ecr_*` and portal outputs `pulumi_ecs_*`/`pulumi_task_*`/`pulumi_private_*` to `engine_*`
- **Terraform**: Update all `module.pulumi_provisioner.*` and `module.pulumi_state.*` references to `module.engine_provisioner.*` and `module.engine_state.*` across environments
- **Terraform**: Update comments, descriptions, and tags from "Pulumi" to "Engine" in module internals (resource names unchanged for state compatibility)
- **Terraform**: Add new `engine-*` SSM parameters alongside deprecated `pulumi-*` parameters for transition

### Removed
- **Platform**: Remove `PULUMI_SECRETS_PROVIDER` env var (dead after Pulumi removal)
- **Platform**: Remove `PULUMI_BACKEND_URL`/`PULUMI_SECRETS_PROVIDER` from `_run_local_provisioner()` and `.env.example`
- **Platform**: Remove mock-pulumi PATH injection from local provisioner

## [3.31.0] - 2026-03-22

### Added
- **Provisioner**: `terraform_base.py` — shared Terraform runner helpers extracted from duplicate code in `terraform_runner.py` and `range_terraform_runner.py`
- **Provisioner**: `cloud/aws/base.py` — `BaseAWSAdapter` base class with shared `_get_client()` for all AWS adapters
- **Provisioner**: Shared executor exceptions (`ExecutorError`, `ExecutorCommandError`, `ExecutorTimeoutError`) in `executors/base.py`

### Changed
- **Provisioner**: `terraform_runner.py` and `range_terraform_runner.py` are now thin wrappers around `terraform_base.py`, eliminating ~550 lines of exact duplication
- **Provisioner**: All 5 AWS adapters (`secrets`, `db_auth`, `config_store`, `event_bus`, `storage`) inherit `BaseAWSAdapter` instead of duplicating `_get_client()`
- **Provisioner**: SSM, SSH, and NGFW executors use shared exception base classes from `executors/base.py` with backward-compatible aliases
- **Provisioner**: `main.py` SQL query construction uses `psycopg.sql` module for safe identifier composition instead of f-string formatting
- **Provisioner**: `linux_xdr_agent_install.py` bash scripts use `mktemp` for unpredictable temp file paths instead of hardcoded `/tmp` paths
- **Provisioner**: NGFW executor temp key file cleanup improved with `__del__` fallback; removed redundant `os.chmod` (mkstemp already creates with 0o600)

### Removed
- **Provisioner**: Remove `pulumi` and `pulumi_aws` from `requirements.txt` (already removed from `pyproject.toml`)

### Security
- **Provisioner**: Added `# NOSONAR` annotations for reviewed security hotspots (subprocess calls, Paramiko AutoAddPolicy, SSH StrictHostKeyChecking, test credentials)

## [3.30.0] - 2026-03-21

### Added
- **Provisioner Cloud**: `SecretsStore` protocol, `CloudSecretsError` exception, `AWSSecretsStore` adapter, and `get_secrets_store()` factory
- **Provisioner Cloud**: `object_exists()` and `delete_object()` methods on `ObjectStorage` protocol and `AWSObjectStorage` adapter

### Changed
- **Provisioner**: Migrate `events.py` from direct `boto3` SNS calls to `EventBus` cloud abstraction
- **Provisioner**: Migrate `config.py` RDS IAM auth from `boto3` to `DBAuth` cloud abstraction
- **Provisioner**: Migrate `main.py` S3/SSM/RDS/Secrets calls to `ObjectStorage`, `ConfigStore`, `DBAuth`, `SecretsStore` cloud abstractions
- **Provisioner**: Migrate `stacks/range_stack.py` Secrets Manager call to `SecretsStore` cloud abstraction
- **Provisioner**: Migrate `components/network.py` RDS IAM auth to `DBAuth` cloud abstraction
- **Provisioner**: Migrate `terraform_runner.py` S3 calls to `ObjectStorage` cloud abstraction
- **Provisioner**: Migrate `range_terraform_runner.py` S3 calls to `ObjectStorage` cloud abstraction

### Removed
- **Provisioner**: Remove `_get_sns_client()` from `events.py` (replaced by `EventBus` protocol)
- **Provisioner**: Remove direct `import boto3` from `events.py`, `config.py`, `main.py`, `stacks/range_stack.py`, `terraform_runner.py`, `range_terraform_runner.py`

## [3.29.1] - 2026-03-21

### Changed
- **Provisioner**: Remove misleading "stub" docstrings from AWS cloud adapters (`AWSObjectStorage`, `AWSConfigStore`, `AWSEventBus`, `AWSDBAuth`) — implementations are complete

## [3.29.0] - 2026-03-21

### Changed
- **Worker**: Migrate `run_worker` management command from direct `boto3` SQS calls to `shared.cloud.get_queue_consumer()` abstraction layer
- **CMS**: Migrate `cms/experiments/events.py` from direct `boto3` SQS calls to `shared.cloud.get_queue_publisher()` abstraction layer
- **Cloud**: Remove stub docstring from `AWSQueuePublisher`/`AWSQueueConsumer` now that extraction is complete

### Removed
- **Engine**: Delete deprecated `_get_ecs_client()` from `engine/ecs.py` (replaced by `shared.cloud.get_task_runner()`)
- **CMS**: Delete deprecated `_get_ecs_client()` from `cms/experiments/ecs.py` (replaced by `shared.cloud.get_task_runner()`)
- **Tests**: Delete `tests/engine/ecs/test_get_ecs_client.py` (tested removed function)

## [3.28.0] - 2026-03-21

### Changed
- **Engine**: Migrate `engine/secrets.get_ssh_key()` from direct `boto3` Secrets Manager calls to `shared.cloud` abstraction layer
- **CTF**: Migrate `ctf/bridges._get_instance_ssh_key()` from direct `boto3` Secrets Manager calls to `shared.cloud` abstraction layer
- **Cloud**: Remove stub docstring from `AWSSecretsStore` now that extraction is complete

## [3.27.3] - 2026-03-21

### Changed
- **Tests**: Consolidate test suite through parametrization and fixture extraction (39,712 → 39,050 lines, -662 net)
- **Tests**: Extract shared `mock_queryset` fixture and `INVALID_USERS`/`INVALID_RANGE_IDS` parametrize helpers to `tests/conftest.py`
- **Tests**: Extract in-memory model builders (`make_ctf_event`, `make_challenge`, `make_team`, `make_participant`, `make_scheduled_task`) to `tests/ctf/conftest.py`
- **Tests**: Create `tests/cms/conftest.py` with shared `credential_type_obj` fixture and `make_credential` builder
- **Tests**: Convert `_create_range_patches` helper to `create_range_ctx` pytest fixture in `cms/test_services_range.py`
- **Tests**: Parametrize user/range_id validation and error propagation tests across service classes in `cms/test_services_range.py`
- **Tests**: Consolidate model_dump/model_validate round-trip tests into parametrized classes in `shared/schemas/test_range.py` and `test_credentials.py`
- **Tests**: Parametrize required-field, default-value, computed-property, and status validation tests in `shared/schemas/test_range.py`
- **Tests**: Parametrize expiry property and positive-id validator tests in `shared/schemas/test_credentials.py`
- **Tests**: Parametrize boolean property, count, and status transition tests in `ctf/test_models.py`
- **Tests**: Parametrize credential property tests in `cms/test_models.py`
- **Tests**: Refactor `test_scoring.py` scoreboard setup methods to use shared `mock_queryset` fixture

### Added
- **Tests**: Add error handling, input validation, and missing config tests for `start_provisioning()` (2 → 7 tests)
- **Tests**: Add error handling, input validation, and missing config tests for `start_teardown()` (2 → 7 tests)
- **Tests**: Add error cases for `start_ngfw_provisioning()` (3 → 6 tests)
- **Tests**: Add error cases for `start_ngfw_teardown()` (4 → 7 tests)

### Removed
- **Tests**: Delete empty `mission_control/test_consumers.py` (0 tests, placeholder comment only)
- **Tests**: Remove redundant `InstanceContext` tests that duplicated `InstanceContextBase` coverage

## [3.27.2] - 2026-03-21

### Security
- **Platform**: Bump `django` 6.0 -> 6.0.3
- **Platform**: Bump `cryptography` 46.0.3 -> 46.0.5
- **Platform**: Bump `pyopenssl` 25.3.0 -> 26.0.0
- **Platform**: Bump `pyasn1` 0.6.1 -> 0.6.3
- **Platform**: Bump `ujson` 5.11.0 -> 5.12.0
- **Platform**: Bump `cbor2` 5.7.1 -> 5.8.0
- **Platform**: Bump `urllib3` 2.6.0 -> 2.6.3
- **Platform**: Bump `filelock` 3.20.0 -> 3.25.2
- **Platform**: Bump `virtualenv` 20.35.4 -> 21.2.0
- **Platform**: Add `[tool.uv] constraint-dependencies` to enforce minimum versions for transitive security deps

## [3.27.1] - 2026-03-21

### Security
- **Provisioner**: Bump `cryptography` 46.0.3 -> 46.0.5
- **Provisioner**: Bump `protobuf` 5.29.5 -> 5.29.6
- **Provisioner**: Bump `urllib3` minimum to >=2.6.3

## [3.27.0] - 2026-03-21

### Changed
- **Test suite: eliminate all DB access outside `tests/integration/`** — 63% faster (722s → 269s)
  - Converted 87 `@pytest.mark.django_db` markers and ~48 `TestCase` subclasses to mock-based tests
  - Only 22 markers remain, all in `tests/integration/` (legitimate integration tests)
  - View tests: replaced `Client`/`force_login` with `RequestFactory` + mock users
  - Model tests: in-memory construction via `Model()` or `__new__` + `__dict__`
  - Service tests: patched ORM managers (`objects.get`, `objects.filter`, `objects.create`, etc.)
  - Added missing engine migration (SubnetAllocation `reserved_at` → `created_at` rename)
  - Added missing CTF migration (index rename, field alter)
  - Changed all `OperatingSystem.objects.get(slug=...)` to `get_or_create()` for xdist resilience

## [3.26.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_models_subnet.py` (CMS) by mocking ORM
  - Added `_make_subnet()` helper to construct Subnet instances in-memory via `__dict__` assignment, bypassing Django FK descriptor validation
  - EntityBase `is_deleted` tests: built in-memory with `deleted_at` set/unset
  - Terminal status auto-`deleted_at` tests: patched `validate_data` and `django.db.models.Model.save` to exercise real `EntityBase.save()` logic without DB
  - Relationship tests: replaced cascade-delete DB test with `_meta` introspection asserting `CASCADE` on_delete and `related_name='subnets'`
  - Ordering test: asserted `Subnet._meta.ordering` instead of querying DB
  - Validation tests: called `subnet.validate_data()` directly on in-memory instances
  - Data/property tests: constructed in-memory instances and asserted properties
  - 4 class-level `@pytest.mark.django_db` markers removed, all 18 tests pass without DB access

## [3.25.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_models.py` (mission_control) by mocking ORM
  - Added `_make()` helper to construct Django model instances in-memory, bypassing FK validation and populating `_state.fields_cache`
  - OperatingSystem `get_for_extension` tests: patched `OperatingSystem.objects.all`
  - UserProfile tests: built via `_make()` with mock user in fields_cache
  - AgentConfig tests: built via `_make()` with mock user/os, `active_for_user` patched at `AgentConfig.objects.filter`
  - Range standup_duration tests: set `created_at`/`ready_at` directly on in-memory instances; annotation test mocks `Range.objects` chain
  - ActivityLog tests: `log()` patched at `ActivityLog.objects.create`, `__str__` tests use `_make()`
  - 4 class/method-level `@pytest.mark.django_db` markers removed, all 34 tests pass without DB access

## [3.24.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_auth.py` (CTF) by mocking ORM
  - Created `_MockGroupManager`/`_MockGroupQS` helpers to simulate `user.groups` with in-memory sets
  - OIDC backend tests: patched `config.oidc.Group.objects`, `config.oidc.get_user_profile`, `ctf.models.CTFEvent.objects`
  - Dashboard routing tests: call `dashboard_router` directly via `RequestFactory` with mock users
  - Access control decorator tests: patched `management.services.get_user_profile`, `ctf.models.CTFParticipant.objects`
  - Dev login tests: patched `config.dev_auth.User.objects`, `config.dev_auth.Group.objects`, `config.dev_auth.login`
  - Context processor tests: patched `management.services.get_user_profile` (bridges import locally)
  - Register view tests: patched `ctf.models.CTFParticipant.objects`, `django.contrib.auth.login`
  - Dual-role tests: patched `management.services.get_user_profile`, `django.contrib.auth.models.Group.objects`
  - 8 class-level `@pytest.mark.django_db` markers removed, all 48 tests pass without DB access

## [3.23.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_range_api.py` (mission_control) by mocking ORM
  - Replaced `Client`/`force_login` with `RequestFactory` + mock user via `AnonymousUser` for auth tests
  - View tests (get_range, launch_range, cancel_range, destroy_range, list_agents): patched CMS service functions (`get_active_range`, `cms_create_range`, `cms_get_agent`, `cms_list_agents`, `cms_list_scenarios`) at the view-module boundary
  - Subnet allocation tests: mocked `transaction.atomic` and `Range.objects` queryset chain
  - Shared fixtures (`mock_user`, `mock_agent`, `mock_linux_agent`, `other_user`) replace DB-backed `test_agent`/`windows_os`/`linux_os` fixtures
  - 6 class-level `@pytest.mark.django_db` markers removed, all 37 tests pass without DB access

## [3.22.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_scoring.py` (CTF) by mocking ORM
  - `TestCalculateScore`: mocked `CTFSubmission.objects.filter().aggregate()` chain
  - `TestGetScoreboard` / `TestGetTeamScoreboard`: mocked annotated queryset chains with mock participant/team objects
  - `TestGetParticipantRank`: mocked both `.get()` lookup and scoreboard queryset
  - `TestGetChallengeStatistics`: mocked `CTFChallenge.objects.get()` and submission queryset chains
  - `TestGetEventStatistics`: mocked `CTFEvent.objects.get()` and all related model managers
  - `TestCalculatePointsWithPenalty`: replaced real model instances with mocks binding the real method
  - 7 class-level `@pytest.mark.django_db` markers removed, all 27 tests pass without DB access

## [3.21.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_views.py` (mission_control) by mocking ORM
  - View tests (dashboard, settings, help): replaced `Client`/`force_login` with `RequestFactory` + mock user, patched `render` to avoid DB-hitting context processors
  - `TestGetUserStorageUsed`: mocked `AgentConfig.active_for_user` queryset instead of creating real DB records
  - `TestUploadLock`: replaced Django session with plain dict (no DB session backend needed)
  - 5 class-level `@pytest.mark.django_db` markers removed, all 14 tests pass without DB access

## [3.20.0] - 2026-03-20

### Changed
- Remove `@pytest.mark.django_db` from three CMS test files by mocking all ORM access
  - `test_services_scenarios.py`: replaced real User/AgentConfig fixtures with mocks, patched registry functions (list_all_scenarios, get_scenario_detail, load_scenario_template)
  - `test_scenario_hydrator.py`: replaced real User/AgentConfig fixtures with mocks, patched hydrator's load_scenario with canned ScenarioTemplate Pydantic objects
  - `test_services_range.py`: converted remaining 4 `create_range` test classes (Validation, EngineCall, Instance, Return) from DB to fully mocked ORM using ExitStack-based helper

## [3.19.0] - 2026-03-20

### Changed
- Test suite optimization: remove unnecessary `@pytest.mark.django_db` markers and add `--reuse-db`
  - Added `--reuse-db` to pytest addopts in pyproject.toml for faster repeated runs
  - `test_create_range.py`: removed `django_db`, added `_mock_transaction` autouse fixture
  - `test_cancel_range.py`: removed `django_db` from both classes, added `_mock_range_lookup` fixture
  - `test_services_storage.py`: converted real `User` fixture to `mock_user`, removed `django_db`
  - `test_handlers.py` (CMS): removed `django_db` from `TestProcessEvent` and `TestParseSnsMessage`
  - `test_handlers.py` (Engine): removed `django_db` from `TestProcessEvent` and `TestParseSnsMessage`
  - `test_models_agent_config.py`: removed `django_db` from `TestAgentConfigModel` (metadata-only tests)
  - `test_models_operating_system.py`: removed `django_db` from `TestOperatingSystemModel` (metadata-only tests)
  - 10 class-level markers removed across 7 test files

## [3.18.0] - 2026-03-20

### Changed
- Test suite cleanup: remove duplicate wrapper tests and unnecessary `@pytest.mark.django_db` markers
  - Removed ~51 duplicate tests from ECS wrapper test files (delegation verified in 2-4 tests each)
  - Deleted `tests/mission_control/test_engine.py` (12 tests duplicating `tests/engine/ecs/`)
  - Removed `@pytest.mark.django_db` from 8 test files that only use mocks (no ORM calls)
- CMS service test streamlining: replace real DB fixtures with mocks in mock-heavy tests
  - `test_services_range.py`: removed `django_db` from 8/12 classes (~75 tests), kept 4 `create_range` classes on DB
  - `test_services_upload.py`: removed `django_db` from all 3 classes (57 tests), removed unused DB fixtures
  - `test_services_agents.py`: removed `django_db` from all 4 classes (34 tests), removed unused DB fixtures
  - Added `mock_user` fixture with `Mock(pk=42, id=42)` to replace real `User.objects.create_user` in pure-mock tests
- Task runner abstraction delegation (PLAT-001.3, #813)
  - `engine/ecs.py`: All ECS task functions now delegate to `TaskRunner` protocol via `get_task_runner()`
  - `cms/experiments/ecs.py`: `start_experiment_task()` delegates to `TaskRunner` protocol via `get_task_runner()`
  - Added `container_name` parameter to `TaskRunner.run_task()` protocol and `AWSTaskRunner` adapter
  - `AWSTaskRunner.run_task()` now raises `CloudTaskError` when no tasks are started (was returning None)
  - `AWSTaskRunner.get_task_status()` now returns all fields callers expect (`desired_status`, `started_at`, `stopped_at`)
  - Exception bridging: `CloudTaskError` caught and re-raised as `ClientError` for backward compatibility
  - All existing function signatures, import paths, and caller contracts preserved
  - `_get_ecs_client()` kept deprecated in both modules; `import boto3` moved inside it

## [3.17.0] - 2026-03-19

### Changed
- Object storage abstraction delegation (PLAT-001.2, #812)
  - `cms/assets/s3.py`: All S3 functions now delegate to `ObjectStorage` protocol via `get_object_storage()`
  - `cms/experiments/s3.py`: All S3 functions now delegate to `ObjectStorage` protocol via `get_object_storage()`
  - `provisioner/config.py`: `generate_presigned_url()` delegates to provisioner `ObjectStorage` adapter
  - Exception bridging: `CloudStorageError` caught and re-raised as `S3Error` for backward compatibility
  - All existing function signatures, import paths, and caller contracts preserved

## [3.18.0] - 2026-03-20

### Added
- Programmable flag validation (CTF-118) — flags can use registered Python validator functions or HTTP callbacks for custom pass/fail logic
- New flag types: `programmable` (server-side validator registry) and `http` (external endpoint validation)
- Validator registry module (`ctf/validators.py`) with `register_validator` / `get_validator` API
- Built-in example validators: `always_true`, `contains_substring`
- `validator_config` JSONField on `CTFFlag` model for per-flag configuration

### Changed
- `CTFFlag.flag_type` max_length increased from 10 to 20 to accommodate new type names

## [3.17.0] - 2026-03-20

### Added
- CTF awards system (CTF-206) — organizers can grant point bonuses or deductions to participants via `CTFAward` model
- Award service (`grant_award`, `revoke_award`, `get_participant_awards`, `get_event_awards`)
- Score calculation now includes awards: `calculate_score`, `get_scoreboard`, `get_team_scoreboard`, model `total_score` properties, and admin annotations all reflect submission points + award points
- `get_event_statistics` includes `total_awards` count
- Award admin interface with inline views on participant and event admin pages

## [3.16.1] - 2026-03-20

### Changed
- Consolidated all in-app test directories (`ctf/tests/`, `cms/experiments/tests/`, `risk_register/tests/`) into centralized `tests/` directory so all 2331 tests are discovered by the default `pytest` command
- Removed `--cov` from pytest `addopts` — local runs are now fast; coverage runs only in CI
- CI workflow now includes `--cov` for `ctf`, `engine`, and `risk_register` modules and no longer ignores `tests/risk_register`

## [3.16.0] - 2026-03-19

### Added
- Cloud provider abstraction layer foundation (PLAT-001.1, #811)
  - Protocol definitions for ObjectStorage, TaskRunner, QueueConsumer, QueuePublisher, SecretsStore (platform)
  - Protocol definitions for EventBus, ConfigStore, DBAuth, ObjectStorage (provisioner)
  - Factory functions with `CLOUD_PROVIDER` setting (defaults to "aws")
  - AWS adapter implementations for all protocols
  - Provider-agnostic exception hierarchy
  - Generic setting aliases (`CLOUD_PROVIDER`, `CLOUD_REGION`, `STORAGE_BUCKET_NAME`) with backward-compatible AWS fallbacks
- Multiple flags per challenge (CTF-107) — new `CTFFlag` model supports multiple valid flags per challenge where any correct flag constitutes a solve
- Each flag independently supports static (hashed) or regex (pattern match) types and case sensitivity
- `add_flag` / `remove_flag` service functions and API endpoints for flag management
- Flag management UI on admin challenge detail page (add/remove flags with type and case sensitivity controls)
- Backward compatible — challenges with only the legacy `flag_hash` field continue to work without migration

## [3.15.4] - 2026-03-18

### Fixed
- Deploy pipeline circular dependency — Engine Deploy now skips gracefully when ECS task definition doesn't exist yet (first deploy), allowing Platform terraform to create it
- Platform workflow no longer blocked by Engine Deploy failure — tolerates non-success results so first deploy can complete
- Guacamole ECS stability check: replaced `aws ecs wait services-stable` (hard 10min timeout) with polling loop (20min); auto-detects FAILED deployments from prior runs and forces redeployment before waiting
- Migration `cms/0015_ngfw_model.py` made idempotent — checks if `ngfw_spec` column exists before adding it, preventing "column already exists" error on fresh databases; uses `PRAGMA table_info` for SQLite (tests) and `information_schema` for PostgreSQL (prod)
- Docker Compose build context corrected — set to parent directory so Dockerfile can access sibling directories (`cyberscript/`, `shifter_platform/`)

### Added
- `SKIP_MIGRATIONS` environment variable support in `entrypoint.sh` for local development

## [3.15.3] - 2026-03-16

### Added
- CTF walkthrough page with 7-step copy-pasteable prompts for Box 0 (WebShell) guided workshop — accessible to participants at `/ctf/walkthrough/`

## [3.15.2] - 2026-03-15

### Fixed
- Range destroy no longer fails with empty CIDR — allocated subnet CIDRs are now persisted to range_config during provisioning, and destroy falls back to the allocation table for ranges provisioned before this fix

## [3.15.1] - 2026-03-15

### Added
- CTF scheduler process (`run_ctf_scheduler`) added to deployment workflow and docker-compose — scheduled tasks (range provisioning, event start/end, cleanup) now execute automatically

### Removed
- `describe_stacks` tool from the ops MCP server — CloudFormation is not used in this project (Pulumi is used instead), so the tool was dead code

## [3.15.0] - 2026-03-15

### Fixed
- CTF magic link now takes participants directly to Mission Control instead of showing a login page
- Removed dead CTF login page — magic link is the only auth path for CTF participants
- Logout now works for all auth types — unified `/logout/` view routes OIDC users through Cognito logout, magic-link/dev users through Django session logout
- Dashboard session-expiry redirect no longer hardcodes `/oidc/authenticate/` — uses `/dashboard/` (the router) so all user types land correctly

### Changed
- CTF participants now only see the Kali (attacker) box in the terminal UI — victim, DC, and NGFW tabs are filtered out in the `active_range()` context processor

## [3.14.0] - 2026-03-15

### Added
- Instance names from scenario YAML templates are now set as EC2 hostnames during provisioning — instances get meaningful names (e.g., `webdev01`, `kali`, `mx-internal`) instead of AWS defaults like `ip-10-1-2-109.us-east-2.compute.internal`
- `name` field passed through Terraform variables, locals, user_data templates, and outputs for all instance types (Kali, Linux victim, Windows victim, DC)
- Hostname setting in `victim_linux.sh.tpl`, `victim_windows.ps1.tpl`, and `dc_windows.ps1.tpl` user_data templates
- EC2 Name tags now use the scenario template name when available

## [3.13.2] - 2026-03-14

### Fixed
- Subnet allocation race condition — `allocate_subnets()` call in `range_stack.py` now passes `range_id` and `request_id`, so CIDR reservations are actually written to `engine_subnetallocation` (GH #786)
- Windows SSH failure during CTF bootstrap — CTF AMIs now build on top of Shifter base AMIs (`shifter-windows`, `shifter-ubuntu`) which have OpenSSH pre-installed, instead of raw Amazon/Canonical images that required runtime installation (GH #786)

### Changed
- CTF Packer templates (`ctf-helpdesk`, `ctf-vault`, `ctf-webshell`, `ctf-mailroom`, `ctf-devbox`) rebase on Shifter base AMIs instead of raw vendor images; `base.ps1`/`base.sh` provisioner steps removed
- CTF setup scripts deduplicated — removed IIS install, WinRM config, SSH config, and firewall rules already baked into base AMIs
- Reverted `configure_ssh` bootstrap DISM fallback — OpenSSH is now guaranteed by base AMI; missing SSH should fail loudly

## [3.13.1] - 2026-03-14

### Fixed
- CTF range destroy API returns 500 due to missing `range_id` — `process_range_event()` now persists `range_id` from SNS event to `RangeInstance` (#756)

## [3.13.0] - 2026-03-14

### Fixed
- Normal Shifter users who are also CTF participants no longer lose access to platform features like Assets, Docs, Settings/Help, and Launch Range (GH #758) — UI restrictions now use `is_ctf_participant_only` which only hides features for pure CTF participants with no other platform role

### Added
- `is_ctf_participant_only()` utility in `shared/auth.py` — returns True only when a user is a CTF participant with no staff, superuser, organizer, or threat research role
- `is_ctf_participant_only` template context variable exposed via CTF context processor

## [3.12.0] - 2026-03-14

### Fixed
- Experiment creation now enforces `staff_only` and `disabled` scenario restrictions (GH #770) — previously the experiment UI and service layer loaded scenarios directly via `cms.scenarios.loader`, bypassing `ScenarioMetadata` access controls

### Changed
- Experiment create form uses `list_all_scenarios(user)` from the scenario registry instead of raw YAML loader, so non-staff users only see scenarios they're allowed to use
- `create_experiment()` service checks scenario access via `check_scenario_access()` before creating the experiment
- `get_scenario_instances()` AJAX endpoint passes the requesting user for access checking
- Experiment services use `load_scenario_template()` from the registry (checks DB first, then YAML) instead of `load_scenario()` from the raw loader

## [3.11.0] - 2026-03-14

### Changed
- CTF organizer admin views now use Mission Control layout (`mission_control/base.html`) instead of separate CTF portal — organizers see the full MC sidebar with ranges, terminal, assets, etc.
- Added "CTF Admin" nav item to Mission Control sidebar for organizers (between Risk Register and Scenario Editor)
- Dashboard router sends CTF organizers to Mission Control dashboard instead of CTF admin dashboard — fixes dual-role users losing access to MC launch panel (GH #758)
- Removed separate CTF organizer sidebar (`ctf_organizer_sidebar.html`) — organizers use the standard MC sidebar

## [3.10.0] - 2026-03-14

## Changed
- Update Claude Code model versions (Sonnet 4.5, Haiku 4.5)

## [3.9.0] - 2026-03-13

### Changed
- CTF participants now land on Mission Control dashboard instead of separate CTF UI — reuses existing range, terminal, and Guacamole views
- Magic link registration (`/ctf/register/`) redirects to Mission Control dashboard
- Dashboard router sends CTF participants to Mission Control
- Dev login redirects CTF participants to Mission Control
- MC sidebar hides Assets, Docs, Settings, and Help nav items for CTF participants (shows only Ranges and Terminal)
- MC dashboard hides Launch Range form for CTF participants (their ranges are pre-provisioned by organizers)
- Dashboard JS skips launch UI initialization in view-only mode for CTF participants

## [3.8.0] - 2026-03-13

### Changed
- CTF participants are auto-registered (Django user created, status set to `registered`) when added individually or via CSV import — eliminates the separate "registration" step
- Magic link emails can be sent to any participant at any time, regardless of status — removed registered-participant guard from `resend_invite()`
- "Send All Links" button now sends to all participants, not just uninvited ones
- Per-participant "Send Link" button always visible in participant list (was hidden after registration)
- Invitation email wording updated: "Click below to access your event" / "Access Event" (was "To register" / "Register Now")

## [3.7.1] - 2026-03-13

### Added
- `list_ranges` MCP tool — list ranges with status, user, scenario, instance count, and timestamps; supports filtering by status and username
- `get_range` MCP tool — get detailed range info including instances and subnet allocations
- `list_subnet_allocations` MCP tool — list subnet CIDR allocations with optional status/VPC filtering

## [3.7.0] - 2026-03-13

### Added
- `SubnetAllocation` model and migration (`engine_subnetallocation` table) to reserve CIDRs during concurrent provisioning, preventing TOCTOU race condition where multiple ranges pick the same subnet CIDR
- Subnet allocation table is checked alongside AWS `describe_subnets` during CIDR selection; stale reservations (>30min) are automatically reclaimed
- `confirm_subnet_allocations()` / `release_subnet_allocations()` lifecycle hooks called on provision success, destroy, and failure (Terraform path)
- `SubnetAllocationAdmin` registered in Django admin for ops visibility
- 7 new tests for allocation table integration (reserve, skip-reserved, stale-reclaim, released-reuse, confirm, release, DB-fallback)

## [3.6.0] - 2026-03-13

### Fixed
- CI deploy workflow (`_shifter-platform.yml`) now passes `EMAIL_BACKEND` and `CTF_FROM_EMAIL` env vars to containers (emails were silently going to console backend)
- EC2 IAM role missing `ses:GetSendQuota` permission required by `django-ses` backend (applied via Terraform)
- `get_scoreboard` and `get_team_scoreboard` annotation `total_score` collided with model `@property` of the same name, causing 500 on participant dashboard, admin scoreboard, and scoreboard API (renamed annotation to `computed_score`)
- Invite token expiry now uses event end time directly instead of `min(7 days, event_end)`, ensuring tokens remain valid through the entire event

### Changed
- `agentic_workshop` scenario template simplified from two-subnet to single flat subnet topology (multi-subnet isolation doesn't work without NGFW; attack path enforced by challenge design instead)

### Added
- CTF range management JavaScript (`static/js/ctf-ranges.js`) with `CTFRangeManager` class wiring Provision All, per-participant Provision, and per-participant Destroy buttons to API endpoints
- Per-participant range API endpoints: `POST /ctf/api/participants/<id>/range/provision/` and `POST /ctf/api/participants/<id>/range/destroy/`
- 20 Jest tests for `CTFRangeManager` covering all button interactions, error handling, and loading states

## [3.5.0] - 2026-03-13

### Added
- `ami_key` optional field on `InstanceConfig`, `InstanceSpec`, and `InstanceContextBase` for custom AMI support
- Provisioner resolves `ami_key` to AMI ID via SSM `/shifter/ami/<ami_key>` and passes per-instance `ami_id` to Terraform
- `get_ami_id()` now accepts arbitrary SSM parameter suffixes (custom ami_key values), not just the 4 known types
- Terraform `ami_id` per-instance override: when non-empty, bypasses the `os_type` AMI lookup
- `agentic_workshop` scenario template: 6-box single-subnet CTF range with custom AMIs for vibe hacking workshop

## [3.4.1] - 2026-03-13

### Fixed
- `resend_invite` now actually sends the invitation email (previously only refreshed the token without emailing)
- `user_data.sh` includes `localhost,127.0.0.1` in `DJANGO_ALLOWED_HOSTS` for SSM tunnel access
- `user_data.sh` stops `ctf-scheduler` container during redeployment (was missing from stop list)

## [3.4.0] - 2026-03-13

### Changed
- CTF RBAC migrated from `UserProfile.user_type` CharField to Django Groups (`CTF Organizer`, `CTF Participant`), enabling users to hold both roles simultaneously
- `get_user_role()` now checks Django group membership instead of `UserProfile.user_type`
- `_set_ctf_participant_profile` / `_clear_ctf_participant_profile` use additive/subtractive group operations instead of overwriting `user_type`
- OIDC callback and dev login add/remove Django groups instead of setting `user_type` field
- Dashboard router uses `shared.auth` helpers instead of `UserProfile` properties
- `UserProfile.is_ctf_organizer` / `is_ctf_participant` properties now delegate to group membership (deprecated, use `shared.auth` helpers)

### Added
- Data migration `0004_ctf_groups` creates `CTF Organizer` and `CTF Participant` groups and migrates existing users
- `shared.auth`: `CTF_ORGANIZER_GROUP`, `CTF_PARTICIPANT_GROUP` constants and `is_ctf_organizer()`, `is_ctf_participant()` helpers
- Dual-role test coverage (organizer who is also a participant)

## [3.3.0] - 2026-03-12

### Added
- Vibe Hacking Workshop CTF range: 5-box range with network topology for 90-minute workshop
- Packer templates for all CTF boxes: ctf-webshell, ctf-mailroom, ctf-helpdesk, ctf-devbox, ctf-vault
- Box 0 "WebShell" (Ubuntu walkthrough): Apache/PHP webshell -> sudo -> SUID privesc
- Box 1 "MailRoom" (Ubuntu): anonymous FTP -> credential pattern -> SSH -> PATH hijack privesc
- Box 2 "HelpDesk" (Windows): SMB cred leak -> RDP -> scheduled task abuse
- Box 3 "DevBox" (Ubuntu, dual-homed): command injection -> SSH key hunting -> GTFOBins sudo node
- Box 4 "Vault" (Windows, internal only): pivot target with WinRM, Backup Operators privesc, KeePass alt path
- Validation test scripts for each CTF box (setup verification)
- CTF scheduled task executor management command (`run_ctf_scheduler`) — polls for due `CTFScheduledTask` rows and dispatches SPIN_UP_RANGES, EVENT_START, EVENT_END, CLEANUP_RANGES, and SEND_REMINDER tasks with signal handling and heartbeat monitoring
- Throttled bulk range provisioning (`provision_event_ranges_throttled`) — spreads AWS resource creation across the spinup window with configurable delay clamped to [5, 120]s and graceful shutdown support
- Full Guacamole connection parameters (RDP credentials, SFTP config, SSH keys) for CTF range access via new `get_range_connection_info` bridge
- "Send All Invites" button on the CTF organizer participant list page with API endpoint
- Registration URL in CTF invitation emails (replaces raw invite token display)
- Event-driven range status sync from CMS to CTF via Django signal (`range_status_changed`) — updates `CTFParticipant.range_status` when CMS processes SNS range events
- Scenarios API endpoint (`/ctf/api/scenarios/`) for listing available CMS scenarios as JSON
- Datetime string parsing in event API POST/PUT handlers so JSON-submitted datetime strings are converted before reaching the service layer
- `range_spinup_minutes` field in event detail API GET response

### Changed
- CTF event create/edit form rewritten to use Mission Control AJAX pattern with XDR dark theme instead of Django form posts with Bootstrap
- CTF admin views and templates: replaced Bootstrap classes with XDR theme styling for visual consistency with Mission Control

### Fixed
- CTF participant registration now sets `UserProfile.user_type` and `active_ctf_event` directly, removing dependency on pre-configured Cognito custom claims for `ctf_participant_required` decorator
- CTF participant disqualification and deletion now clear `UserProfile` CTF fields
- `get_range_access_url` now passes RDP username/password, SFTP root directory, and SSH key to Guacamole instead of only hostname

### Removed
- Dead `_extract_ip_from_range_spec` helper in `ctf/services/range.py` (replaced by `get_range_connection_info` bridge)
- Django form-based event creation/edit views (replaced by AJAX pattern)

## [3.2.0] - 2026-03-12

### Added
- CTF scheduled task executor management command (`run_ctf_scheduler`) — polls for due `CTFScheduledTask` rows and dispatches SPIN_UP_RANGES, EVENT_START, EVENT_END, CLEANUP_RANGES, and SEND_REMINDER tasks with signal handling and heartbeat monitoring
- Throttled bulk range provisioning (`provision_event_ranges_throttled`) — spreads AWS resource creation across the spinup window with configurable delay clamped to [5, 120]s and graceful shutdown support
- Full Guacamole connection parameters (RDP credentials, SFTP config, SSH keys) for CTF range access via new `get_range_connection_info` bridge
- "Send All Invites" button on the CTF organizer participant list page with API endpoint
- Registration URL in CTF invitation emails (replaces raw invite token display)
- Event-driven range status sync from CMS to CTF via Django signal (`range_status_changed`) — updates `CTFParticipant.range_status` when CMS processes SNS range events

### Fixed
- CTF participant registration now sets `UserProfile.user_type` and `active_ctf_event` directly, removing dependency on pre-configured Cognito custom claims for `ctf_participant_required` decorator
- CTF participant disqualification and deletion now clear `UserProfile` CTF fields
- `get_range_access_url` now passes RDP username/password, SFTP root directory, and SSH key to Guacamole instead of only hostname

### Removed
- Dead `_extract_ip_from_range_spec` helper in `ctf/services/range.py` (replaced by `get_range_connection_info` bridge)

## [3.1.2] - 2026-03-12

### Fixed
- CTF event form: replace plain text `scenario_id` input with a dropdown populated from the CMS scenario registry
- CTF event form: add `is-invalid` CSS class to fields with errors for Bootstrap 5 error visibility
- CTF event form: validate submitted `scenario_id` exists in the scenario registry

## [3.1.1] - 2026-03-12

### Fixed
- Flag hashing bug: challenges created via admin form used bare SHA256, producing hashes that `verify_flag()` could never match; now uses `hash_flag()` from services
- Potential division by zero in scoring solve rate calculation
- Removed unreachable `return` statements in `api_participant_list` and `api_participant_detail`

### Security
- Add missing authorization decorators to 8 CTF API views: `api_challenge_list`, `api_challenge_detail`, `api_submit_flag`, `api_use_hint`, `api_submissions`, `api_range_status`, `api_range_access`, `api_scoreboard`
- Remove `invite_token` from API responses in `api_participant_list` and `api_participant_resend_invite`
- Replace SHA256 fallback with PBKDF2-SHA256 (600k iterations) for flag hashing when bcrypt is unavailable
- Add `# NOSONAR` annotations to hardcoded test/dev encryption keys in settings
- Add SNS topic KMS encryption in dev and prod Terraform environments
- Set `recovery_window_in_days = 7` for Secrets Manager in production (was 0)
- Pin Secrets Manager IAM policy ARNs to specific AWS account ID
- Add `#tfsec:ignore` justifications to required IAM wildcards and egress rules
- Add `# NOSONAR` annotation to dev auth bypass with justification

## [3.1.0] - 2026-03-12

### Added
- CTF admin team list, scoreboard, and analytics pages
- CTF help page with getting started content
- CTF API endpoints: event list/detail, challenge list/detail
- NGFW toggle in CTF event form (range_config)

### Changed
- CTF app uses bridge module (`ctf/bridges.py`) for all cross-domain integrations (CMS, management, mission_control)
- CTF scheduled tasks documented as database-only; no Celery dependency
- Email backend defaults to console for dev; configure via `EMAIL_BACKEND` env var for production
- Wire `EMAIL_BACKEND` and `CTF_FROM_EMAIL` through deployment pipeline (SSM → user_data.sh → Docker env → Django settings)

### Fixed
- Removed stale scheduler module reference from services docstring

### Removed
- Dead `mock_scheduler` fixture that patched non-existent `ctf.services.scheduler`

## [3.0.0] - 2026-03-11

### Added
- CTF (Capture The Flag) management platform — core app files: models, enums, services, admin, forms, migrations
- CTF config and routing integration: settings, URL routing, dashboard router, dev login user types, OIDC user type claims
- CTF views, URL routing, and templates: organizer admin views, participant views, API endpoints, 38 template files, email templates, sidebar partials
- UserProfile CTF fields: user_type, active_ctf_event, role properties (is_ctf_organizer, is_ctf_participant, is_standard_user)
- CTF test suite: 13 test files, 230 tests across models, auth, challenges, events, participant views, services (notification, range)
- CTF participant registration endpoint (`/ctf/register/`) to complete invite-link registration flow

### Fixed
- CTF invite emails never sent: `invite_participant()` and `bulk_import_participants()` prematurely set `invited_at`, causing `send_invitations()` to skip all participants
- CTF range provisioning: all ranges were created under the organizer's user, causing the second participant's range to fail the active-range check; now uses `participant.user`

### Security
- Add organizer ownership checks to 11 CTF views missing authorization: range list/provision APIs, notification list/create/send views and APIs, team list, scoreboard, analytics, and event detail API — non-owning organizers now get 403

## [2.3.3] - 2026-03-10

### Added
- SE Admin IAM Users Terraform module (`platform/terraform/global/se-admins/`) for managing PANW SE admin access to the dev AWS account

## [2.3.2] - 2026-02-24

### Fixed
- Logout button not working (GET request to POST-only `OIDCLogoutView`)

## [2.3.1] - 2026-02-24

### Added
- CyberScript DSL language reference documentation (`documentation/docs/cyberscript/`)
- Schema validators: unique instance names, `dc_config` required when `domain_controller: true`

### Fixed
- Threat Research RBAC sidebar visibility and auth redirect

## [2.3.0] - 2026-02-24

### Added
- Unified platform audit logging system
- Audit coverage for range pause/resume, experiments, scenario editor
- AuditLog entity types: experiment, scenario, script
- AuditLog actions: pause, resume, cancel
- Audit service tests (16 tests)

### Fixed
- audit_log() now swallows exceptions instead of re-raising (never breaks the application)
- Stale self.range_id references in SSH consumer after refactor
- Migrated agent events from deprecated ActivityLog to AuditLog

## [2.2.10] - 2026-02-23

### Added
- Threat Research RBAC group
- Threat Research access to Experiment Manager and Scenario Editor

## [2.2.9] - 2026-02-22

### Fixed
- Experiment runner integration fixes

## [2.2.8] - 2026-02-22

### Changed
- Finish experiment runner integration

## [2.2.7] - 2026-02-21

### Added
- Scenario Editor UAT plans

### Fixed
- Role enum validation for ScenarioTemplate

## [2.2.6] - 2026-02-21

### Changed
- Range pause/unpause uses Ready instead of Active status

## [2.2.5] - 2026-02-21

### Added
- MCP tools for SSM tunnel testing: start_portal_test_tunnel, stop_portal_test_tunnel
- localhost to ALLOWED_HOSTS in dev for tunnel access

## [2.2.4] - 2026-02-21

### Changed
- Enable dev_login in deployed dev environment for programmatic testing via SSM tunnel

## [2.2.3] - 2026-02-21

### Fixed
- Broken migration chain causes Django crash loop

## [2.2.2] - 2026-02-17

### Fixed
- Deploy script SSM waiter timeout - increased max attempts from 20 to 60 (15 minutes)

## [2.2.1] - 2026-02-16

### Changed
- Centralized script variable sanitization in Pydantic contexts for consistent and secure variable handling.
- Moved experiment template variable logic to shared `cyberscript` library to enable cross-layer reuse and validation.
- Hardened `ExperimentOrchestrator` with comprehensive exception handling and debug logging to ensure unexpected failures mark runs as FAILED rather than hanging.
- Standardized `ExperimentManager` services and views to match CMS defensive coding patterns, including uniform user validation and ORM result type checking.
- Refactored experiment creation flow to enforce model-level validation within atomic transactions.

## [2.2.0] - 2026-02-16

### Add
- Direct NGFW access for users

## [2.1.7] - 2026-02-16

### Added
- Cortex Broken Bank AMI

## [2.1.6] - 2026-02-16

### Added
- Add XDR Collector and Cloud Identity Engine agents to CMS
-
## [2.1.5] - 2026-02-15

### Changed
- Merged MCP-Shifter and MCP-NGFW into MCP-Ops
- MCP-Ops has range reconciliation tool to find and destroy orphaned instances
- Add better parsing for AWS to SonarQube

## [2.1.4] - 2026-02-15

### Fixed
- Shifter DB MCP no longer leaks connections to RDS

## [2.1.3] - 2026-02-15

### Fixed
- Failed ranges do not always get destroyed

## [2.1.2] - 2026-02-14

### Fixed
- Restrictive Egress rules in Network Firewall loosened to match XSIAM docs recommendations

## [2.1.1] - 2026-02-10

### Fixed
- Subnet `connected_to` semantics corrected: Terraform now creates security group rules on target subnet allowing traffic from source (was reversed)
- Range provisioning now reads NGFW data ENI ID from database instead of non-existent environment variable

### Changed
- Updated `connected_to` documentation to clarify unidirectional semantics (both subnets must list each other for bidirectional traffic)
- Updated basic_ngfw scenario template to have bidirectional subnet connectivity

## [2.1.0] - 2026-02-08

### Added
- Experiment Manager for creating and managing experiments

## [2.0.0] - 2026-02-07

### Added
- Scenario Editor for creating and editing CyberScript

## [1.1.3] - 2026-02-07

### Added
- Certipy to Kali AMI

## [1.1.2] - 2026-02-07

### Added
- Credentials details page

## [1.1.1] - 2026-02-07

### Changed
- Increased number of possible user subnets by decreasing subnet size

## [1.1.0] - 2026-02-06

### Changed
- Range pause/resume flow and UI updates

### Fixed
- Guacamole ECS service not deploying correctly

## [1.0.9] - 2026-02-02

### Fixed
- Claude errors due to using wrong small model
- Handle NGFW "starting" state correctly

## [1.0.8] - 2026-02-02

### Fixed
- Fix logic error handling non-NGFW scenarios

## [1.0.7] - 2026-02-01

### Fixed
- Refine Internet egress domains and CIDR to Palo Alto Networks published IPs instead of overbroad GCP IPs

## [1.0.6] - 2026-01-28

### Added
- MCP servers for Shifter DB, NGFW, and AWS ops
### Fixed
- NGFW destroy flow does not remove EC2 instances
- NGFW commands not piped to SSH as required
- Provisioner missing permission for deleting NGFW resources

## [1.0.5] - 2026-01-28

### Changed
- Updated SSH connection validation to handle difference between SSH being up and management plane being fully up

## [1.0.4] - 2026-01-28

### Fixed
- Hydrator no longer rejects empty folder fields for SCM creds

## [1.0.3] - 2026-01-27

### Fixed
- Some range boxes have unexpected Internet access


## [1.0.2] - 2026-01-25

### Added
- Range pause/resume flow and UI updates

## [1.0.1] - 2026-01-25

### Changed
- Migrated range and NGFW provisioning to Terraform

## [1.0.0] - 2026-01-21

### Added
- Cortex BYOT scenario (automation except for CIE and XDR collector)
- Cortex Deployment Experience scenario

### Changed
- Dashboard renamed to Ranges
- Ranges view uses multiple tiles for launch and active ranges
- NGFW flow handles prompting user to associate NGFW to SCM and XDR
- Removed legacy Terraform-based range provisioning
- Ubuntu box supports RDP/desktop access
- Users can set MFA to remember devices

### Fixed
- Django build does not include cyberscript shared library
- Extend and streamline NGFW stand up plan
- Dynamic subnet creation for ranges misses Shifter Platform creation
- Missing VPC route for kali
- VPC Internet egress not enforcing drop rule
- Kali RDP not working due to permissions on logs
- XDR not deployed on BYOT scenario DC
- Race condition in DC readiness and target attempt to join domain

## [0.10.7] - 2026-01-12

### Changed
- Extract all Cyberscript related code to shared library for reuse in Provisioner and Engine
-
## [0.10.6] - 2026-01-13

### Fixed
- Type conflict causes NGFW provisioning to fail
- CMS parses legacy and new range_spec formats for consumers

## [0.10.5] - 2026-01-12

### Fixed
- Provisioner ID mismatch causes range create status update to fail
- Range subnets have no route to s3 for agent downloads

## [1.0.4] - 2026-01-12

### Changed
- Extracted ssh key generation to shared library

## [1.0.3] - 2026-01-12

### Added
- Additional local dev support

### Fixed
- Provisioner ID mismatch causes range create status update to fail

## [1.0.0] - 2026-01-10

### Added
- NGFW create/destroy flow and UI
- NGFW's dynamically add routes for subnets in user ranges
- NGFW's dynamically pause if user has no active ranges
- CyberScript (DSL) templates and initial interpreter for all range operations (range, ngfw, dc, etc.)
- v1.0 of the Cortex BYOT scenario template
  - Two config options: Automated or Full Manual
  - Automated: NGFW, DC, 2x Workstations, Server, Attacker, domain join, XDR agent install, subnet routing
    - Remaining manual (automation coming soon): CIE, XDR Collector, Caldera
- Improved Bedrock logging and alarms
- Draft Cortex BYOT scenario template
- venv enforcer hook for Claude Code
- Guacamole RDP for Range instances
- User (not just technical) docs in Shifter

### Changed
- NGFW models and services refactored to use schemas
- Extended DSL and initial DSL interpreter implementation for NGFW flows
- Templates refactored to use CyberScript DSL
- Engine refactored to accept RequestSpec and interpret it into Engine models
- CyberScript subnets align with actual subnets in AWS
- AaC gate (service layer boundary violations at code or model level) fails will now block PRs
- AWS assets tagged to requests for cost tracking and cleanup
- Patched vulnerable urllib3, now on 2.6.3
- Update technical docs

### Fixed
- Dashboard range status updates and styling
- Better AaC checking in check_layer_imports script
- Sticky sesesions on Linux terminals: keep history, scrollback, etc when reconnecting
- tmux now used for Terminal UI sessions
- RDP copy/paste not working
- Packer does not clean up EC2 instance after build
- tmux Terminal UI sessions not allowing mouse scrolling

## [0.10.6] - 2025-01-09

### Added
- Guacamole RDP for Range instances

### Fixed
- tmux now used for Terminal UI sessions

## [0.10.5] - 2025-01-06

### Changed
- Added tmux install to Kali and Ubuntu AMIs

## [0.10.4] - 2025-01-06

### Fixed
- Hotfix for Home subnet CIDR conflict detection

## [0.10.3] - 2025-01-04

### Changed
- user_data for Shifter Platform deployment and ASG lifecycle hook

### Fixed
- Terminal timeouts, reconnects, and stability issues
- Range instance username mismatch

## [0.10.2] - 2025-01-04

### Changed
- GitHub runners replaced with auto-scaling ephemeral runners via terraform-aws-github-runner module
  - Scale from zero on workflow trigger
  - EC2 spot instances for cost savings
  - GitHub App authentication for secure runner registration
- Added runner-deploy.sh script for runner infrastructure management
- Added manual-deployment.md documentation for global terraform stacks


## [0.10.1] - 2025-01-02

### Added
- Cyber range DSL foundation (Shared Schema)
- Interactive cli app for Shifter AWS account bootstrap and infrastructure deployment
- Arch as Code foundation: Code and model level service layer boundary violation detection in CI/CD and pre-commit
- Independent processes consume range status updates
- Claude develop skill
- Centralized code coverage reporting

### Changed

- CMS services extraction edge cases and fixes
- Mission Control re-wire to use services
- Engine services extraction and implementation (excl pause/resume)
  - NGFW services deferred to upcoming patch
  - Mission Control re-wire deferred to upcoming patch
- Model migrations to respect service layer separation
- Redis replication for HA (single-node in dev, replication group in prod)
- SNS/SQS for range status updates with alarms
- Fault-tolerant fully alarmed range status consumer processes
- Unit test coverage improvements

### Fixed
- In-depth help check short circuited by Django middleware
- Remove dead code from service layer refactoring
- Frontend tests not included in pre-commit
- Remove stale Celery references
- Linting
- Some tests not called
- Pre-commit and CI/CD test, lint, quality, and sast coverage
- SonarQube coverage exclusions
- Tests for repo utility apps and Architecture as Code tests

## [0.10.0] - 2025-01-01

### Added
- CMS services extraction and implementation
- Unified Credential model

## [0.9.9] - 2025-12-31

### Added
- Management services implementation
  - cognito_sub update service
  - activity log service
  - user profile service

### Changed
- OIDC backend updated to use management services
- User profile model moved to management domain
- Activity log model moved to management domain

## [0.9.8] - 2025-12-31

### Added
- Portal NGFW Management UI (#416)
  - NGFW list view at `/mission-control/assets/ngfw/`
  - NGFW detail view with AWS resources, PAN-OS info, linked ranges
  - 5-step setup wizard (Name & Credentials → Registration → Confirm → Provisioning → Complete)
  - Deprovision confirmation view with linked ranges warning
  - API endpoints:
    - `GET /api/ngfw/list/` - List user's NGFWs
    - `POST /api/ngfw/` - Start provisioning
    - `GET /api/ngfw/<id>/status/` - Poll provisioning status
    - `POST /api/ngfw/<id>/start/` - Start NGFW
    - `POST /api/ngfw/<id>/stop/` - Stop NGFW
    - `POST /api/ngfw/<id>/deprovision/` - Deprovision NGFW
  - WebSocket consumer for real-time provisioning status updates
  - XDR manual configuration instructions with serial number display
  - 62 tests covering all views and APIs
- Test review skill (`.claude/skills/test-review/`)
  - 6 quality criteria with specific fail indicators
  - Anti-pattern catalog by severity (HIGH/MEDIUM/LOW)
  - Coverage gap detection checklist
  - Scoring formula and fix guidance

### Note
- NGFW API endpoints are stubbed pending Issue #414 (UserNGFWStack)
- UI is complete and functional with simulated provisioning flow

## [0.9.7] - 2025-12-30

### Security
- Hardened GitHub Actions OIDC IAM permissions to limit blast radius (#430)
  - Restricted `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:PutRolePolicy` to specific role name patterns
  - Restricted `iam:CreateInstanceProfile` to matching instance profile patterns
  - Restricted `iam:PassRole` to same role patterns
  - Allowed patterns: `dev-portal-*`, `prod-portal-*`, `dev-range-*`, `prod-range-*`, `shifter-*`, `github-actions-shifter-*`
  - Prevents attacker from creating arbitrary roles with `AdministratorAccess` if GHA is compromised

## [0.9.6] - 2025-12-30

### Added
- S3 cost budget alerts for dev and prod environments
  - Defense-in-depth monitoring for unusual S3 costs
  - Alerts at 80% of $50/month threshold

## [0.9.3] - 2025-12-30

### Added
- Windows victim AMI Packer build (#410)
  - `windows.pkr.hcl` Packer template with WinRM communicator
  - PowerShell provisioning scripts: base, services, tools, claude-code, sysprep
  - XAMPP, IIS, FTP Server, OpenSSH Server
  - Python 3.12, Node.js 20.x, Git
  - Claude Code configured for Bedrock (system PATH at `C:\Program Files\nodejs`)
  - WinRM enabled for remote management
  - Windows Defender disabled via GPO for XDR compatibility
  - EC2Launch v2 sysprep for AMI finalization
- GitHub Actions workflow support for Windows AMI builds

### Changed
- Updated packer README with Windows AMI documentation
- Updated victim-ami.md with Packer build instructions

## [0.9.2] - 2025-12-30

### Added
- Ubuntu victim AMI Packer configuration (#409)
  - `ubuntu.pkr.hcl` template following Kali pattern
  - Provisioning scripts: base.sh, services.sh, tools.sh, claude-code.sh
  - Services: Apache 2.4 with mod_php, MySQL 8.0, Docker, OpenSSH, vsftpd, Samba
  - Development tools: build-essential, Python 3, Node.js 20.x, Git
  - Claude Code configured for AWS Bedrock
- GitHub Actions workflow support for Ubuntu AMI builds
- Ubuntu test classes in shifter/packer/tests/test_packer.py

### Changed
- SSM parameter for victim AMI renamed from `/shifter/ami/victim` to `/shifter/ami/ubuntu`
- Terraform data sources updated for new SSM parameter name

## [0.9.1] - 2025-12-30

### Changed
- Engine architecture refactor (#413)
  - Executors moved to `executors/` (ssm_executor, ssh_executor)
  - Orchestrators moved to `orchestrators/` (setup_orchestrator)
  - Plans moved to `plans/` (setup_plan.py → base.py)
  - RangeStack moved to `stacks/`
  - New: `AWSExecutor`, `OpsOrchestrator` stubs
  - New: Base protocols for executors and orchestrators

## [0.9.0] - 2025-12-30

### Added
- NGFW database models for persistent per-user NGFW support (#412)
  - `SCMCredential` model for Strata Cloud Manager PIN-based registration
  - `NGFWDeploymentProfile` model for Software NGFW Credits authcodes
  - `UserNGFW` model for persistent NGFW instances
  - `Asset` and `Credential` abstract base classes with soft delete and expiration
- Field-level encryption for sensitive credentials using `django-encrypted-model-fields`
  - `scm_pin_value` and `authcode` fields encrypted at rest
  - `FIELD_ENCRYPTION_KEY` environment variable required in production
- Range model fields for NGFW integration
  - `ngfw` FK to UserNGFW (SET_NULL on delete)
  - `gwlb_endpoint_id` for GWLB endpoint tracking
- Django admin for new models (SCMCredential, NGFWDeploymentProfile, UserNGFW)
- Database grants for provisioner_lambda user on new tables
- NGFW infrastructure foundation for persistent per-user NGFW instances (#408)
  - Dedicated /22 subnet (10.1.4.0/22) for ~500 NGFW capacity
  - Management security group (SSH/HTTPS from Portal for management)
  - Dataplane security group (all VPC traffic via GWLB)
  - IAM role with S3 bootstrap read and CloudWatch Logs access
  - CloudWatch alarm for NGFW capacity (>400 triggers SNS alert)
  - Terraform outputs for Engine/Pulumi consumption

### Removed
- `StrataConfig` model (superseded by `SCMCredential` and `NGFWDeploymentProfile`)
- Range fields: `ngfw_enabled`, `strata_config`, `ngfw_instance_id`, `ngfw_untrust_ip`, `ngfw_trust_ip`

## [0.8.9] - 2025-12-29

### Added
- Packer infrastructure for reproducible AMI builds (#273)
- sshpass in Kali AMI for non-interactive SSH (#273)
- GitHub Actions workflow for AMI builds

## [0.8.8] - 2025-12-29

### Changed
- Remove redundant SSH security group rules (#290)

## [0.8.7] - 2025-12-29

### Added
- `standup_duration` property on Range model for tracking provisioning time

## [0.8.6] - 2025-12-29

### Changed
- Remove Step Functions permissions from GitHub OIDC role (cleanup after v1 provisioner removal)

## [0.8.5] - 2025-12-29

### Fixed
- Dashboard dropdown behavior and portal test stability

## [0.8.4] - 2025-12-29

### Changed
- Extract service layer from views.py (engine, cms apps)
- Centralize Range status groupings as frozenset constants

## [0.8.3] - 2025-12-29

### Changes
- Refactor consumers.py for maintanability

## [0.8.2] - 2025-12-27

### Added
- NGFW (VM-Series) support
- Strata Cloud Manager support
- Cortex XDR sidebar submenu styling
- Asset Menu

### Changes
- GitGuardian and Snyk ignore tests

## [0.8.1] - 2025-12-27

### Changed
- Migrate all instances to Shifter Engine
- Docs updated to reflect new architecture and naming conventions

## [0.8.0] - 2025-12-27

### Added
- Domain controller AMI
- Basic AD scenario option with AD join by Windows
- Re-factor Shifter Engine scenario generation for extensibility

### Changed
- SonarQube ignores test files

## [0.7.20] - 2025-12-24

### Added
- JavaScript unit tests for DirectUploader (upload.js) with Jest (#136)
  - 79 tests covering happy paths, failure modes, edge cases, order of operations
  - Proper mocks for fetch, XMLHttpRequest, navigator.sendBeacon, window events
  - `make test-js` and `make test-js-coverage` Makefile targets
  - CI integration via `portal-js-tests` job in quality workflow

## [0.7.19] - 2025-12-24
- Add TDD planning Claude Code skill

## [0.7.18] - 2025-12-24

### Added
- Claude Code Skills for common repo/ops tasks

## [0.7.17] - 2025-12-24

### Changed
- Risk register app is accessible only by admin
- Removed History sidebar item (not yet working)
- Terminal page and link handles no active range gracefully

## [0.7.16] - 2025-12-23

### Added
- Developer documentation section (`docs/dev/`) with onboarding guides
  - Local setup, CI/CD, secrets management, Terraform patterns, engineering principles
- Commit tfvars to repository (no longer gitignored)
- Dev-box admin password auto-generated and stored in Secrets Manager

### Changed
- Removed `*.tfvars` from `.gitignore` - config values are not secrets
- Dev-box no longer requires manual password in tfvars

### Removed
- `terraform.tfvars.example` files (redundant now that tfvars are committed)
- `admin_password` variable from dev-box Terraform

## [0.7.15] - 2025-12-23

### Added
- Documentation section in Mission Control sidebar
- Renders markdown docs from `shifter/shifter_platform/documentation/docs/` with navigation tree
- Mermaid.js diagram support for architecture diagrams
- Cortex XDR dark theme styling for documentation pages

## [0.7.14] - 2025-12-22

### Fixed
- Terminal UI text overflows container

## [0.7.13] - 2025-12-22

### Fixed
- Terminal UI does not show IP address for Windows victims

## [0.7.12] - 2025-12-22

### Added
- Windows victim support in provisioner v2
- Windows victim AMI v3 with XAMPP, Claude Code, Python, Git, IIS, FTP, OpenSSH
- Terminal UI SSH support for Windows victims (Administrator username)
- Database migration granting provisioner SELECT on operatingsystem table

### Fixed
- Range destroy race condition leads to subnet collision
- Django logs not forwarded to CloudWatch
- Windows AMI sysprep: Claude Code installed to system path (`C:\Program Files\nodejs`)
- Windows Defender disabled via policy to avoid XDR conflicts

## [0.7.11] - 2025-12-21

.deb and .rpm packages confirmed fix as part of provisioner v2 in 0.7.7

### Added
- Provisioner confirms assigned subnet index is available before provisioning

### Fixed
- Kali boots slow due to redundant kali headless install
- Failed range auto-cleanup not running in dev


## [0.7.10] - 2025-12-21

### Fixed
- Provisioner fails to install .deb or .rpm agent packages properly
- Provisioner fails to rollback range if agent installation fails

## [0.7.9] - 2025-12-21

### Fixed
- Provisioner uses vars for instance types instead of hardcoded values

## [0.7.8] - 2025-12-21

### Added
- Standing dev box instance for development and testing

## [0.7.7] - 2025-12-21

### Added
- Pulumi-based provisioner for declarative multi-OS range infrastructure
  - ECS Fargate execution with Step Functions orchestration
  - S3/DynamoDB state backend, ECR container registry
  - Reusable components: NetworkComponent, InstanceComponent, RangeStack
  - Instance catalog supporting Kali, Ubuntu, Windows, Amazon Linux
- CI/CD workflow for Pulumi provisioner (`_pulumi-provisioner.yml`)
- Django model fields and service routing for v1 (Lambda) / v2 (Pulumi) provisioners
- Self-hosted GitHub Actions runner for CI/CD

### Changed
- Range instance types bumped to t3.medium (4GB min for Claude Code)
- CI Docker builds use local caching instead of GitHub Actions cache

### Fixed
- Secrets Manager resources now Pulumi-managed (proper lifecycle, no orphans)
- KMS policy, DNS egress, availability zone configuration for ECS tasks
- WebSocket terminal consumer reads from `provisioned_instances` field (v2 provisioner compatibility)

### Removed
- V1 (Lambda) provisioner

## [0.7.6] - 2025-12-19

### Added
- ALB access logs, VPC flow logs, RDS log exports, WAF logging
- XDR CloudTrail integration via CloudFormation (dev and prod)
- CloudWatch alarms for log aggregation (Firehose delivery lag, SQS DLQ)

### Changed
- Replaced Checkov skip comments with actual implementations (CKV_AWS_91, CKV2_AWS_11, CKV_AWS_129)
- Removed unused XDR IAM from Terraform (managed by CloudFormation instead)

### Fixed
- Multiple code quality, security, and code smells

## [0.7.5] - 2025-12-18

### Added
- AWS WAF protection for ALB with rate limiting and AWS managed rules

## [0.7.4] - 2025-12-18

### Added
- ElastiCache Redis module for Django Channels
- Portal autoscaling: launch template, ASG, scaling policies, CloudWatch alarms
- ALB session stickiness for WebSocket affinity
- Lambda auto-fix for range security group SSH rules from Portal VPC

### Changed
- Django Channels uses Redis when `REDIS_HOST` env var set, falls back to InMemory
- EC2 module supports single instance or ASG mode via `enable_autoscaling` flag
- Dev environment: autoscaling enabled with 2 instances
- GitHub Actions portal workflow supports ASG deployment via SSM targeting by tag
- IAM: Added `elasticache_asg` policy for ElastiCache, Auto Scaling, and Launch Template permissions


## [0.7.3] - 2025-12-17

### Fixed
- VPC peering TF drift dev/prod

### Fixed
- Network Firewall blocking XDR agent egress to Cortex cloud
  - Changed from STRICT_ORDER to DEFAULT_ACTION_ORDER for domain allowlist
  - Added Suricata rule to block direct IP connections (SNI bypass prevention)
- XDR agent not registering with tenant after installation
  - Added cortex.conf deployment before running installer script

## [0.7.2] - 2025-12-17

### Changed
- Removed redundant connection status from terminal header
- Increased terminal padding for better readability

## [0.7.1] - 2025-12-16

### Fixed
- XDR agent not installing on victim EC2 instances (#274)
  - Root cause: User data script used `aws s3 cp` but victim EC2 lacks AWS CLI
  - Changed to presigned URL + curl for agent download (no AWS CLI required)
  - Added SSM-based agent verification before marking range as ready
- CI/CD pipeline not updating Step Functions and Lambdas on code changes
  - Root cause: Missing `output_file_mode` in `archive_file` caused inconsistent zip hashes across CI runners
  - Added `output_file_mode = "0666"` to all Lambda archive_file blocks
  - Extracted Step Functions definitions to external ASL JSON files with `templatefile()`
- Dashboard polling errors when session expires during range provisioning
  - CORS errors occurred when API redirected to Cognito for re-authentication
  - Added session expiration detection and automatic redirect to login page
  - Network Firewall blocking XDR agent egress to Cortex cloud
    - Changed from STRICT_ORDER to DEFAULT_ACTION_ORDER for domain allowlist
    - Added Suricata rule to block direct IP connections (SNI bypass prevention)
  - XDR agent not registering with tenant after installation
    - Added cortex.conf deployment before running installer script

### Added
- Agent verification step in provisioning workflow
  - New `verify_agent` Lambda checks installation via SSM RunCommand
  - Step Functions retry loop with 30s intervals (5 min max)
  - Ranges fail fast with descriptive error if agent install fails
- External ASL state machine definitions for better maintainability
  - `provision_range.asl.json`, `teardown_range.asl.json`, `cleanup_stale_ranges.asl.json`

## [0.7.0] - 2025-12-16

### Added
- Claude Code on Kali and Victim AMIs for AI-assisted penetration testing
  - Configured for Amazon Bedrock (no internet required)
  - Role-specific CLAUDE.md system prompts for each instance type
  - Kali: Authorized pentester role with subnet-only scope
  - Victim: Scenario setup assistant for vulnerable configurations
- Bedrock VPC endpoints (bedrock-runtime, sts) for Range VPC
- Bedrock IAM permissions for range instance role

### Changed
- Increased Portal EC2 instance to t3.large (from t3.micro) for WebSocket stability
- Increased Kali and Victim instances to t3.small for Claude Code memory requirements

## [0.6.0] - 2025-12-16

### Added
- Browser-based Terminal UI for SSH access to range instances (#267)
  - Side-by-side Kali and Victim terminal panes with xterm.js
  - WebSocket-based SSH via Django Channels
  - Terminal sidebar menu item with active range indicator
- VPC peering between Portal and Range VPCs for SSH connectivity
- Security group rules allowing SSH from Portal to range instances

### Changed
- Switched from Gunicorn (WSGI) to Daphne (ASGI) for WebSocket support

### Fixed
- Buttons should not have underline

## [0.5.4] - 2025-12-15

### Removed
- OpenWebUI/AgentChat infrastructure (#261)
  - Deleted agentchat Terraform modules and environments
  - Removed MCP-Shifter and OpenWebUI MCP wrapper code
  - Removed agentchat GitHub Actions workflows
  - Removed ECR repositories for openwebui and mcp-shifter
  - Removed Cognito agentchat client
  - Removed openwebui_db Secrets Manager secret
  - Removed agentchat documentation
  - Removed migrations for victim_mcp_user and kali_mcp_user rename
- Entire MCP directory (`mcp/`) including aptl-mcp-common and mcp-red

### Changed
- Architecture updated: Chat UI replaced with planned browser-based terminal (Django Channels)
- `chat_base_url` now optional in provisioner module (empty string allowed)
- Updated CLAUDE.md and architecture docs to reflect new terminal-based approach

## [0.5.3] - 2025-12-15

### Added
- TARGET_MODE parameterization for MCP-Shifter (`kali` or `victim`)
  - Same binary serves both target types via environment variable
  - Dynamic column selection based on target mode
  - Tool prefixes match target type (`kali_*` or `victim_*`)
- Victim MCP database user (`victim_mcp_user`) for operational isolation
- Renamed `mcp_user` to `kali_mcp_user` for consistency
- SSM VPC Endpoints for Range VPC (ssm, ssmmessages, ec2messages)
  - Enables Systems Manager access without internet
  - Traffic stays within AWS network
- Custom OpenWebUI Docker image with Cortex theme baked in
  - ECR repository for custom OpenWebUI image
  - Dockerfile extends base image with custom CSS/assets
  - CI/CD builds and deploys themed image automatically
- Victim MCP wrapper for OpenWebUI (`mcp_wrapper_victim.py`)

### Changed
- Replaced mcp-red with mcp-shifter in CI quality workflow
- Architecture docs updated with MCP dual-container diagram
- AgentChat uses custom OpenWebUI image instead of stock ghcr.io image

## Fixed
- Missing s3 permissions to fetch XDR installer
- Fix range user_data fails to account for different installer types

## [0.5.2] - 2025-12-15

### Changed
- Reskin OpenWeb UI UX to match Cortex XDR look and feel

## [0.5.1] - 2025-12-15

### Added
- AWS Network Firewall for Range VPC egress filtering (#251)
- NAT Gateway for private subnet internet access
- Domain allowlists: Victim restricted to XDR endpoints, Kali has no external access

## [0.5.0] - 2025-12-14

### Added
- MCP-Shifter server for OpenWebUI integration (`mcp/mcp-shifter/`)
  - Cognito JWT authentication with per-user session management
  - RDS IAM authentication for range lookup
  - Secrets Manager integration for SSH key retrieval
  - Session limits (per-user and global) with structured logging
  - Idle connection cleanup timer
  - StreamableHTTPServerTransport for MCP over HTTP
- OpenWebUI MCP wrapper tool (`mcp/openwebui-mcp-wrapper/`)
- `cognito_sub` column on Range model for MCP user lookups
- Custom OIDC backend passing Cognito `sub` claim to Range model
- Security context in MCP server description (authorized pentest boundaries)
- VPC peering between Portal VPC and Range VPC for SSH connectivity
- ALB listener rules for `/chat` and `/mcp` path routing
- IAM policies for MCP server (RDS connect, Secrets Manager read)
- Security group rules for SSH from AgentChat to Kali instances
- Cognito app client for OpenWebUI OIDC authentication
- AgentChat docker-compose for local development (`agentchat/`)
- SSH keypair generation in create_kali Lambda (stored in Secrets Manager)
- `kali_ssh_key_secret_arn` field on Range model

### Changed
- AgentChat deployment workflow includes mcp-shifter container
- mark_ready Lambda sets chat_url when range becomes ready
- - AgentChat routing changed from subpath (`/chat/`) to subdomain (`chat.{domain}`)
- ACM certificate includes SAN for `chat.{domain}` subdomain
- Cognito OAuth callbacks updated for subdomain URLs
- ALB listener rules use `host_header` matching instead of `path_pattern`
- Docker layer caching added to portal and agentchat CI/CD workflows (faster builds)

## [0.4.5] - 2025-12-15
### Changed
- Reskin Portal and Risk Register to Cortex XDR look and feel

## [0.4.4] - 2025-12-14

### Changed

- Upgraded patch @modelcontextprotocol/sdk

## [0.4.3] - 2025-12-13

### Added
- Risk Register Django app
-
## [0.4.2] - 2025-12-13

### Added
- OpenWebUI + Bedrock Access Gateway (BAG) for AgentChat
- Sonnet 4.5 and DeepSeek R1 models for AgentChat
- AgentChat infrastructure
- Checkov IaC security scanning in CI and pre-commit
- Dockerfile HEALTHCHECK for portal container

### Changed
- SonarCloud coverage extended to all modules
- GitHub Actions workflows: explicit permissions, removed workflow_dispatch inputs where not needed
- Use SonarQube Cloud automatic analysis instead of CI/CD workflows

### Security
- Full review of lint (ruff, bandit, eslint) and IaC (checkov) findings
- Fixed critical issues: workflow permissions, Dockerfile healthcheck
- Created issues (#214-222) for deferred security hardening (WAF, flow logs, KMS, etc.)
- All checkov findings now have explicit skip comments with issue references

## [0.4.1] - 2025-12-12

### Removed
- LibreChat
- LiteLLM

## [0.4.0] - 2025-12-12

### Added
- Dev environment (`terraform/environments/dev/`)
- Branch-based deployments: `dev` branch → dev, `main` branch → prod
- Bootstrap script for new AWS accounts (`scripts/bootstrap-dev.sh`)

### Changed
- All workflows support environment selection via branch or manual dispatch
- Streamline GitHub Actions workflows for consistency
- Utility scripts work with dev and prod environments
- User updated immediately when range deploy fails

## [0.3.6] - 2025-12-11

### Fixed
- Remove default value from s3_bucket_arn variable (module variables should have no defaults)

## [0.3.5] - 2025-12-11

### Changed
- Make no versioning on user data s3 bucket explicit

## [0.3.4] - 2025-12-11

### Added
- AWS Bedrock as LibreChat LLM provider

### Changed
- LibreChat EC2 instance rebuilds on user_data changes

## [0.3.3] - 2025-12-11

### Changed
- RDS deletion protection enabled for prod database
- Final snapshot enabled before RDS deletion

## [0.3.2] - 2025-12-11

### Added
- Kali EC2 provisioning Lambda (create_kali) with official AWS Marketplace AMI
- Kali security group in Range VPC with bidirectional victim traffic
- kali_instance_id and kali_ip fields on Range model
- Kali cleanup in teardown Lambda
- Range VPC security documentation (security groups, traffic matrix, isolation)

### Changed
- Victim security group now allows all inbound from Kali SG (for attacks)
- Kali security group allows all inbound from Victim SG (reverse shells, C2)

## [0.3.1] - 2025-12-11

### Added
- LibreChat infrastructure (EC2, dedicated subnet, Secrets Manager, Docker Compose)
- LibreChat CI/CD workflows (infra and deploy)
- SSM tunnel script for LibreChat admin access

### Fixed
- Portal/LibreChat infra workflows now trigger on direct push to main, not just upstream cascade

## [0.3.0] - 2025-12-11

### Added
- Provisioner fields on Range model (subnet_id, subnet_cidr, subnet_index, victim_instance_id, step_function_execution_arn)
- IAM Database Authentication on RDS for Lambda provisioner
- Django migration to create provisioner_lambda PostgreSQL user with minimal permissions
- Provisioner Lambda functions (create_subnet, create_victim, create_kali, configure_librechat, cleanup)
- Step Functions state machines for provisioning and teardown with error handling and timeouts
- Victim security group in Range VPC
- Provisioner module wiring to Portal VPC with remote state references
- Portal integration with Step Functions (replaces callback-based stub)
- EC2 IAM permissions for Step Functions execution
- Range failure alarms
- Stale range cleanup
- docs/maintenance.md: RDS maintenance window reference

### Fixed
- Lambda DB queries: `agent_config_id` → `agent_id`, `os_type_id` → `os_id` (Django FK naming)
- Lambda handlers: `range_id[:8]` slice on integer (range_id is int, not UUID)
- db-connect.sh: Added autocommit for INSERT/UPDATE queries
- IAM policy: Fix `ec2:CreateSubnet` permission (unsupported `ec2:Vpc` condition key)
- Cleanup Lambda: Allow teardown from `ready` state (mark_failed=false)

### Removed
- Callback endpoint for provisioner (Lambda writes directly to DB)

## [0.2.9] - 2025-12-09

### Fixed
- AWS_REGION mismatch
- ALB health check errors
- Update docs

## [0.2.8] - 2025-12-09

### Fixed
- Range provisioner missing env var for domain
- Remove default site url for range provisioner

## [0.2.7] - 2025-12-09

### Added
- Dashboard Range launch flow with live status polling
- Range API endpoints (status, launch, cancel, destroy, callback)
- Range model status fields (pending, provisioning, ready, paused, resuming, destroying, destroyed, failed)
- Stub provisioner service with HMAC-signed callback tokens
- Client-side DashboardManager for state management
- State transition validation to prevent callback replay attacks

## [0.2.6] - 2025-12-08

### Fixed
- Upload lock clears on page navigation/error (beforeunload + 30s timeout fallback)

## [0.2.5] - 2025-12-08

### Added
- 2GB file upload via presigned S3 URLs with progress indicator
- 5GB per-user storage quota
- Upload cancel/abort support
- S3 CORS configuration for browser uploads
- S3 lifecycle rule for orphan cleanup

## [0.2.4] - 2025-12-08

### Fixed
- Logout now clears Cognito session (redirects to Cognito /logout endpoint)
- Local dev logout uses dev_logout instead of OIDC logout

## [0.2.3] - 2025-12-08

### Fixed
- Agent uploads failing: container now uses EC2 instance role via IMDSv2

### Removed
- Static IAM user credentials for portal container

## [0.2.2] - 2025-12-08

### Added
- Agent upload to S3 with magic byte validation
- File type validation (.msi, .zip, .tar.gz, .tgz, .deb, .rpm)
- Agent delete with S3 cleanup
- S3 bucket env var in deploy workflow

## [0.2.1] - 2025-12-08

### Added
- Mission Control data models (OperatingSystem, UserProfile, AgentConfig, Range, ActivityLog)
- Django admin registration for all models
- UserProfile auto-creation signal
- Model unit tests (21 tests, 100% coverage)

## [0.2.0] - 2025-12-08

### Added
- Mission Control UI shell (Dashboard, Agents, History, Settings, Help)
- Dev auth bypass for local testing
- User stories: Help, Language, Notifications

## [0.1.19] - 2025-12-08

### Changed
- Updated license to proprietary
- Block access to /admin from public internet

## [0.1.18] - 2025-12-08

### Changed
- Improved portal coming soon page design

## [0.1.17] - 2025-12-08

### Fixed
- Insecure TLS config in MCP HTTP client (removed global NODE_TLS_REJECT_UNAUTHORIZED)
- Portal deploy/infra workflow race condition (workflow_run trigger + concurrency)

### Security
- Upgraded @modelcontextprotocol/sdk to 1.24.3 (CVE-2025-66414 DNS rebinding fix)

## [0.1.16] - 2025-12-08

### Changed
- README update

## [0.1.15] - 2025-12-07

### Added
- Landing page at / to prevent redirect loop after OIDC auth

## [0.1.14] - 2025-12-07

### Fixed
- Cognito secret retrieval from Secrets Manager (issuer -> issuer_url key)

## [0.1.13] - 2025-12-07

### Added
- S3 user storage module for file uploads (agents, etc.)
- GitHub Actions IAM permissions for S3 bucket management

## [0.1.12] - 2025-12-07

### Added
- Range VPC module - stable VPC, IGW, route table
- Range environment config
- Range infrastructure workflow
- Range infrastructure documentation

## [0.1.11] - 2025-12-07

### Added
- Cognito Terraform module (user pool, client, hosted UI domain)
- Pre-signup Lambda for email domain restriction
- Auth architecture docs
- Wire Cognito into portal environment
- EC2 module accepts list of secret ARNs
- IAM permissions for Cognito and Lambda
- Django OIDC integration (mozilla-django-oidc)
- Entrypoint fetches Cognito secrets from Secrets Manager
- Deploy workflow passes COGNITO_SECRET_ARN to container

## [0.1.10] - 2025-12-07

### Fixed
- Hardcoded domain in Django ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS replaced with domain from tfvars secret

## [0.1.9] - 2025-12-07

### Fixed
- IAM permissions for SSM SendCommandToInstances
- Staticfiles directory permission error in container

## [0.1.13] - 2025-12-07

### Added
- S3 user storage module for file uploads (agents, etc.)
- GitHub Actions IAM permissions for S3 bucket management

## [0.1.8] - 2025-12-07

### Added
- Django portal Docker setup (multi-stage Dockerfile with uv)
- Container entrypoint with DB wait, migrations, gunicorn
- docker-compose.yml for local dev with Postgres
- Makefile with dev commands (up, down, build, logs, shell, migrate, init)
- GitHub Actions workflow for portal build, ECR push, SSM deploy
- Portal dev documentation
- Secrets management: IAM user for prod, Secrets Manager for DB + app secrets

### Changed
- Architecture docs updated with portal deployment pipeline
- GitHub OIDC role gets SSM permissions for deployments

## [0.1.7] - 2025-12-07

### Added
- Portal EC2 module (Docker host, SSM access, ECR/Secrets Manager IAM)
- Portal ALB module (ACM certificate, HTTPS listener, target group)
- Environment wiring with terraform_remote_state for ECR
- IAM permissions for EC2, ELB, ACM
- Security documentation
- Ethics documentation
- Disclaimer in README

### Changed
- Architecture docs updated for EC2+ALB (was ECS)
- ECR authentication via credential helper (replaces manual docker login)

### Security
- IMDSv2 enforced on EC2 (SSRF mitigation)
- ALB drops invalid HTTP headers
- ACM certificate validation with 45m timeout

## [0.1.6] - 2025-12-05

### Fixed
- Missing IAM permissions for ec2:ModifySubnetAttribute and iam:CreateServiceLinkedRole (RDS)

## [0.1.5] - 2025-12-05

### Added
- Portal VPC module (public/private subnets, NAT gateway)
- Portal RDS module (PostgreSQL, Secrets Manager credentials)
- Namespaced tfvars sync script (`TF_VARS_{ENV}_{COMPONENT}`)
- IAM permissions for VPC, RDS, Secrets Manager, KMS

## [0.1.4] - 2025-12-05

### Added
- Terraform foundation infrastructure (ECR module, global IAM, environment structure)
- GitHub Actions OIDC authentication for AWS
- CI/CD workflow for infrastructure deployment
- Version bump script

## [0.1.3] - 2025-12-05

### Added
- MkDocs with Material theme
- Documentation site (architecture, setup, API reference)
- GitHub Actions workflow for automatic GitHub Pages deployment
- Mermaid.js diagrams in architecture docs

## [0.1.2] - 2025-12-04

### Added

- Image assets for docs

### Changed
- Updated CLAUDE.md to reflect new architecture
- Removed unused files from .gitignore
- Only run mcp tests on code change

## [0.1.1] - 2025-12-04

### Added
- SonarCloud integration
- Build and test workflow
- Quality gate badge to README

### Fixed
- npm version mismatch

### Changed
- Upgraded vitest from 1.x to 4.x (required code changes to test files due to breaking changes)
## [0.1.0] - 2025-12-04

### Added
- Initial Shifter architecture for self-service cyber range platform
- Core MCP library (`mcp/aptl-mcp-common`) with SSH session management
- Reference MCP server (`mcp/mcp-red`) as template for new MCPs
- SonarCloud integration with automated code quality scanning
- Test coverage reporting via vitest with lcov output

### Changed
- Forked from APTL (Advanced Purple Team Lab) with new direction

### Removed
- All Docker/Wazuh infrastructure (replaced by XDR/XSIAM integration)
- Container definitions (kali, victim, gaming-api, minetest, minecraft, reverse)
- CTF scenarios (will be AI-generated dynamically)
- Local deployment scripts
