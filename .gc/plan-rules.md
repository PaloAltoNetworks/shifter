# shifter plan rules

Mandatory constraints the `/implement` skill applies during plan phase.
These encode the ADR-guard checks, guardrail-file discipline,
architectural defaults, and Kubernetes-specific validators previously in
`AGENTS.md` prose.

- Plans MUST pass `python3 scripts/adr_guard/adr_guard.py --all --level ci`
  before declaring completion.
- Plans MUST respect the ADR index at `docs/adr/index.yaml` and
  exceptions at `docs/adr/exceptions.yaml`. New or changed guardrails
  require matching ADR/registry updates in the same change.
- Plans that touch `.github/workflows/**` MUST pass `actionlint`.
- Plans that touch Terraform under `platform/terraform/` MUST pass
  `cd platform/terraform && tflint --recursive --config ../../.tflint.hcl`.
- Plans that touch Python in `shifter/shifter_platform/` MUST pass
  `uv run ruff check .` and `uv run ruff format --check .` from that
  directory.
- Plans that touch Python imports MUST pass
  `cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter`.
- Plans that touch `platform/k8s/**` MUST pass
  `kube-linter lint --config .kube-linter.yaml platform/k8s/`.
- Plans that touch `platform/k8s/gcp/base/*.yaml` MUST pass
  `kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml`.
- Plans MUST NOT weaken CI or local enforcement silently. Rule
  exceptions require an entry in `docs/adr/exceptions.yaml` with an
  owner and expiry.
- Plans MUST keep cross-layer access going through service boundaries;
  shared contracts live under `shared/`.
- Changes to guardrail files (`.github/workflows/**`, `.github/CODEOWNERS`,
  `.github/pull_request_template.md`, `.github/copilot-instructions.md`,
  `.pre-commit-config.yaml`, `.importlinter`, `.tflint.hcl`,
  `.gitleaks.toml`, `.kube-linter.yaml`, `.claude/settings.json`,
  `.claude/hooks/**`, `scripts/adr_guard/**`, `docs/adr/**`) MUST stay
  documented in the ADR enforcement docs or registry.
