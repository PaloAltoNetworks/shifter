# OSS Release Hygiene Preflight (#1196)

Status: pre-implementation guidance

Date: 2026-05-12

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1196>

## Scope Boundary

This workstream is repository hygiene, not a new runtime feature. It may add
community-profile files, GitHub automation, CI hardening, and identifier
cleanup, but it must not create a second deployment configuration model or
relax existing architecture enforcement.

The issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract.

## Architecture Decisions

- Community files are policy text, not application behavior. `SECURITY.md` and
  `SUPPORT.md` should come from the PANW organization sources named in the
  issue. Project-specific contribution guidance belongs in `CONTRIBUTING.md`
  and should point to existing repo commands and docs rather than duplicating
  every detail.
- GitHub automation changes are guardrail changes when they touch workflows or
  repo security posture. They must preserve ADR-002/ADR-003: document the new
  enforcement surface and keep `adr_guard` as the hard architecture gate.
- Identifier cleanup must move deployment-specific values to existing
  configuration seams. Do not replace the legacy operator domain or a personal
  email with a new hardcoded production identity when the value is
  environment-owned.
- Domain names and notification email addresses in committed tfvars are config,
  not secrets, but they are still OSS identifiers. Secrets and secret values
  remain out of tfvars, generated env files, workflow logs, argv, and docs.
- SonarCloud badges should use the public badge endpoint without the committed
  token. After the token is removed, do not leave broad scanner allowlists that
  would hide a future committed badge token.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1196 |
| --- | --- | --- |
| Architecture enforcement | `.ground-control.yaml`, `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py`, `docs/adr/index.yaml`, `docs/adr/README.md` | Run `adr_guard` and update enforcement docs for workflow or guardrail changes. |
| Workflow validation | `.github/workflows/_quality.yml`, `.github/workflows/deploy.yml`, `actionlint`, `.github/pull_request_template.md` | New workflows/jobs should follow existing permissions, self-hosted runner, pinned-action, and least-privilege patterns. |
| Secret scanning | `.gitleaks.toml`, `.pre-commit-config.yaml`, `_quality.yml` gitleaks job | Remove the Sonar token and tighten any obsolete allowlist; do not compensate with broader exceptions. |
| Dependency automation | Existing package roots with `pyproject.toml`/`uv.lock`, `package-lock.json`, and workflow action pins | Dependabot config should enumerate the repo's actual package roots instead of assuming one root package. |
| Runtime env binding | `shifter/shifter_platform/config/settings.py`, `scripts/gcp/render_runtime_env.py`, Helm/K8s runtime env files | Keep public hostnames and email senders environment-bound. Generated env files should be regenerated from canonical inputs, not hand-edited as a parallel source. |
| Root deployment config | `shifter/installation/schema.py`, `contract.py`, `registry.py`, `docs/architecture/root-configured-backend-bundles.md` | New OSS-facing deployment defaults should flow through the backend bundle/root config model when that is the owning seam. |
| Terraform validation | `platform/terraform/**`, `.tflint.hcl`, ADR-004 secret-in-tfvars checks | Tfvars may hold non-secret config, but alarm emails and domains should be variables/examples, not personal or legacy org identifiers. |
| Kubernetes validation | `platform/k8s/gcp/**`, `.kube-linter.yaml`, `kubeconform`, ADR-006/ADR-008 | Treat generated `platform-runtime.generated.env` as derived output; regenerate from Terraform/bootstrap inputs where possible. |
| Changelog and PR convention | `changelog.d/README.md`, `.github/pull_request_template.md` | PR title lint should align with existing towncrier/release conventions without inventing a new release taxonomy. |

## Security Layers

- Auth surface: community files and issue templates must route security reports
  to PSIRT and must not create an issue-template path that asks users to paste
  vulnerability details into public issues. Runtime auth behavior remains owned
  by ADR-009 and the existing Django/provider seams.
- Secret-handling surface: badge tokens, personal emails, secret references,
  GitHub tokens, and provider credentials must not be committed, logged, or
  passed through process argv. Root config and backend bundles accept
  references, not secret values.
- Env-binding shape: domain/email defaults must satisfy `settings.py`,
  Terraform variables, GCP renderers, Helm/K8s runtime env, and test fixtures
  consistently. Prefer one canonical config input plus generated outputs over
  per-file string replacement.
- Config validators: changes must pass ADR guard, actionlint for workflows,
  TFLint for Terraform, kube-linter/kubeconform for K8s, package-native lint for
  Python/JS where touched, and explicit `git grep` verification for forbidden
  identifiers.
- OS/process exposure: any helper script added for scanning or replacement must
  use structured argv subprocess calls and avoid echoing token-like strings in
  command logs. MCP code remains constrained by ADR-010.
- Error/log surface: validation or lint failures should name the file/key and
  remediation. Do not echo secret values, badge tokens, or full environment
  payloads in diagnostics.

## Extensibility Seams

- Public DNS and email identities should be parameterized at the deployment
  config layer (`deployment.domain`, Terraform variables, backend renderer
  inputs, or documented examples). The next OSS user should not need to edit
  source code to replace PANW/example domains.
- Dependabot should be structured so adding another package root is another
  `updates` entry, not a new convention. As of current GitHub docs, `uv`,
  `npm`, and `github-actions` are supported package ecosystems; use the package
  ecosystem that matches each root's lockfile.
- CodeQL should be its own workflow or clearly documented quality job with
  least privileges (`contents: read`, `security-events: write`) and the
  requested `security-extended` suite. It should not become a replacement for
  Bandit, Checkov, gitleaks, ADR guard, or actionlint.
- PR title lint should validate the title shape only. It should not redefine
  changelog fragment types, release-drafter labels, branch routing, or merge
  policy.

## Gotchas And Anti-Patterns

- Do not make public `security_report.md` encourage disclosure in GitHub Issues.
  It should redirect to PSIRT/private reporting and the local `SECURITY.md`.
- Do not hand-edit generated runtime files as the source of truth. If a generated
  file remains committed, identify the generator input and regenerate it.
- Do not swap the legacy operator domain to a PANW domain inside tests where
  `example.com` is a safer non-operational placeholder.
- Do not collapse deployment domain, CTFd URL, SES sender domain, Django
  allowed hosts, CSRF origins, and alarm notification email into one concept.
  They are related but not the same contract.
- Do not add broad gitleaks allowlists for README badges, examples, or fixtures.
  If a fixture must contain token-shaped text, keep the allowlist path-scoped and
  documented.
- Do not use `pull_request_target` for PR title lint or CodeQL unless there is a
  specific reviewed security reason. Public-fork inputs should run with
  read-only checkout behavior.
- Do not weaken existing workflow path filters, skip logic, or architecture
  gates to keep the hygiene PR small.

## Non-Goals

- No LICENSE work, AWS account-ID externalization, default-password cleanup, or
  git-history rewrite.
- No backend-bundle migration, root config redesign, Terraform state migration,
  or deploy branch routing change.
- No new schema, exception hierarchy, logging framework, security scanner
  framework, or release taxonomy.
- No local override of `CODE_OF_CONDUCT.md` unless the implementation
  intentionally differs from the inherited PANW organization default.
