# Release Please Preflight (#1776)

Status: binding pre-implementation guidance

Date: 2026-07-20

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1776>

## Resolution (implementation, #1776)

During implementation the user directed that Shifter adopt the exact
release-please process already running in the sibling repositories (`aces-sdl`,
`aptl`, `aces-scenario-workbench`): the `release-please-action` creates the
`vX.Y.Z` tag and GitHub Release via the ephemeral `GITHUB_TOKEN`, with a `main`
to `dev` back-merge job. That process supersedes two stricter recommendations in
the guidance below:

- **Tag signing:** the CI-created release tag is not GPG/OIDC signed. The
  baseline `v3.103.0` transition tag is still created manually with the
  maintainer's key; `vX.Y.Z` tags from `3.104.0` onward are created by the
  action. ADR-042-R2 was reconciled accordingly.
- **PR-title types:** the shared PR-title validator keeps the retained
  Keep-a-Changelog types (`security`, `added`, `changed`, `deprecated`,
  `removed`, `fixed`) as valid non-bumping titles alongside the Conventional
  Commit types; only `feat`, `fix`, `perf`, and a breaking marker bump.
  ADR-042-R4 was reconciled accordingly.

The umbrella-version, sole-CHANGELOG-writer, lossless-final-transition,
run-on-main, back-merge, and least-privilege-workflow decisions below are
unchanged and binding.

## Scope And Decisions

Shifter has one umbrella release version. It is a deployed platform whose
components are changed, promoted, and supported together; the repository does
not publish its Python, Node, Terraform, or Helm subtrees as independently
versioned products. Configure one Release Please package at `.` with
`include-component-in-tag: false`, a `simple` release strategy, and package name
`shifter`.

A Shifter release means a signed annotated `vX.Y.Z` tag and GitHub Release for
one protected-`main` source commit. It is a source/provenance and support
coordinate. It does not deploy an environment, publish a Python/Node/Helm
package, or create a new container-image coordinate. Existing deployments
remain bound to an exact source revision and verified OCI digest under ADR-037;
a SemVer tag must not replace the digest as deployment identity.

Release Please becomes the only release coordinator and `CHANGELOG.md` writer.
Towncrier is replaced, not retained as a second input. Conventional Commit
subjects on `main` determine the version bump and generated notes:

| Signal | Meaning |
| --- | --- |
| `feat:` | backward-compatible platform capability; minor bump |
| `fix:` or `perf:` | backward-compatible correction; patch bump |
| `feat!:` / `fix!:` or `BREAKING CHANGE:` | incompatible supported contract; major bump |
| `docs`, `chore`, `refactor`, `test`, `ci`, `build` | non-release maintenance |

Security fixes use `fix(security):`; dependency fixes use `fix(deps):` when they
should cut a patch. The former towncrier types (`added`, `changed`, `fixed`, and
so on) must not remain as a parallel release taxonomy: several are not Release
Please releasable units and therefore cannot reliably drive a bump.

## Version And Branch Boundaries

- `.release-please-manifest.json` records the last released umbrella version.
- The `simple` releaser's root `version.txt` is the committed current-version
  mirror. It is not an application runtime setting.
- `vX.Y.Z` plus its signed tag target identifies released source. The GitHub
  Release is the public metadata projection of that tag.
- The versions in the 12 Python package roots, Node package roots, and
  `platform/charts/shifter/Chart.yaml` retain their existing component/tooling
  meanings. Do not add them as `extra-files` merely because they contain a
  field named `version`.
- The release workflow targets protected `main` explicitly. `dev` remains the
  integration branch; feature PRs target `dev`, and promotion preserves their
  commits when `dev` is merged to `main`.
- Feature PRs into `dev` must be squash-merged with the validated PR title as
  the squash commit subject. A green PR-title check alone is insufficient if
  the merge method produces `Merge pull request ...` or otherwise hides the
  title from Release Please. The `dev` to `main` promotion must preserve the
  squashed feature commits rather than squash the whole release train into one
  opaque promotion commit.
- A release commit exists only on `main` initially. Reuse the sibling ACES
  main-to-dev back-merge convention: open or update one narrowly identified,
  human-merged `main` to `dev` PR. Never force-update `main` or `dev`, and do not
  exempt all PRs involving `dev` from title or policy checks.

The latest inspected release is signed annotated tag `v3.102.0`. The first
Release Please manifest baseline must equal the newest real transition tag; it
must not reuse a published version or infer an umbrella version from a
component's `0.1.0`/`1.0.0` metadata.

## Transition Integrity

At preflight time `changelog.d/` contains 408 pending fragment files. They are
release data, not disposable migration debris. Before Release Please is
activated, a final Towncrier-owned release must consume every pending fragment
into a correctly rendered `CHANGELOG.md`, and the matching signed tag and
GitHub Release must exist on `main`. Seed the manifest from that exact version
and bound Release Please's initial history scan to that release commit.

Do not activate Release Please against `v3.102.0` and silently delete the
pending fragments: current history contains plain merge commits, duplicated
branch-merge history, and many non-conventional subjects, while the fragments
carry curated notes not recoverable from commit headings. The transition check
must also catch the existing malformed adjacent bullets in the `3.102.0`
section so new generated sections render as valid Markdown while historical
content remains preserved.

After that boundary, remove the Towncrier config, fragment directory, custom
template, `CHANGELOG.md merge=union` rule, and every fragment requirement or
instruction in one ownership change. Do not keep an empty `changelog.d/` as a
compatibility signal.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required boundary |
| --- | --- | --- |
| Release workflow | Current ACES `release-please.yml` patterns; `googleapis/release-please-action` | Use manifest mode, explicit `main`, serialized runs, immutable action SHAs, and one root package. |
| Signed tag lineage | Existing signed annotated Shifter tags; the ACES scenario-packs keyless tag gate | Do not silently downgrade releases to unsigned/lightweight tags. Keep Release Please in PR-only mode if a separate, fail-closed signer creates the tag and GitHub Release. |
| Changelog ownership | `CHANGELOG.md`, `towncrier.toml`, `changelog.d/README.md`, `.gitattributes` | Preserve history and pending notes at cutover, then leave Release Please as the sole writer. |
| Commit signal | `.github/workflows/pr-title-lint.yml`, `CONTRIBUTING.md`, Dependabot config | Enforce standard release-bearing types on feature PRs to `dev`; preserve the title in the squash commit; make Dependabot titles compatible. |
| Branch lifecycle | `dev` integration, `main` stable promotion, existing sibling back-merge workflow | Release on `main`; sync the release commit back through a normal PR without creating a second release loop. |
| Ground Control | Root `release-please-config.json` auto-detection and `gc_render_pr_body` release-please mode | Remove the fragment rule from `.gc/plan-rules.md`. Do not invent a `.ground-control.yaml` `changelog_mode` key: Ground Control deliberately detects the root config. |
| Workflow policy | ADR-002/003/004/037, `actionlint`, `adr_guard`, `.github/quality-path-filters.yaml`, Dependabot | Keep guardrail docs synchronized, classify the new release files, pin actions by full SHA, and retain existing checks. |
| Deployment provenance | `_shifter-engine.yml`, `_shifter-platform.yml`, `_gcp-dev.yml`, ADR-037 | Keep source SHA, image digest validation, SBOM, and attestations authoritative. A release tag is not a deploy trigger or image selector. |

No application controller, DTO, service, repository, database record, runtime
config schema, exception hierarchy, or logging framework is warranted. Release
state persists in the manifest, Git tag, and GitHub Release; application and
deployment persistence remain untouched.

## Security And Cross-Cutting Layers

- **Workflow event/auth surface:** run only on `push` to protected `main`; do
  not use `pull_request_target` or execute an untrusted PR checkout. A tag-sign
  job must bind the exact protected workflow identity and source SHA.
- **Permissions:** default to `contents: read`. Give the Release Please job only
  `contents: write` and `pull-requests: write`; give a separate keyless signing
  job only the narrow `contents: write` and `id-token: write` it needs. Release
  automation receives no AWS, GCP, package-registry, deployment-environment,
  issue-write, or self-hosted-runner authority.
- **Secret handling:** prefer the ephemeral `GITHUB_TOKEN` and OIDC signing;
  add no PAT or static signing key. Pass the token as an action input or masked
  environment value, never in a remote URL, generated file, process argument,
  artifact, summary, release note, or log. GitHub-created PR checks may require
  a maintainer to approve their run; do not replace that touchpoint with an
  admin merge that bypasses required checks.
- **Input/config shape:** `release-please-config.json` and the manifest must be
  valid JSON and conform to Release Please's official config schema. Validate
  strict SemVer, a single `.` package, `vX.Y.Z`, full source SHA, expected
  repository, manifest/version agreement, release-PR identity, and existing-tag
  target before any tag or Release write. Titles, API JSON, branch names, and
  action outputs are untrusted data and must enter shell steps through quoted
  environment variables or parsed files, never expression interpolation into
  shell source.
- **Repository validators:** workflow changes pass `actionlint`; all changes
  pass `python3 scripts/adr_guard/adr_guard.py --all --level ci`; release config,
  workflow, manifest, and `version.txt` receive explicit parse/contract tests;
  path ownership and Dependabot action pinning remain synchronized. The
  release PR must pass the canonical repository quality graph, not a smaller
  release-specific copy.
- **Runtime/env-binding shape:** no Django settings, installation schema,
  Terraform variable, Helm value, Kubernetes environment variable, or host
  `.env` entry is added. The release version remains build/repository metadata.
- **OS/process exposure:** use a GitHub-hosted runner. Checkout of protected
  source disables persisted credentials when shell git operations are needed;
  GitHub auth stays in masked environment, and signing uses short-lived OIDC.
- **Error/log surface:** failures are bounded GitHub annotations and non-zero
  exits naming the invalid field or state. Do not dump API response bodies,
  tokens, environment contents, commit bodies, or signing material. Release
  notes are public and must not contain secret/internal operational detail.

Tagging is an idempotent write boundary: an existing `vX.Y.Z` may be reused only
when it is signed by the expected workflow identity and dereferences to the
exact release commit. A mismatched existing tag fails closed; tags are never
deleted or force-moved to make a rerun pass.

## Extensibility Seam

The only package-selection seam is the `packages` map in
`release-please-config.json`. It contains only `.` now. A future independently
published component may be added only after an explicit product/lifecycle
decision; its mere possession of `pyproject.toml`, `package.json`, or
`Chart.yaml` is not evidence that it is independently releasable.

The only release-to-artifact seam is a job gated by Release Please's
`release_created` output and consuming its version/tag/source outputs. It is
empty for this issue. A future container or package publication may attach
there without changing umbrella version ownership or making release creation a
deployment event.

The authentication seam is the action's `token` input. Start with
`GITHUB_TOKEN`; if unattended bot-PR checks later become an explicit
requirement, substitute a narrowly scoped, short-lived GitHub App installation
token. Do not spread credential selection through shell commands or add a PAT
as an implicit workaround.

## Gotchas And Anti-Patterns

- Do not configure one Release Please package per language directory, Terraform
  root, MCP server, or Helm chart. That confuses source layout with product
  lifecycle and creates tags that do not correspond to independently shipped
  artifacts.
- Do not bump every `version` field with `extra-files`; package, chart,
  protocol, migration, and umbrella release versions are different concepts.
- Do not assume the current PR-title workflow is a sufficient foundation: it
  skips every PR whose base or head is `dev`, which includes normal feature PRs.
- Do not accept the old towncrier types in the title gate after cutover. A
  syntactically valid `added:` or `security:` commit can be invisible to the
  version strategy.
- Do not run Release Please on `dev`, tag an integration-only commit, squash
  the whole `dev` promotion, or let the `main` to `dev` sync trigger a release.
- Do not hand-edit generated release sections, the manifest, or `version.txt`
  during ordinary feature work. Correct a note through the documented Release
  Please commit-override mechanism before the release PR is merged.
- Do not rely on a GitHub `release` event for continuation: writes made with
  `GITHUB_TOKEN` do not reliably start a new workflow. Keep dependent release
  work in the same run or an explicitly called reusable workflow.
- Do not auto-deploy from a tag, introduce mutable SemVer image tags, weaken
  digest verification, or treat a GitHub Release as evidence that an
  environment is healthy.

## Non-Goals

- Publishing any Python, Node, Terraform, Helm, VM image, or OCI artifact.
- Changing runtime version APIs, banners, logs, settings, configuration files,
  persistence, migrations, or application error envelopes.
- Changing deployment, promotion, rollback, image-digest, SBOM, or attestation
  behavior.
- Independent component versioning, compatibility matrices, release trains, or
  prerelease channels.
- Automated merging of release or back-merge PRs, branch-protection redesign,
  or a long-lived GitHub credential.
