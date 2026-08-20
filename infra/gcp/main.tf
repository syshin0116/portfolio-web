locals {
  legacy_artifact_registry_region          = "us-east4"
  disabled_preview_wif_attribute_condition = "attribute.repository_id == '__legacy_provider_disabled__'"
  delivery_role_mapping                    = "assertion.event_name == 'pull_request' && assertion.workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/preview-agent.yml@' + assertion.ref ? (assertion.job_workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/agent-image-build.yml@' + assertion.ref ? 'preview-builder' : assertion.environment == '${var.github_preview_environment}' && assertion.job_workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/agent-release.yml@' + assertion.ref ? 'preview-deployer' : 'invalid') : assertion.event_name in ['push', 'workflow_dispatch'] && assertion.ref == 'refs/heads/main' && assertion.workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/deploy-agent.yml@refs/heads/main' ? (assertion.job_workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/agent-image-build.yml@refs/heads/main' ? 'production-builder' : assertion.environment == '${var.github_production_environment}' && assertion.job_workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/agent-release.yml@refs/heads/main' ? 'production-deployer' : 'invalid') : 'invalid'"
  delivery_wif_attribute_condition         = "attribute.repository_id == '${var.github_repository_id}' && attribute.repository_owner_id == '${var.github_owner_id}' && attribute.delivery_role in ['preview-builder', 'preview-deployer', 'production-builder', 'production-deployer']"

  required_services = toset([
    "artifactregistry.googleapis.com",
    "cloudscheduler.googleapis.com",
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

  production_runtime_secret_names = toset([
    "agent-auth-secret",
    "agent-database-url",
    "langsmith-api-key",
    "openai-api-key",
  ])

  preview_secret_names = toset([
    "agent-preview-anthropic-api-key",
    "agent-preview-auth-secret",
    "agent-preview-database-url",
    "agent-preview-langsmith-api-key",
  ])

  migration_secret_names = {
    preview    = "agent-preview-migration-database-url"
    production = "agent-migration-database-url"
  }

  required_agent_secret_names = setunion(
    local.production_secret_names,
    local.preview_secret_names,
    toset(values(local.migration_secret_names)),
  )

  required_production_delivery_secret_names = toset([
    "agent-auth-secret",
    "agent-database-url",
    "agent-migration-database-url",
    "langsmith-api-key",
    "openai-api-key",
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

  migrators = {
    preview = {
      account_id   = "agent-preview-migrator"
      display_name = "Cloud Run preview migration identity"
    }
    production = {
      account_id   = "agent-prod-migrator"
      display_name = "Cloud Run production migration identity"
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
  location      = local.legacy_artifact_registry_region
  repository_id = "agent"
  description   = "Production agent images with bounded rollback retention"
  format        = "DOCKER"

  docker_config {
    # Each delivery writes a never-reused run/attempt tag and deploys the
    # resolved digest. Tags must remain mutable so cleanup policies can remove
    # expired tagged versions.
    immutable_tags = false
  }

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "delete-after-90-days"
    action = "DELETE"

    condition {
      tag_state  = "ANY"
      older_than = "7776000s"
    }
  }

  cleanup_policies {
    id     = "keep-last-30"
    action = "KEEP"

    most_recent_versions {
      keep_count = 30
    }
  }

  depends_on = [google_project_service.required]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_artifact_registry_repository" "preview_agent" {
  project       = var.project_id
  location      = local.legacy_artifact_registry_region
  repository_id = "agent-preview"
  description   = "Preview agent images with short-lived retention"
  format        = "DOCKER"

  docker_config {
    immutable_tags = false
  }

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "delete-after-14-days"
    action = "DELETE"

    condition {
      tag_state  = "ANY"
      older_than = "1209600s"
    }
  }

  cleanup_policies {
    id     = "keep-last-20"
    action = "KEEP"

    most_recent_versions {
      keep_count = 20
    }
  }

  depends_on = [google_project_service.required]

  lifecycle {
    # The imported legacy preview repository records the provider-default false
    # as an omitted dockerConfig block. Keep Terraform read-only for that legacy
    # surface; the live readiness verifier still rejects immutableTags=true.
    ignore_changes  = [docker_config]
    prevent_destroy = true
  }
}

resource "google_artifact_registry_repository" "active_agent" {
  project       = var.project_id
  location      = var.region
  repository_id = "agent"
  description   = "Singapore production agent images with bounded rollback retention"
  format        = "DOCKER"

  docker_config {
    immutable_tags = false
  }

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "delete-after-90-days"
    action = "DELETE"

    condition {
      tag_state  = "ANY"
      older_than = "7776000s"
    }
  }

  cleanup_policies {
    id     = "keep-last-30"
    action = "KEEP"

    most_recent_versions {
      keep_count = 30
    }
  }

  depends_on = [google_project_service.required]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_artifact_registry_repository" "active_preview_agent" {
  project       = var.project_id
  location      = var.region
  repository_id = "agent-preview"
  description   = "Singapore preview image foundation retained dormant by delivery gates"
  format        = "DOCKER"

  docker_config {
    immutable_tags = false
  }

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "delete-after-14-days"
    action = "DELETE"

    condition {
      tag_state  = "ANY"
      older_than = "1209600s"
    }
  }

  cleanup_policies {
    id     = "keep-last-20"
    action = "KEEP"

    most_recent_versions {
      keep_count = 20
    }
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

resource "google_service_account" "maintenance_scheduler" {
  project      = var.project_id
  account_id   = "agent-maintenance-scheduler"
  display_name = "Cloud Scheduler production maintenance invoker"

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

resource "google_service_account" "builder" {
  project      = var.project_id
  account_id   = "agent-image-builder"
  display_name = "GitHub production agent image builder"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "preview_builder" {
  project      = var.project_id
  account_id   = "agent-preview-image-builder"
  display_name = "GitHub preview agent image builder"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "migrator" {
  for_each = local.migrators

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

resource "google_secret_manager_secret" "migration" {
  for_each = local.migration_secret_names

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
  disabled                  = false

  depends_on = [google_project_service.required]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_iam_workload_identity_pool_provider" "preview" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-preview"
  display_name                       = "Legacy GitHub Preview (disabled)"
  disabled                           = true

  attribute_mapping = {
    "google.subject"          = "assertion.sub"
    "attribute.repository_id" = "assertion.repository_id"
  }

  attribute_condition = local.disabled_preview_wif_attribute_condition

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

check "agent_delivery_stage_inputs" {
  assert {
    condition = var.agent_delivery_stage == "foundation" ? (
      var.agent_bootstrap_image == null
      && var.agent_preview_bootstrap_image == null
      && var.agent_secret_versions == null
      ) : (
      var.agent_bootstrap_image != null
      && var.agent_preview_bootstrap_image == null
      && var.agent_secret_versions != null
    )
    error_message = "foundation requires null image/version inputs; every later stage requires one immutable production image, no preview image, and the complete reviewed production numeric version map."
  }
}

check "agent_secret_version_inventory" {
  assert {
    condition = var.agent_delivery_stage == "foundation" ? true : (
      var.agent_secret_versions != null
      && toset(keys(var.agent_secret_versions)) == local.required_production_delivery_secret_names
    )
    error_message = "every non-foundation stage requires exactly the five production delivery secret IDs, with no missing or extra version keys."
  }
}

resource "google_iam_workload_identity_pool_provider" "production" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-production"
  display_name                       = "GitHub Agent Delivery"
  disabled                           = false

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.delivery_role"       = local.delivery_role_mapping
  }

  attribute_condition = local.delivery_wif_attribute_condition

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  lifecycle {
    prevent_destroy = true
  }
}
