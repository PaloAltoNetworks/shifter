# ACES Parity Inventory Path Integrity Preflight

Issue: GitHub #1313, "ACES guardrails: add parity-inventory path-integrity
check to adr_guard."

Status: accepted design guidance for the #1313 implementation. The GitHub
issue remains the authoritative delivery contract. This note fixes the
classification, security, routing, and error-handling boundaries that must not
be rediscovered file-locally. It does not implement the checker or alter CI.

## Decision

Extend `scripts/adr_guard/adr_guard.py` with the
`aces-parity-inventory-path-integrity` check; do not add a second inventory
parser, standalone validator, workflow script, or runtime model. The check is
a global repository invariant over
`docs/architecture/aces-migration-parity-inventory.yaml` and is governed by a
new, narrowly stated ADR-024 rule. It must use the existing `Violation` result,
ADR exception filtering, CLI rendering, `CHECKS`, and `CHECK_LEVELS` surfaces.

The inventory remains an ADR-024 audit ledger. It is not a runtime schema,
command manifest, test runner, launchability model, or ACES contract. The
checker validates only whether repo-path evidence still resolves; it must not
execute evidence, infer migration readiness, or validate the business meaning
of a row.

## Classification Contract

Only `legacy_source` and `validation_evidence` are path-bearing fields for this
issue. Keep that field set in one named constant so a later evidence field can
join the same checker without duplicating its traversal or classification
logic.

Each field is a YAML string whose semicolon-separated clauses are classified
independently after trimming. A semicolon is therefore a clause delimiter in
these two fields, not shell syntax.

| Kind | Deterministic shape | Validation |
| --- | --- | --- |
| repo path | One POSIX, repo-relative token containing `/` or beginning with `.`, with no shell operators or whitespace. Spell a root-level name as `./name`. | The path exists under the repository root. Files and directories are both valid. |
| repo glob | A repo-path token containing supported glob metacharacters | At least one path under the repository root matches. |
| shell command | A lexically command-shaped clause, including the existing `python3 ...`, `cd ... && ...`, and `aces conformance ... --profile ...` forms | Classify only. Never execute, expand, or resolve command arguments as evidence paths. |
| explicit prose | A sentence, annotation, dotted model/member reference, removal statement, external-source description, or other clause that is not a repo path/glob/command | Classify only. Do not extract path-looking substrings from prose. |

Path and glob classification must be syntax-led, not existence-led; otherwise a
deleted path would be reclassified as prose and evade the check. Conversely,
do not scan arbitrary words inside prose for slashes. Entries such as shipped
summaries, `engine.Range.provisioned_instances`, and annotations such as
`tests/example.py (#1234)` are prose unless the checkable path is placed in its
own clause.

The implementation must make ambiguous current inventory values explicit in
the same change:

- quote or use block scalars for values where `#` is content. In plain YAML a
  whitespace-prefixed `#` starts a comment; current values such as the removed
  experiments descriptions and `future #1290 ...` do not parse as they read;
- describe the upstream `aces-sdl/contracts/profiles/backend/` reference as
  external prose rather than allowing it to look like a missing repo path;
- put every repo path intended to be checked in its own semicolon-delimited
  clause. Mixed prose such as `path plus future tests` is deliberately prose,
  not a partially checked path.

Do not introduce per-row type tags, a second `row_schema`, a command allowlist
stored in YAML, or path exemptions embedded in the inventory. A genuine waiver
uses the existing dated `docs/adr/exceptions.yaml` mechanism.

## Security And Host-Filesystem Boundary

Treat the checked YAML as untrusted static repository input even though it is
reviewed source:

- parse with `yaml.safe_load`; never use unsafe constructors;
- never pass inventory text to `subprocess`, `shell=True`, `eval`, `exec`, a
  shell, or a command-line argument;
- never expand `~`, environment variables, command substitutions, or brace
  expressions;
- reject absolute paths, `..` traversal, and path/glob candidates that escape
  the repository root;
- do not follow symlinked components outside the repository. Reject such
  evidence fail-closed without reading the target or its contents;
- check metadata/existence only. Do not open referenced evidence files, print
  matching file contents, enumerate glob matches in diagnostics, or inspect
  credentials and environment bindings.

Violations must identify the inventory path, row id, field, and offending
repo-relative clause. They must not contain the absolute checkout path, a stack
trace, environment values, file contents, or expanded command text. Missing
PyYAML, a missing/unreadable inventory, malformed YAML, a non-mapping root, a
non-list `rows` value, a non-mapping row, a missing/non-string row id, or a
missing/non-string inspected field is a bounded violation, not a crash or
silent skip. This is shape validation needed to make the path check fail
closed; it must not grow into duplicate validation of the inventory's full
domain schema.

No authentication, API error envelope, database, cache, or runtime logging
surface is involved. The applicable error envelope is the existing ADR guard
`Violation`/text-or-JSON CLI output. The applicable observability signal is the
CI/pre-commit failure itself; adding a logger, audit row, metric, or event for a
static repository check would create a second concern.

## Local And CI Enforcement Boundary

The check is global: `--all` and `--files`/`--changed` must validate the whole
inventory because a referenced path can disappear without the inventory being
in the changed-file set. It belongs in `CHECKS` and the `ci` level so the issue's
required `adr_guard --all --level ci` invocation is authoritative.

Local enforcement must reuse pre-commit. A focused hook may invoke only this
check with PyYAML supplied by the hook environment, following the existing
dependency-bearing ADR guard hook pattern. It must run for every commit rather
than only inventory edits; path deletion is the regression being guarded.
Register that same hook in the always-present CI pre-commit job so docs-only or
Markdown evidence deletion cannot evade the check when the broader Quality
workflow is legitimately skipped.

The parity inventory itself is a guardrail document. Route its edits through
the existing Quality/ADR-conformance classifiers as well; do not create a
parallel workflow or duplicate the inventory's referenced paths in workflow
filters. Changes to workflow or pre-commit routing remain subject to ADR-003,
ADR-002, `actionlint`, the workflow-model tests, and the mandatory changelog
fragment for CI/local pipeline behavior.

The guardrail change must update the ADR-024 registry entry with a dedicated
rule/check mapping and update
`docs/technical/dev/adr-enforcement.md`. No exception is expected for the
current inventory; all checkable paths and globs must resolve when the rule
lands.

## Canonical Incumbents To Reuse

- `scripts/adr_guard/adr_guard.py`: `Violation`, check registration, levels,
  argument scoping, exception filtering, and text/JSON output.
- `scripts/adr_guard/tests/`: temporary-repository fixtures and registration,
  targeted-mode, malformed-input, and real-repository conformance patterns.
- `docs/architecture/aces-migration-parity-inventory.yaml`: the sole parity
  ledger and row ids used in diagnostics.
- `docs/adr/index.yaml` ADR-024: the policy owner; path integrity is a distinct
  rule rather than an overload of an unrelated ADR or `ADR-REGISTRY`.
- `docs/adr/exceptions.yaml`: the only waiver mechanism, with owner and expiry.
- `.pre-commit-config.yaml`, `.github/workflows/deploy.yml`,
  `.github/quality-path-filters.yaml`, and `.github/workflows/_quality.yml`: the
  existing local, always-present, routing, and full ADR-conformance surfaces.
- `docs/technical/dev/adr-enforcement.md`: the canonical operator/developer
  description of ADR guard behavior.

The extensibility seam is the inspected-field constant plus one pure clause
classifier returning the closed kinds `path`, `glob`, `command`, and `prose`.
A future inventory evidence field should extend the field constant; a future
supported glob form should extend the classifier tests. Neither requires a new
checker, workflow, YAML schema, or exception hierarchy.

## Acceptance Guardrails

Coverage must prove the current inventory passes and that the check is present
in the CI level. Isolated fixtures must cover missing files, directories,
one-match and zero-match globs, semicolon-separated paths, the three command
forms named by #1313, removed-legacy prose, dotted model references, quoted
issue-number prose, malformed/incorrect YAML shapes, absolute/traversal paths,
and symlink escape attempts. A command-shaped fixture should also prove no
sentinel side effect occurs, providing behavioral evidence that classification
never executes evidence.

Diagnostics should be deterministic and one violation should represent one
bad clause. Do not collapse multiple missing rows into an unstructured parser
exception, and do not emit a violation for every unmatched expansion of one
glob.

## Gotchas And Anti-Patterns

- Do not decide "path" by calling `exists()` first; that makes missing paths
  self-exempting.
- Do not treat every slash in a sentence as a path or extract path prefixes
  from annotated prose; current shipped summaries intentionally contain such
  text.
- Do not use `shlex` as an executor. Lexical parsing, if used, does not grant
  permission to run a command.
- Do not use shell glob expansion, recursive repository crawls, network access,
  package lookup, or ACES CLI availability as the existence oracle.
- Do not validate only inventory edits. Moves/deletions elsewhere are the main
  failure mode.
- Do not duplicate the referenced-path list in CI filters, pre-commit regexes,
  tests, or another manifest.
- Do not add an ACES-specific exception class, logger, DTO, service,
  repository, model, migration, or runtime configuration flag.
- Do not weaken docs-only Quality routing globally merely to run this cheap
  invariant; use the existing always-present pre-commit surface and exact
  guardrail-document routing.

## Non-Goals

- No issue implementation, checker code, test code, hook, workflow, changelog,
  or runtime behavior in this preflight.
- No validation of ACES conformance, cutover readiness, evidence quality,
  owner/category correctness, or whether a cited test actually exercises a
  row.
- No execution of commands or tests named by `validation_evidence`.
- No requirement that evidence paths be files rather than directories, or be
  executable, importable, or semantically valid.
- No rewrite of the parity inventory into a typed runtime contract.
- No new Ground Control requirement for this requirement-free issue.
