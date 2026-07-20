config {
  call_module_type = "local"
  force            = false
}

plugin "google" {
  enabled = true
  version = "0.31.0"
  source  = "github.com/terraform-linters/tflint-ruleset-google"

  # Verify the plugin via its PGP signature instead of GitHub artifact
  # attestations. A GitHub-side change to attestation bundles makes tflint's
  # attestation verifier nil-panic during `tflint --init` (sigstore-go
  # bundle.TlogEntries), which reddens terraform-lint repo-wide. This is the
  # maintainer-recommended interim workaround; remove once tflint ships the
  # fix. Upstream: terraform-linters/tflint#2591 (fix PR #2593). Issue #1691.
  signature = "pgp"
}

# Start with rules that are actionable in the current tree. The repo has
# substantial legacy debt around version/provider declarations and unused
# declarations; turning those on immediately would make the new gate noisy and
# unmergeable without improving ADR conformance.
rule "terraform_required_version" {
  enabled = false
}

rule "terraform_required_providers" {
  enabled = false
}

rule "terraform_unused_declarations" {
  enabled = false
}
