# Polaris Onboarding First-Click Preflight

Issue: GitHub #704, "Polaris UX: orientation page + briefing deck don't show
participants where to go first."

This note records the architecture boundary for the future implementation. It is
intentionally not an implementation plan.

## Boundary

The fix is participant-facing event collateral for Polaris onboarding:

- The CTFd orientation page in `scenario-dev/polaris/build/ctfd-pages/index.md`.
- The briefing deck under `scenario-dev/polaris/briefing-deck/`.
- A printable seat handout source, if added, colocated with the briefing
  collateral rather than with range runtime content.

The goal is to make the first action path explicit: get to the board, launch
the range through the existing Mission Control/magic-link flow, click
`ENTER RANGE`, then solve the CTFd Start Here warm-up from `/challenges`.

This issue does not require a new participant auth flow, CTFd plugin, Shifter
range controller, scenario schema, CTFd sync client, or generated deck pipeline.
It should change source-controlled content and only use the existing sync and
preview workflows to publish or inspect that content.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Scenario source order | `scenario-dev/polaris/README.md` | Reconcile against `build/`, CTFd JSON, pages, and walkthroughs before older design prose or notes. |
| CTFd page source | `scenario-dev/polaris/build/ctfd-pages/index.md` | Keep front matter valid and preserve `route: index`, `format: markdown`, and `auth_required: true`. |
| CTFd page parsing/upsert | `scripts/ctfd-workshop/ctfd_reconcile.py::parse_page`, `load_pages`, `upsert_page` | Do not edit live CTFd admin state as the source of truth. Repo content must be syncable through the existing scripts. |
| CTFd board sync | `sync_polaris_ctfd.py`, `sync_polaris_ctfd_onboarding.py`, `common.CtfdClient` | Reuse token auth, JSON handling, page sync, and pagination. Do not add another CTFd client or schema for a copy-only fix. |
| Start Here warm-up | `scenario-dev/polaris/build/ctfd-onboarding.json`, `build/A14-kali/welcome.txt` | The first-step command/copy must align with the checked-in warm-up challenge and Kali welcome file. Do not duplicate flags or challenge metadata into a new schema. |
| Briefing deck source | `scenario-dev/polaris/briefing-deck/index.html`, `styles.css`, `deck.js`, `README.md` | The deck is intentionally static and hand-authored. Add or adjust slide sections and scoped CSS classes; do not introduce a templater/build step for this issue. |
| Speaker notes | `scenario-dev/polaris/briefing-deck/script.md` | Projected content and spoken handoff must say the same literal path. Do not rely on verbal-only instructions. |
| Event feedback | `scenario-dev/polaris/lessons-4.md` | Use it as problem context, not as another participant-facing source that must be read during the event. |
| Participant/user creation | `scripts/ctfd-workshop/create_users.py` and its generated output | Seat-specific credential CSVs are operational artifacts and must stay untracked. A generic handout may say "your registered email" and the shared event password already present in the deck, but must not commit per-participant credentials. |

## Cross-Cutting Layers

Security layers the future design must satisfy:

- CTFd auth surface: the orientation page remains an authenticated CTFd page.
  The hero CTA to `/challenges` is a navigation affordance, not an
  authorization decision. Do not make hidden/draft pages public or add a bypass
  link to private content.
- Shifter range auth surface: the deck and handout may point participants to
  the existing Mission Control/magic-link flow and `ENTER RANGE`, but should not
  change Django views, magic-link handling, range provisioning, or participant
  permissions.
- CTFd page shape gate: `parse_page` requires front matter with `title` and
  `route` and will pass the Markdown/HTML body through CTFd. Keep the page body
  static: scoped CSS under `.polaris-page`, normal links, and no `<script>`,
  inline event handlers, forms, tracking pixels, or remote assets.
- CTFd sync shape: publishing page changes should flow through
  `sync_polaris_ctfd.py` or `sync_polaris_ctfd_onboarding.py`. If an operator
  uses dry-run, it must not be described as live verification.
- Secret handling: do not print, commit, or add examples containing CTFd admin
  tokens, magic-link tokens, generated participant passwords, private keys, or
  raw credential CSVs. Do not include the Start Here `FLAG{...}` value on the
  handout or in the deck.
- Operational credential copy: the existing shared board password in the deck
  is event collateral, not a platform secret, but it is still public-facing
  cohort text. Keep it in participant-facing artifacts only; do not promote it
  into config, tests, sync logs, or scripts.
- OS/process exposure: keep CTFd admin tokens in `CTFD_TOKEN` or a local token
  file if sync is run. Do not pass tokens, magic links, participant credentials,
  or flags through process argv, shell snippets, QR-code generators, or
  generated filenames.
- Config and env binding: this content fix should not introduce new runtime
  environment variables, Terraform variables, Kubernetes secrets, or Django
  settings. Event-specific URLs belong in the reviewed collateral until a
  separate generator is justified.
- Error envelopes and logs: existing sync output may name page routes and
  challenge names. New validation or print-generation helpers, if any, must not
  dump full page bodies, credential rows, magic links, admin tokens, or flags.
- Repository validation: architecture/doc changes pass
  `python3 scripts/adr_guard/adr_guard.py --all --level ci`. Content-only
  Polaris edits should also be previewed locally with the deck server or CTFd
  page sync dry-run as appropriate.

Maintainability incumbents the implementation must build on:

- `scenario-dev/polaris/README.md` for source-of-truth ordering.
- `scenario-dev/polaris/build/ctfd-pages/index.md` and the existing CTFd page
  front-matter contract.
- `scenario-dev/polaris/build/ctfd-onboarding.json` and
  `build/A14-kali/welcome.txt` for the warm-up challenge contract.
- `scripts/ctfd-workshop/ctfd_reconcile.py` plus the two Polaris sync entrypoints
  for page/challenge publishing.
- `scenario-dev/polaris/briefing-deck/README.md`, `index.html`, `styles.css`,
  `deck.js`, and `script.md` for the static deck workflow.

Extensibility seam:

Keep the future seam at the event-handoff value boundary:
`ctfd_base_url`, `mission_control_url`, `credential_display`,
`start_challenge_path`, and `first_step_command`. For this issue, those values
can remain explicit in reviewed static artifacts. If another cohort needs the
same artifacts with different URLs or credentials, introduce a small reviewed
handoff data source or generator at that boundary only. Do not turn it into a
new CTFd challenge schema, range DTO, deck framework, or participant identity
system.

Whole-repo surfaces in scope for the future implementation:

- `scenario-dev/polaris/build/ctfd-pages/index.md`
- `scenario-dev/polaris/build/ctfd-pages/kali-quickstart.md` if the CTA copy
  references quickstart content.
- `scenario-dev/polaris/build/ctfd-onboarding.json`
- `scenario-dev/polaris/build/A14-kali/welcome.txt`
- `scenario-dev/polaris/briefing-deck/index.html`
- `scenario-dev/polaris/briefing-deck/styles.css`
- `scenario-dev/polaris/briefing-deck/deck.js` only if navigation semantics
  truly change.
- `scenario-dev/polaris/briefing-deck/script.md`
- `scenario-dev/polaris/briefing-deck/README.md`
- A new printable handout source under `scenario-dev/polaris/briefing-deck/`,
  if the implementation adds one.
- `scripts/ctfd-workshop/README.md`, `sync_polaris_ctfd.py`,
  `sync_polaris_ctfd_onboarding.py`, and `ctfd_reconcile.py` for publish
  workflow compatibility.
- `scenario-dev/polaris/lessons-4.md` as feedback provenance.
- `docs/architecture/polaris-scenario-bake-preflight-618.md`,
  `polaris-scenario-smoketest-preflight-617.md`, and
  `polaris-ctfd-sync-preflight-702.md` for adjacent boundaries.

## Gotchas And Anti-Patterns

- Do not make `/challenges` the only visible first action if participants still
  need to launch Kali first. The CTA, deck, and handout must agree on the
  sequence.
- The current deck has a "Good Hunting" closing slide before board/range/URL
  slides. Ensure the final projected handoff is the literal click path, not a
  narrative signoff followed by optional operational slides.
- Do not bury "First Moves" below narrative copy. The page must put the begin
  action above mission flavor.
- Do not rename the CTFd `index` route, make the page unauthenticated, or move
  orientation content into a live-only CTFd admin edit.
- Do not commit participant lists, magic links, generated passwords, or
  credential CSVs while adding a handout.
- Do not print the warm-up flag value in the deck or seat handout. If the
  handout includes an exact first command, make its spoiler level intentional
  and keep it consistent with `ctfd-onboarding.json`.
- Do not add JavaScript, external CSS/images, QR-code tracking, or analytics to
  CTFd pages or the handout for this issue.
- Do not solve the copy problem by changing Shifter auth, CTFd permissions,
  challenge gating, range provisioning, Guacamole behavior, or Kali network
  access.
- Do not add duplicate schemas, duplicate validators, a second page parser, a
  second CTFd client, a deck build system, or a print pipeline unless a separate
  issue justifies it.
- Do not let the printable handout drift into a new canonical challenge guide.
  It is a first-click card; detailed mission reference stays in CTFd pages,
  challenge descriptions, and walkthroughs.

## Non-Goals

- Implementing the issue in this preflight.
- Reworking participant invites, magic links, CTFd login, Shifter range access,
  Guacamole reliability, provisioning, scoring, hints, flags, or challenge
  prerequisites.
- Replacing CTFd page sync, board sync, or Polaris smoketest architecture.
- Creating a generic onboarding CMS, scenario packaging framework, slide
  generator, or print-material generator.
- Mutating live CTFd, AWS, GCP, Terraform, Kubernetes, or production range
  state.
- Changing platform navigation, participant-side Django templates, locale
  strings, or event lifecycle unless a future implementation proves this
  content-only boundary is insufficient.
