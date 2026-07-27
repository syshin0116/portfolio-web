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
  description = "Exact GitHub environment claim accepted by the preview provider."
  type        = string
  default     = "Preview"

  validation {
    condition     = var.github_preview_environment == "Preview"
    error_message = "The preview provider must remain bound to the exact Preview environment."
  }
}

variable "github_production_environment" {
  description = "Exact GitHub environment claim accepted by the production provider."
  type        = string
  default     = "Production"

  validation {
    condition     = var.github_production_environment == "Production"
    error_message = "The production provider must remain bound to the exact Production environment."
  }
}
