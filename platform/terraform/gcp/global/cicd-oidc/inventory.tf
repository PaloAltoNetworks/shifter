variable "github_repository_id" {
  description = "Immutable GitHub execution repository ID, verified during bootstrap."
  type        = string
  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.github_repository_id))
    error_message = "github_repository_id must be a numeric repository ID."
  }
}

variable "github_owner_id" {
  description = "Immutable GitHub owner ID, verified during bootstrap."
  type        = string
  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.github_owner_id))
    error_message = "github_owner_id must be a numeric owner ID."
  }
}

variable "release_evidence_bucket_name" {
  description = "Explicit deployment-owned retained evidence bucket; preserve its name during migration."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.release_evidence_bucket_name))
    error_message = "release_evidence_bucket_name must be a valid bucket name."
  }
}

variable "purpose_contexts" {
  description = "Validated exact execution tuples. Disabled purposes are absent; capabilities are product policy."
  type = map(list(object({
    environment           = string
    ref                   = string
    workflow_ref          = string
    reusable_workflow_ref = string
  })))
  validation {
    condition = length(var.purpose_contexts) > 0 && alltrue([
      for purpose, contexts in var.purpose_contexts :
      contains(["build", "validate", "promote", "release_scan", "deploy", "destroy"], purpose) && length(contexts) > 0
    ])
    error_message = "purpose_contexts must enable only supported purposes with non-empty contexts."
  }
  validation {
    condition = length(flatten([
      for purpose, contexts in var.purpose_contexts : distinct([for context in contexts : lower("repo:${var.github_org}/${var.github_repo}:environment:${context.environment}")])
      ])) == length(distinct(flatten([
        for purpose, contexts in var.purpose_contexts : [for context in contexts : lower("repo:${var.github_org}/${var.github_repo}:environment:${context.environment}")]
    ])))
    error_message = "Purpose subject sets must be pairwise disjoint."
  }
  validation {
    condition = alltrue(flatten([
      for purpose, contexts in var.purpose_contexts : [for context in contexts :
        can(regex("^refs/heads/[A-Za-z0-9][A-Za-z0-9_/-]*$", context.ref)) &&
        can(regex("^[A-Za-z0-9][A-Za-z0-9_-]*$", context.environment)) &&
        startswith(context.workflow_ref, "${var.github_org}/${var.github_repo}/.github/workflows/") &&
        endswith(context.workflow_ref, "@${context.ref}") &&
        can(regex("^[A-Za-z0-9_./@-]+$", context.workflow_ref)) &&
        (context.reusable_workflow_ref == "" || can(regex("^Brad-Edwards/shifter/\\.github/workflows/_[a-z0-9_-]+\\.yml@[a-f0-9]{40}$", context.reusable_workflow_ref)))
      ]
    ]))
    error_message = "Trust tuples require exact repository, Environment, branch and workflow contexts."
  }
}

variable "name_prefix" {
  description = "Explicit stable resource prefix from the validated deployment inventory."
  type        = string
}

variable "project_number" {
  description = "Verified foundation project number used for inspectable exact principals in first-run plans."
  type        = string
  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.project_number))
    error_message = "project_number must be a verified numeric project number."
  }
}
