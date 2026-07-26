variable "project_id" {
  description = "Existing GCP project dedicated to syshin0116.dev."
  type        = string
  default     = "festive-ally-503605-v7"
}

variable "project_number" {
  description = "Numeric GCP project identifier used in principalSet members."
  type        = string
  default     = "72919926064"
}

variable "region" {
  description = "Cloud Run and Artifact Registry region."
  type        = string
  default     = "us-east4"
}

variable "github_repository_id" {
  description = "Immutable numeric GitHub repository ID."
  type        = string
  default     = "1102380057"
}

variable "github_owner_id" {
  description = "Immutable numeric GitHub repository owner ID."
  type        = string
  default     = "99532836"
}

variable "github_preview_environment" {
  description = "Exact GitHub environment claim accepted by the preview provider."
  type        = string
  default     = "Preview"
}

variable "github_production_environment" {
  description = "Exact GitHub environment claim accepted by the production provider."
  type        = string
  default     = "Production"
}
