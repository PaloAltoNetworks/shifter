# Polaris repo → AMI content drift audit

Issue: GitHub #618, "Eliminate post-bake hotfix pattern: audit scenario
drift and reduce repo→AMI content gap".

This is the item-1 deliverable of #618: an inventory of every Polaris
scenario artifact that reaches a participant range, which delivery path
carries it, and what happens when the `polaris-vm` AMI is rebaked from a
clean repository checkout. It complements the architecture boundary note
in [`polaris-scenario-bake-preflight-618.md`](polaris-scenario-bake-preflight-618.md).

## Why drift happens

A deployed Polaris range is fed by **three** content paths with very
different change-propagation behavior:

| Path | What it carries | How a change propagates | CI/CD |
| --- | --- | --- | --- |
| **A. Baked AMI** | The `scenario-dev/polaris/build/` docker-compose stack | Operator uploads a new build tarball to S3 **and** rebakes the `polaris-vm` AMI (`aws ec2 create-image`), then updates SSM `/shifter/ami/polaris-vm` | None until #618 item 4 |
| **B. Provisioner runtime** | `PolarisRangeBootstrapPlan` SSM steps | Provisioner container image auto-rebuilds on push to `main` (`deploy.yml`); applies to every new range | Yes |
| **C. CTFd board** | `ctfd-challenges.json`, onboarding, pages | `scripts/ctfd-workshop/sync_*` scripts push to the CTFd API | Operator-run |

Drift is the gap between what the repo says and what a deployed range
actually contains. It is structural: path A has no CI, so a content
change committed to `build/` does not reach ranges until someone
remembers to rebake. The delta is usually discovered at event time.

## Path A — content baked into the `polaris-vm` AMI

The AMI is a real baked image of a working range-0 docker-compose stack.
On a clean-checkout rebake, the only scenario content that appears on a
fresh range **without** a range-launch fetch is whatever the `build/`
tree's Dockerfiles copy or generate. The high-risk surfaces:

| Asset | Source in `build/` | Baked via | Clean-rebake behavior |
| --- | --- | --- | --- |
| A0 website + PDFs | `A0-boreas-website/site/`, `A0-boreas-website/build_pdfs.py`, `ctfd-challenges.json` | `a0/Dockerfile` | PDFs are regenerated at image-build time. Flag values must already be correct in the source — see "Flag 6" below. |
| A1 mail seed | `A1-mail-server/build_mail.py` | `a1/Dockerfile` | Regenerated from the generator script. |
| A3 / A5 / A10–A13 services | per-asset `server.py` | `a3/`,`a5/`,`a10/`–`a13/Dockerfile` | Copied from source as-is. |
| A4 document seed | `A4-file-share/build_documents.py` | `a4/Dockerfile` | Regenerated from the generator script. |
| A6 / A7 / A8 lab material | generator scripts, GPG material, bare repos, SQL, research keys | `a6/`,`a7/`,`a8/Dockerfile` | Copied/generated from source. |
| A9 splice content | README, scan results, Modbus helper | `a9/Dockerfile` | Copied from source. |
| A14 Kali overlay | `A14-kali/welcome.txt`, `A14-kali/claude_system_prompt.txt`, shared Modbus helper | `a14/Dockerfile` | Copied from source. `welcome.txt` (flag 0 / warm-up) is baked here — no longer a post-bake hotfix. |
| A15 / A16 pivot content | workstation content + intentionally embedded credentials | `a15/`,`a16/Dockerfile` | Copied from source. |
| DNS + topology | `build/dns/*`, `build/docker-compose.yml` | `dns/`, compose | Baked as-is; per-range DC IP is corrected at runtime (path B). |

`scenario-dev/polaris/tests/` is **not** baked — it is fetched from S3 at
range launch (path B, `polaris_fetch_tests`).

### Flag 6 — the canonical drift instance

`build_pdfs.py` generates `boreas-annual-2025.pdf` for A0. Before #619 the
generator never wrote flag 6 into the PDF, so every clean-checkout rebake
reproduced the "Ottawa bug": CTFd had `FLAG{c6f8d2b3e91a4507}` configured
but the artifact did not contain it. The fix sources the flag from the
CTFd board (`ctfd-challenges.json`, challenge 6) via `flag_for()` and
renders it on the Kursk line, so the PDF and the board cannot silently
diverge. A bake-time smoke (`build/verify_flags_baked.py`) greps every
rendered artifact for its canonical `FLAG{...}` and fails the bake on a
miss; the `polaris-scenario-bake.yml` workflow runs it.

## Path B — runtime customization (`PolarisRangeBootstrapPlan`)

`shifter/engine/provisioner/plans/polaris_range_bootstrap.py` runs after
`LinuxBootstrapPlan` against the polaris-vm host. Steps:

- `polaris_range_bootstrap` — rewrites `docker-compose.override.yml` with
  this range's DC IP and per-instance kali pubkey, force-recreates the
  `dns` + `a14-kali` containers, strips the baked splice-link pre-wiring.
- `polaris_fetch_tests` — pulls the `tests/` tree from S3.
- `polaris_install_splice_watcher` — installs the `polaris-splice-watcher`
  systemd service (attaches `a14-kali` to splice-link on flag 19).
- `polaris_kali_bedrock_shard` — writes `/etc/profile.d/claude-bedrock.sh`
  and the `/etc/hosts` Bedrock VPC-endpoint override inside `a14-kali`.

This path is the correct home for anything range-specific: the DC IP,
the per-instance SSH key, and the Bedrock VPCE private IP are all known
only at provision time and cannot be baked into an image.

## Retired post-bake hotfix layer

Before the bootstrap plan carried the splice watcher and bedrock shard,
three operator scripts under `scripts/polaris-aws-range/` patched
already-running ranges by SSM fan-out:

- `apply_splice_watcher.py` — splice-watcher install + `welcome.txt` drop.
- `apply_kali_bedrock_shard.py` — Bedrock env file + `/etc/hosts` override.
- `run_postprovision.sh` — supervisor that ran the two above.

All three are **removed** by #618. Their portable logic is in
`PolarisRangeBootstrapPlan` (path B) and `welcome.txt` is baked into
`a14/Dockerfile` (path A). Keeping them would re-create the dual-ownership
the issue exists to eliminate. `scripts/polaris-aws-range/` retains only
the bake-range Terraform and the read-only `check_range_health.py`.

## Known parallel: `build/` stack vs the aces-SDL realization

Polaris has a second, declarative realization under
`scenario-dev/polaris/containers/` + `sdl/polaris-operation-northstorm.sdl.yaml`,
resolved through `containers/images.yaml`. It is **not** what the live
event deploys — `build/docker-compose.yml` is. The two kali definitions
illustrate the divergence: the deployed `build/a14/Dockerfile` installs
`@anthropic-ai/claude-code`, while the SDL-path `containers/boreas-kali/Dockerfile`
does not. Reconciling or retiring the SDL path is out of scope for #618
(no aces-sdl migration); it is recorded here as a standing drift risk.

## Recommendations carried forward

- The operator bake is automated by `polaris-scenario-bake.yml` (#618
  item 4): `workflow_dispatch` only, mirroring `packer.yml`.
- Treat the Bedrock model id as a release-managed input — it is currently
  duplicated across `polaris_range_bootstrap.py` and the packer/config
  Claude scripts. Single-sourcing it is tracked separately, not in #618.
