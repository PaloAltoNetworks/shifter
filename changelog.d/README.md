# Changelog fragments

Every PR with a user-visible change drops one tiny Markdown file in this
directory; the release process (`towncrier build`) collates the fragments
into [`../CHANGELOG.md`](../CHANGELOG.md) and removes the consumed files.

This exists because hand-editing the top of `CHANGELOG.md` in every PR
guaranteed merge conflicts whenever two PRs were open at once: every
rebase to clear the conflict re-triggered the full `Deploy` workflow on
the PR. Fragments live in their own files, so two PRs can never write to
the same path and the conflict goes away.

## Add a fragment

Create one file here per change, named:

```
<issue>.<type>.md
```

* `<issue>` is the GitHub issue or PR number, used to render `(#NNN)`
  next to the bullet. If the change has no issue/PR (e.g. a typo fix),
  prefix the slug with `+` and the suffix is suppressed:
  `+fix-typo.fixed.md`.
* `<type>` is one of (Keep a Changelog sections, in this order):
  * `security` — vulnerability fixes / hardening
  * `added` — new features
  * `changed` — changes to existing behaviour
  * `deprecated` — soon-to-be-removed features
  * `removed` — removed features
  * `fixed` — bug fixes

The file body is the bullet text. Markdown is allowed (bold, code spans,
links). Keep it to one paragraph per fragment; if a change really needs
several bullets, split it across several fragments.

### Example

`966.security.md`:

```markdown
**GCP portal runtime no longer derives its Django security posture from
managed-TLS readiness, and now fails closed.** `scripts/gcp/render_runtime_env.py`
previously used a single `secure_portal_mode` flag to switch debug,
secure cookies, and the auth provider together; the renderer now emits
the production runtime profile unconditionally and refuses to render an
HTTP/ingress-IP runtime when a public hostname or managed TLS is missing.
```

renders as:

```markdown
- **GCP portal runtime no longer derives its Django security posture from
  managed-TLS readiness, and now fails closed.** ... (#966)
```

## Build the changelog (release time)

```sh
uvx towncrier build --version <X.Y.Z> --date $(date -u +%F)
```

This collates `changelog.d/*.md` into a new release block at the top of
`CHANGELOG.md` (just under the `<!-- towncrier release notes start -->`
marker), deletes the consumed fragments, and stages the changes. Commit
the result.

## Preview without writing

```sh
uvx towncrier build --draft --version <X.Y.Z>
```

prints the rendered block to stdout without modifying any files.

## Check that a PR has a fragment

```sh
uvx towncrier check --compare-with origin/dev
```

returns non-zero if the PR has no fragment under `changelog.d/`. Useful
locally; can also be wired into CI as a soft check (some PRs — pure
refactors, CI-only changes — legitimately have nothing user-visible to
say, in which case mark the PR `[no changelog]` or land an empty
fragment with the rationale).
