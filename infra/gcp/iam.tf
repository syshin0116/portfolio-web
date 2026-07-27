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
}

resource "google_service_account_iam_member" "deployer_uses_runtime" {
  for_each = local.deployer_service_accounts

  service_account_id = local.runtime_service_account_ids[each.key]
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${each.value}"
}

resource "google_secret_manager_secret_iam_member" "runtime_accessor" {
  for_each = google_secret_manager_secret.runtime

  project   = var.project_id
  secret_id = each.value.secret_id
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

resource "google_service_account_iam_member" "github_preview" {
  service_account_id = google_service_account.deployer["preview"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/attribute.environment/${var.github_preview_environment}"
}

resource "google_service_account_iam_member" "github_production" {
  service_account_id = google_service_account.deployer["production"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/attribute.environment/${var.github_production_environment}"
}
