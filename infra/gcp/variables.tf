variable "project_id" {
  description = "Existing GCP project dedicated to syshin0116.dev."
  type        = string
  default     = "festive-ally-503605-v7"

  validation {
    condition     = var.project_id == "festive-ally-503605-v7"
    error_message = "This state and backend are dedicated to festive-ally-503605-v7; use a separate root module for another project."
  }
}

variable "region" {
  description = "Cloud Run and Artifact Registry region."
  type        = string
  default     = "us-east4"

  validation {
    condition     = var.region == "us-east4"
    error_message = "This foundation is fixed to us-east4; review state, imports, and data residency before changing regions."
  }
}

variable "github_repository_id" {
  description = "Immutable numeric GitHub repository ID."
  type        = string
  default     = "1102380057"

  validation {
    condition     = var.github_repository_id == "1102380057"
    error_message = "This federation root is dedicated to syshin0116/syshin0116.dev repository ID 1102380057."
  }
}

variable "github_owner_id" {
  description = "Immutable numeric GitHub repository owner ID."
  type        = string
  default     = "99532836"

  validation {
    condition     = var.github_owner_id == "99532836"
    error_message = "This federation root is dedicated to GitHub owner ID 99532836."
  }
}

variable "github_preview_environment" {
  description = "Exact GitHub environment claim accepted only for the preview deployer role."
  type        = string
  default     = "Agent Preview"

  validation {
    condition     = var.github_preview_environment == "Agent Preview"
    error_message = "The preview deployer role must remain bound to the exact Agent Preview environment."
  }
}

variable "github_production_environment" {
  description = "Exact GitHub environment claim accepted only for the production deployer role."
  type        = string
  default     = "Agent Production"

  validation {
    condition     = var.github_production_environment == "Agent Production"
    error_message = "The production deployer role must remain bound to the exact Agent Production environment."
  }
}

variable "agent_delivery_stage" {
  description = "Explicit bootstrap stage: foundation creates prerequisites, jobs creates migration/probe jobs, and services creates the serving surface."
  type        = string
  default     = "foundation"

  validation {
    condition     = contains(["foundation", "jobs", "services"], var.agent_delivery_stage)
    error_message = "agent_delivery_stage must be exactly foundation, jobs, or services."
  }

  validation {
    condition = var.agent_delivery_stage == "foundation" ? (
      var.agent_bootstrap_image == null
      && var.agent_preview_bootstrap_image == null
      && var.agent_secret_versions == null
      ) : (
      var.agent_bootstrap_image != null
      && var.agent_preview_bootstrap_image != null
      && var.agent_secret_versions != null
    )
    error_message = "foundation requires null image/version inputs; jobs and services require immutable production/preview images plus the complete reviewed numeric version map."
  }
}

variable "agent_bootstrap_image" {
  description = "Reviewed immutable agent image for the jobs and services stages; null during foundation bootstrap, after which CD owns digest changes."
  type        = string
  default     = null

  validation {
    condition     = var.agent_bootstrap_image == null || can(regex("^us-east4-docker\\.pkg\\.dev/festive-ally-503605-v7/agent/agent@sha256:[0-9a-f]{64}$", var.agent_bootstrap_image))
    error_message = "When set, agent_bootstrap_image must be the exact regional agent repository path at a lowercase sha256 digest."
  }
}

variable "agent_preview_bootstrap_image" {
  description = "Reviewed immutable preview image in the isolated preview repository for the jobs and services stages; null during foundation bootstrap."
  type        = string
  default     = null

  validation {
    condition     = var.agent_preview_bootstrap_image == null || can(regex("^us-east4-docker\\.pkg\\.dev/festive-ally-503605-v7/agent-preview/agent@sha256:[0-9a-f]{64}$", var.agent_preview_bootstrap_image))
    error_message = "When set, agent_preview_bootstrap_image must be the exact preview repository path at a lowercase sha256 digest."
  }
}

variable "agent_secret_versions" {
  description = "Reviewed Secret Manager numeric versions keyed by all eleven managed secret IDs; null only during foundation bootstrap. Secret payloads never enter Terraform."
  type        = map(string)
  default     = null

  validation {
    condition = var.agent_secret_versions == null ? true : alltrue([
      for version in values(var.agent_secret_versions) :
      can(regex("^[1-9][0-9]*$", version))
    ])
    error_message = "Every agent_secret_versions value must be a positive numeric Secret Manager version; latest and aliases are forbidden."
  }

  validation {
    condition = var.agent_secret_versions == null ? true : toset(keys(var.agent_secret_versions)) == toset([
      "agent-auth-secret",
      "agent-database-url",
      "agent-migration-database-url",
      "agent-preview-anthropic-api-key",
      "agent-preview-auth-secret",
      "agent-preview-database-url",
      "agent-preview-langsmith-api-key",
      "agent-preview-migration-database-url",
      "anthropic-api-key",
      "langsmith-api-key",
      "openai-api-key",
    ])
    error_message = "agent_secret_versions must contain exactly the eleven managed secret IDs, with no missing or extra keys."
  }
}
