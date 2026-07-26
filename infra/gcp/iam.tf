locals {
  runtime_service_account = google_service_account.runtime.email
  deployer_service_accounts = {
    for name, account in google_service_account.deployer : name => account.email
  }
}

resource "google_project_iam_member" "deployer_run_admin" {
  for_each = local.deployer_service_accounts

  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${each.value}"
}

resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  for_each = local.deployer_service_accounts

  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.agent.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${each.value}"
}

resource "google_service_account_iam_member" "deployer_uses_runtime" {
  for_each = local.deployer_service_accounts

  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${each.value}"
}

resource "google_secret_manager_secret_iam_member" "runtime_accessor" {
  for_each = google_secret_manager_secret.runtime

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.runtime_service_account}"
}

resource "google_service_account_iam_member" "github_preview" {
  service_account_id = google_service_account.deployer["preview"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${var.project_number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/attribute.environment/${var.github_preview_environment}"
}

resource "google_service_account_iam_member" "github_production" {
  service_account_id = google_service_account.deployer["production"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${var.project_number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/attribute.environment/${var.github_production_environment}"
}
