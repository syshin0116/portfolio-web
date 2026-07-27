locals {
  preview_wif_attribute_condition    = "assertion.repository_id == '${var.github_repository_id}' && assertion.repository_owner_id == '${var.github_owner_id}' && assertion.event_name == 'pull_request' && assertion.environment == '${var.github_preview_environment}'"
  production_wif_attribute_condition = "assertion.repository_id == '${var.github_repository_id}' && assertion.repository_owner_id == '${var.github_owner_id}' && assertion.event_name == 'push' && assertion.ref == 'refs/heads/main' && assertion.environment == '${var.github_production_environment}'"

  required_services = toset([
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "sts.googleapis.com",
  ])

  production_secret_names = toset([
    "agent-auth-secret",
    "agent-database-url",
    "anthropic-api-key",
    "langsmith-api-key",
    "openai-api-key",
  ])

  preview_secret_names = toset([
    "agent-preview-anthropic-api-key",
    "agent-preview-auth-secret",
    "agent-preview-database-url",
    "agent-preview-langsmith-api-key",
    "agent-preview-openai-api-key",
  ])

  deployers = {
    preview = {
      account_id   = "agent-preview-deployer"
      display_name = "GitHub preview deployer"
    }
    production = {
      account_id   = "agent-prod-deployer"
      display_name = "GitHub production deployer"
    }
  }
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "agent" {
  project       = var.project_id
  location      = var.region
  repository_id = "agent"
  description   = "Immutable agent images"
  format        = "DOCKER"

  docker_config {
    immutable_tags = true
  }

  depends_on = [google_project_service.required]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "agent-runtime"
  display_name = "Cloud Run production agent runtime"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "preview_runtime" {
  project      = var.project_id
  account_id   = "agent-preview-runtime"
  display_name = "Cloud Run preview agent runtime"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "deployer" {
  for_each = local.deployers

  project      = var.project_id
  account_id   = each.value.account_id
  display_name = each.value.display_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_secret_manager_secret" "runtime" {
  for_each = local.production_secret_names

  project   = var.project_id
  secret_id = each.value

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_secret_manager_secret" "preview_runtime" {
  for_each = local.preview_secret_names

  project   = var.project_id
  secret_id = each.value

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  description               = "GitHub Actions federation; no service-account keys."

  depends_on = [google_project_service.required]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_iam_workload_identity_pool_provider" "preview" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-preview"
  display_name                       = "GitHub Preview"

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.environment"         = "assertion.environment"
    "attribute.event_name"          = "assertion.event_name"
    "attribute.ref"                 = "assertion.ref"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
  }

  attribute_condition = local.preview_wif_attribute_condition

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  lifecycle {
    prevent_destroy = true
  }
}

check "runtime_environments_are_disjoint" {
  assert {
    condition     = length(setintersection(local.production_secret_names, local.preview_secret_names)) == 0
    error_message = "Preview and production Secret Manager resource names must be disjoint."
  }
}

resource "google_iam_workload_identity_pool_provider" "production" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-production"
  display_name                       = "GitHub Production"

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.environment"         = "assertion.environment"
    "attribute.event_name"          = "assertion.event_name"
    "attribute.ref"                 = "assertion.ref"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
  }

  attribute_condition = local.production_wif_attribute_condition

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  lifecycle {
    prevent_destroy = true
  }
}
