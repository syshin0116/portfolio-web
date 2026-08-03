output "artifact_registry_repository" {
  value = google_artifact_registry_repository.active_agent.name
}

output "preview_artifact_registry_repository" {
  value = google_artifact_registry_repository.active_preview_agent.name
}

output "legacy_artifact_registry_repository" {
  value = google_artifact_registry_repository.agent.name
}

output "legacy_preview_artifact_registry_repository" {
  value = google_artifact_registry_repository.preview_agent.name
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

output "builder_service_account" {
  value = google_service_account.builder.email
}

output "preview_builder_service_account" {
  value = google_service_account.preview_builder.email
}

output "preview_migrator_service_account" {
  value = google_service_account.migrator["preview"].email
}

output "production_migrator_service_account" {
  value = google_service_account.migrator["production"].email
}

output "preview_cloud_run_service" {
  value = try(google_cloud_run_v2_service.agent["preview"].name, null)
}

output "production_cloud_run_service" {
  value = try(google_cloud_run_v2_service.agent["production"].name, null)
}

output "preview_migration_job" {
  value = try(google_cloud_run_v2_job.migration["preview"].name, null)
}

output "production_migration_job" {
  value = try(google_cloud_run_v2_job.migration["production"].name, null)
}

output "preview_grant_probe_job" {
  value = try(google_cloud_run_v2_job.grant_probe["preview"].name, null)
}

output "production_grant_probe_job" {
  value = try(google_cloud_run_v2_job.grant_probe["production"].name, null)
}

output "preview_maintenance_job" {
  value = try(google_cloud_run_v2_job.maintenance["preview"].name, null)
}

output "production_maintenance_job" {
  value = try(google_cloud_run_v2_job.maintenance["production"].name, null)
}

output "maintenance_scheduler_service_account" {
  value = google_service_account.maintenance_scheduler.email
}

output "production_guest_maintenance_schedule" {
  value = try(google_cloud_scheduler_job.guest_maintenance["production"].name, null)
}

output "preview_workload_identity_provider" {
  description = "Retained legacy provider; managed disabled and not trusted by any service account."
  value       = google_iam_workload_identity_pool_provider.preview.name
}

output "production_workload_identity_provider" {
  description = "Canonical active provider for all four phase-specific delivery roles."
  value       = google_iam_workload_identity_pool_provider.production.name
}

output "delivery_workload_identity_provider" {
  description = "Canonical active provider for preview/production builder/deployer roles."
  value       = google_iam_workload_identity_pool_provider.production.name
}

output "terraform_state_bucket" {
  value = google_storage_bucket.terraform_state.name
}
