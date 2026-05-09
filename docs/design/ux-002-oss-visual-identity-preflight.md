# UX-002 OSS Visual Identity Preflight

This note sets architecture guardrails for the partial UX-002 debranding pass
tracked by issue #1101. It is intentionally not an implementation plan and does
not define the final Shifter visual identity.

## Boundary

The debranding pass must remove proprietary brand surface area from shipped UI
and static surfaces while preserving domain-accurate product references that
users need to operate ranges.

Remove branding contamination from:

- Django base templates, partials, login/logout pages, and app templates.
- Static CSS, JavaScript, images, favicons, social-card assets, and generated
  static output.
- In-app documentation pages that present Shifter itself.
- Decorative copy, titles, logo marks, color tokens, class names, filenames, and
  UI behavior names derived from proprietary product branding.

Keep legitimate product references in:

- Scenario templates, range configuration, provisioning code, packer scripts,
  Terraform/Kubernetes assets, MCP packages, and tests that describe or validate
  supported product integrations.
- User-facing instructional copy where the product name is required to complete
  a range task, configure an integration, upload an agent, or interpret exercise
  telemetry.
- Existing schema fields and persisted domain concepts such as agent type values
  when renaming would become a data migration or API compatibility problem.

When a string match is ambiguous, classify it by purpose. If the term identifies
Shifter's own look, navigation, marketing voice, or decorative chrome, remove it.
If it identifies an external product that a range deploys, configures, or teaches,
keep it.

## Existing Patterns To Reuse

- Base layouts already centralize most global styling and script imports in
  `shifter/shifter_platform/templates/mission_control/base.html`,
  `shifter/shifter_platform/templates/ctf/base.html`, and
  `shifter/shifter_platform/templates/documentation/base.html`. Replace shared
  theme entrypoints there rather than duplicating per-app CSS imports.
- Navigation chrome is centralized in
  `shifter/shifter_platform/templates/partials/icon_sidebar.html` and
  `shifter/shifter_platform/templates/partials/ctf_participant_sidebar.html`.
  Keep sidebar behavior in the existing sidebar/dropdown JavaScript modules
  instead of creating a second navigation system.
- Static JavaScript uses Jest with jsdom under
  `shifter/shifter_platform/static/js/*.test.js`. Reuse those tests for any
  behavior-preserving file renames or DOM contract changes.
- CSS quality tooling already exists through Stylelint in
  `shifter/shifter_platform/.stylelintrc.json`; JavaScript quality uses
  `eslint.config.js`.
- Template context shared across apps flows through existing Django context
  processors in `config/settings.py`. Do not introduce a new global branding
  context unless a real runtime setting is required.
- Cross-layer Python changes, if any become necessary, must follow existing app
  service boundaries and shared contracts under `shifter/shifter_platform/shared`.
  This debranding pass should normally stay in templates, static assets, tests,
  and documentation.

## Guardrails

- Use a neutral interim palette with WCAG AA contrast. Do not approximate,
  sample, recolor, or rename proprietary palette values.
- Rename brand-derived CSS classes, custom properties, filenames, and JS module
  names only where the rename removes Shifter-owned UI contamination. Do not
  rename persisted product fields or scenario schema keys as part of this pass.
- Avoid introducing a design system, token package, theme engine, logo system, or
  runtime tenant branding abstraction. UX-002's final identity and follow-up
  design-system work are separate.
- Keep visual assets original or plain placeholders. Do not trace, simplify,
  recolor, or otherwise derive replacement logos from proprietary marks.
- Scrub source references and generated/static references together. A template
  that no longer imports an asset is not enough if the branded file still ships.
- Review grep hits manually by boundary, not by blanket deletion. Product names
  in provisioning, scenarios, tests, and product setup docs can be correct.
- Preserve authentication, authorization, logging, upload validation, scenario
  validation, and provisioning behavior. This pass is a presentation and shipped
  artifact cleanup, not a domain model change.

## Verification Expectations

Before completion, the implementation should run the repo architecture gate:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

For frontend/static edits under `shifter/shifter_platform`, also run the relevant
stack-native checks from that directory:

```bash
uv run ruff check .
uv run ruff format --check .
npm test -- --runInBand
npx eslint static/js
npx stylelint "static/css/**/*.css"
```

Use a scoped case-insensitive search over templates, static assets, JavaScript,
and in-app documentation to produce a reviewer-readable list of remaining hits.
Each remaining hit should be justifiable as a product reference, not Shifter
branding.
