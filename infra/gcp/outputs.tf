output "artifact_registry_repository" {
  value = google_artifact_registry_repository.agent.name
}

output "runtime_service_account" {
  description = "Production runtime service account; retained for compatibility."
  value       = google_service_account.runtime.email
}

output "production_runtime_service_account" {
  value = google_service_account.runtime.email
}

output "preview_runtime_service_account" {
  value = google_service_account.preview_runtime.email
}

output "preview_deployer_service_account" {
  value = google_service_account.deployer["preview"].email
}

output "production_deployer_service_account" {
  value = google_service_account.deployer["production"].email
}

output "preview_workload_identity_provider" {
  value = google_iam_workload_identity_pool_provider.preview.name
}

output "production_workload_identity_provider" {
  value = google_iam_workload_identity_pool_provider.production.name
}

output "terraform_state_bucket" {
  value = google_storage_bucket.terraform_state.name
}
