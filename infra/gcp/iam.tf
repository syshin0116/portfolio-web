locals {
  runtime_service_account_ids = {
    preview    = google_service_account.preview_runtime.name
    production = google_service_account.runtime.name
  }
  runtime_service_accounts = {
    preview    = google_service_account.preview_runtime.email
    production = google_service_account.runtime.email
  }
  deployer_service_accounts = {
    for name, account in google_service_account.deployer : name => account.email
  }
  migrator_service_account_ids = {
    for name, account in google_service_account.migrator : name => account.name
  }
  migrator_service_accounts = {
    for name, account in google_service_account.migrator : name => account.email
  }
  github_delivery_role_principals = {
    preview_builder     = "principalSet://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/attribute.delivery_role/preview-builder"
    preview_deployer    = "principalSet://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/attribute.delivery_role/preview-deployer"
    production_builder  = "principalSet://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/attribute.delivery_role/production-builder"
    production_deployer = "principalSet://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/attribute.delivery_role/production-deployer"
  }
  cloud_run_image_pull_principal = "serviceAccount:service-${data.google_project.current.number}@serverless-robot-prod.iam.gserviceaccount.com"
}

resource "google_project_iam_custom_role" "cloud_run_delivery" {
  project     = var.project_id
  role_id     = "cloudRunAgentDelivery"
  title       = "Cloud Run agent delivery"
  description = "Update and verify only existing agent services and jobs, then run jobs without overrides."
  stage       = "GA"
  permissions = [
    "run.jobs.get",
    "run.jobs.run",
    "run.jobs.update",
    "run.operations.get",
    "run.revisions.get",
    "run.services.get",
    "run.services.update",
  ]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account_iam_member" "deployer_uses_runtime" {
  for_each = local.deployer_service_accounts

  service_account_id = local.runtime_service_account_ids[each.key]
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${each.value}"
}

resource "google_service_account_iam_member" "deployer_uses_migrator" {
  for_each = local.deployer_service_accounts

  service_account_id = local.migrator_service_account_ids[each.key]
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${each.value}"
}

resource "google_secret_manager_secret_iam_member" "runtime_accessor" {
  for_each = local.production_runtime_secret_names

  project   = var.project_id
  secret_id = google_secret_manager_secret.runtime[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.runtime_service_accounts.production}"
}

resource "google_secret_manager_secret_iam_member" "preview_runtime_accessor" {
  for_each = google_secret_manager_secret.preview_runtime

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.runtime_service_accounts.preview}"
}

resource "google_secret_manager_secret_iam_member" "migrator_accessor" {
  for_each = google_secret_manager_secret.migration

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.migrator_service_accounts[each.key]}"
}

resource "google_service_account_iam_member" "github_preview" {
  service_account_id = google_service_account.deployer["preview"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_delivery_role_principals.preview_deployer
}

resource "google_service_account_iam_member" "github_production" {
  service_account_id = google_service_account.deployer["production"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_delivery_role_principals.production_deployer
}

resource "google_service_account_iam_member" "github_builder" {
  service_account_id = google_service_account.builder.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_delivery_role_principals.production_builder
}

resource "google_service_account_iam_member" "github_preview_builder" {
  service_account_id = google_service_account.preview_builder.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_delivery_role_principals.preview_builder
}

resource "google_artifact_registry_repository_iam_member" "builder_writer" {
  project    = var.project_id
  location   = local.legacy_artifact_registry_region
  repository = google_artifact_registry_repository.agent.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.builder.email}"
}

resource "google_artifact_registry_repository_iam_member" "preview_builder_writer" {
  project    = var.project_id
  location   = local.legacy_artifact_registry_region
  repository = google_artifact_registry_repository.preview_agent.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.preview_builder.email}"
}

resource "google_artifact_registry_repository_iam_member" "deployer_reader" {
  for_each = {
    production = local.deployer_service_accounts.production
  }

  project    = var.project_id
  location   = local.legacy_artifact_registry_region
  repository = google_artifact_registry_repository.agent.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${each.value}"
}

resource "google_artifact_registry_repository_iam_member" "preview_deployer_reader" {
  project    = var.project_id
  location   = local.legacy_artifact_registry_region
  repository = google_artifact_registry_repository.preview_agent.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${local.deployer_service_accounts.preview}"
}

resource "google_artifact_registry_repository_iam_member" "cloud_run_reader" {
  project    = var.project_id
  location   = local.legacy_artifact_registry_region
  repository = google_artifact_registry_repository.agent.repository_id
  role       = "roles/artifactregistry.reader"
  member     = local.cloud_run_image_pull_principal

  depends_on = [google_project_service.required]
}

resource "google_artifact_registry_repository_iam_member" "preview_cloud_run_reader" {
  project    = var.project_id
  location   = local.legacy_artifact_registry_region
  repository = google_artifact_registry_repository.preview_agent.repository_id
  role       = "roles/artifactregistry.reader"
  member     = local.cloud_run_image_pull_principal

  depends_on = [google_project_service.required]
}

resource "google_artifact_registry_repository_iam_member" "active_builder_writer" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.active_agent.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.builder.email}"
}

resource "google_artifact_registry_repository_iam_member" "active_preview_builder_writer" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.active_preview_agent.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.preview_builder.email}"
}

resource "google_artifact_registry_repository_iam_member" "active_deployer_reader" {
  for_each = {
    production = local.deployer_service_accounts.production
  }

  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.active_agent.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${each.value}"
}

resource "google_artifact_registry_repository_iam_member" "active_preview_deployer_reader" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.active_preview_agent.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${local.deployer_service_accounts.preview}"
}

resource "google_artifact_registry_repository_iam_member" "active_cloud_run_reader" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.active_agent.repository_id
  role       = "roles/artifactregistry.reader"
  member     = local.cloud_run_image_pull_principal

  depends_on = [google_project_service.required]
}

resource "google_artifact_registry_repository_iam_member" "active_preview_cloud_run_reader" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.active_preview_agent.repository_id
  role       = "roles/artifactregistry.reader"
  member     = local.cloud_run_image_pull_principal

  depends_on = [google_project_service.required]
}
