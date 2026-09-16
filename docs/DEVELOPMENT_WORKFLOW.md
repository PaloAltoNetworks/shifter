# Development and release workflow

This document describes the branch model, the pull-request flow, and the
release model for Shifter. It is the reference cited by `CONTRIBUTING.md`,
`CHANGELOG.md`, and `.gc/plan-rules.md`.

## Branch model

- `dev` is the integration branch. All feature and fix work targets `dev`.
- `main` is the stable release line. It receives only `dev` to `main` promotion
  PRs and the release-please release PR; it never receives feature PRs or
  automated dependency bumps directly.

## Pull-request flow

1. Branch off `dev`.
2. Give the PR a Conventional Commit title (`<type>(<optional-scope>): <subject>`
   with a lowercase subject). The `pr-title-lint` workflow enforces the shape on
   every PR that targets `dev`.
3. Squash-merge the PR into `dev`. The squash makes the validated PR title the
   single commit subject that release-please reads once the change reaches
   `main`, so the title, not the individual work-in-progress commits, is the
   release signal.

Do not hand-edit `CHANGELOG.md` and do not add changelog fragments. release-please
owns both the changelog and the version (see below).

## Promoting dev to main

Open the promotion PR with `make devmain`. The target runs one `gh pr create`
against `Brad-Edwards/shifter` with `dev` as the head branch, `main` as the
base, a Conventional Commit title, and a body that restates the merge strategy.
It pins the repository explicitly because this checkout is a fork of
`PaloAltoNetworks/shifter`: an unpinned `gh pr create` resolves the base
repository to the fork parent and opens the promotion PR against the upstream
OSS repo.

Merge the promotion PR with a merge commit. Never squash it. A squash collapses
every Conventional Commit subject in the promotion into one, so release-please
reads a single subject on `main` instead of the individual feature titles, and
the release PR loses the correct version bump along with the changelog entries
for that release.

`pr-title-lint` runs on the promotion PR, because `Lint PR title` is a required
status check on `main` as well as on `dev`. The title `make devmain` sends
satisfies it. The lint is not a release signal here, since the promotion
preserves the feature commits rather than collapsing them into one: it runs so
that the required context reports, which a workflow scoped away from `main`
cannot do.

No check constrains how the promotion PR is merged. The target carries the
title; the maintainer carries the merge method.

## Release model

Releases are coordinated by [release-please](https://github.com/googleapis/release-please)
on `main`, configured by `release-please-config.json` and
`.release-please-manifest.json` at the repository root (ADR-042). Shifter uses a
single umbrella version: one root package (`release-type: simple`), one
`vX.Y.Z` tag, and one `CHANGELOG.md`. The root `version.txt` is the committed
mirror of the current version; it is repository metadata, not an application
runtime setting. The component `pyproject.toml`, `package.json`, and
`Chart.yaml` versions keep their own meanings and are not swept into the
umbrella bump.

On each push to `main`, release-please maintains a release PR
(`chore(main): release X.Y.Z`) that bumps `version.txt` and prepends a new
`CHANGELOG.md` section generated from the Conventional Commit history since the
last release. Merging that release PR creates the `vX.Y.Z` tag and the GitHub
Release, and the `sync-dev` job opens a `main` to `dev` back-merge PR so `dev`
picks up the version bump and changelog. That back-merge PR is merged by a
maintainer; automation never force-updates `main` or `dev`.

### What bumps the version

| Commit subject on `main` | Effect |
| --- | --- |
| `feat:` | minor bump |
| `fix:` or `perf:` | patch bump |
| `feat!:`, `fix!:`, or a `BREAKING CHANGE:` footer | major bump |
| `docs`, `chore`, `refactor`, `test`, `ci`, `build`, `revert` | no bump |
| retained Keep-a-Changelog types (`security`, `added`, `changed`, `deprecated`, `removed`, `fixed`) | no bump |

The retained Keep-a-Changelog types are accepted as valid PR titles for
continuity, but they do not cut a release. Use `feat`, `fix`, or `perf`, or a
breaking marker, when a change should produce a new version.

### What a release is, and is not

A release is a source and provenance coordinate: a `vX.Y.Z` tag plus a GitHub
Release bound to one `main` commit. It is not a deployment, a package
publication, or a container-image coordinate. Deployment identity remains the
exact source revision and the verified OCI image digest (ADR-037); a SemVer tag
is never a deploy trigger or an image selector.

The release tag and GitHub Release are created by the release-please action
using the workflow's ephemeral `GITHUB_TOKEN`, mirroring the sibling RAES
repositories. The release PR is opened by that token, so branch-protection
required checks do not run on it automatically; a maintainer merges it (admin).

## Towncrier to release-please transition (#1776)

Before this cutover, the changelog was managed with towncrier fragments under
`changelog.d/`. The transition consumed every pending fragment into a final
`## [3.103.0]` changelog section (preserving all content), then removed
`towncrier.toml`, `changelog.d/`, its template, and the `CHANGELOG.md merge=union`
attribute. release-please is now the sole changelog writer.

### One-time activation runbook (maintainer, on `main`)

The dev-side cutover (config, workflow, final changelog, tooling reconciliation)
lands through the normal `dev` PR. Activating release-please then requires two
maintainer actions on `main`, because `main` is protected:

1. Promote `dev` to `main` through the usual `dev` to `main` PR, preserving the
   feature commits.
2. On `main`, create the baseline tag `v3.103.0` at the promotion commit and a
   matching GitHub Release. `.release-please-manifest.json` already records
   `3.103.0`, so release-please treats this as the last released version and
   scans only commits after it.

From the next push to `main` onward, release-please opens the release PR for
`3.104.0` and later automatically; no further manual tagging is required for
routine releases.
