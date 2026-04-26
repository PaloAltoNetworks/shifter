# aces-sdl validation path — APTL first, then replace cyberscript in shifter

## Intent

The aces-sdl project is a backend-agnostic scenario description language.
For that claim to be meaningful we must prove the same scenario can be
realised through more than one independent backend. The validation path:

1. **First**: build one or more backends in **APTL** (public OSS) that
   consume aces-sdl scenarios as input. APTL is cheap to iterate against
   and OSS, so no scenario-sensitive content lands in its tree.
2. **Then**: translate Polaris to aces-sdl and drive it through the APTL
   backend(s) end-to-end. A live range that passes Polaris's existing
   smoketests is the acceptance gate. If that works, backend-agnosticism
   is proven in practice, not just on paper.
3. **Then**: incorporate aces-sdl into shifter, replacing the existing
   `cyberscript` scenario DSL. Authoring Polaris (and any future
   shifter scenario) in aces-sdl is the endgame. APTL is the stepping
   stone that de-risks that swap.

## Invariants while we are in steps (1) and (2)

- `aces-sdl` and any APTL backend package MUST stay scenario-agnostic.
  No Polaris / Boreas / Aurora / Northstorm identifiers anywhere in the
  public-repo source. Polaris is tested against the public capability,
  but Polaris content never lives in the public tree.
- The aces-sdl reference/regression fixture is a generic kitchen-sink
  scenario (currently `examples/scenarios/enterprise-red-team-reference.sdl.yaml`).
  Polaris is NOT the regression fixture upstream.
- The Polaris translation lives entirely in shifter under
  `scenario-dev/polaris/`:
  - `sdl/` — the scenario in aces-sdl form
  - `content-packages/polaris/` — seed data (AD, mail, git, SQL, PDFs,
    modbus state, GPG material, etc.) the generic content generators
    consume at range-build time
  - `containers/images.yaml` — scenario → image realisation mapping
  - `containers/<image>/` — Dockerfiles for images the scenario needs.
    Most are generic patterns (openssh workstation, Flask intranet,
    Postfix+Dovecot, Kali + xrdp, pymodbus launcher). One
    (`brain-controller`) is genuinely scenario-specific.

Keeping those in shifter **is correct for now** even though some of the
container Dockerfiles are generic patterns. See "deferred cleanup" below.

## Deferred cleanup — done at step (3), not before

When aces-sdl lands in shifter and starts replacing cyberscript, **that
is the correct moment** to extract the genuinely generic base images
(e.g. `openssh-workstation`, `flask-intranet-base`, `postfix-dovecot`,
`pymodbus-plc-launcher`, `alpine-ssh`, `kali-xrdp`) out of
`scenario-dev/polaris/containers/` and push them down into APTL as
reusable image templates. The scenario-specific overrides (Boreas user
list in the intranet app, `boreas.local` domain in the mail config,
the brain-controller protocol) stay in shifter.

Do NOT perform that extraction earlier. Reasons:

- The generics are small; rewriting them later is cheap.
- Moving them now adds coupling across three repos (aces-sdl, APTL,
  shifter) during the period when we most need flexibility.
- When we swap cyberscript for aces-sdl we will touch those container
  definitions anyway; extraction there is incremental, not a separate
  refactor.

## Cyberscript is the thing that goes away

The legacy scenario DSL in shifter is **cyberscript**. The target end
state is:

- cyberscript removed from shifter
- aces-sdl integrated into shifter as the only scenario description
  language
- Polaris (and successor scenarios) authored in aces-sdl directly,
  with content packages + image realisation manifest as today

Any discussion of "aces-sdl vs cyberscript" should resolve in favour
of aces-sdl as the target, with cyberscript as the thing being
retired.

## Current state (check-in as of this writing)

Work in progress on local branches, nothing pushed:

- `aces-sdl` worktree `polaris-translation` — 13 additive SDL
  extensions (AD OU/privileges/SPN, topology mutations, prerequisite
  metrics, hints, replication strategy, controlled-vocabulary
  extensions), new kitchen-sink reference scenario, tests.
- `APTL` worktree `polaris-backend` — two new top-level folders:
  - `aces_backend/` — docker + adjacent VM realisation
  - `aces_backend_libvirt/` — pure libvirt realisation
  Both consume aces-sdl scenarios. Twelve real content generators
  (pdf, docx, xlsx, email-box, git-repo, postgres-seed, smb-share,
  ad-directory-seed, modbus-register-state, gpg-*, binary-blob, plus
  text/config formats) live under `aces_backend/content_generators/`.
- `shifter/scenario-dev/polaris/` — the Polaris scenario expressed in
  aces-sdl (`sdl/`), its content packages (`content-packages/`), and
  the image realisation map + Dockerfiles (`containers/`).

No live deploy has occurred in any AWS account. The next milestone is
deploying APTL + aces-sdl + the Polaris translation into a clean
(non-panw) AWS account and running Polaris's existing smoketests
against the realised range.
