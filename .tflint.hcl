config {
  call_module_type = "local"
  force            = false
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
