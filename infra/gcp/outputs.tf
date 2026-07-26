output "artifact_registry_repository" {
  value = google_artifact_registry_repository.agent.name
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
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
