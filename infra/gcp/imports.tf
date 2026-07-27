import {
  to = google_artifact_registry_repository.agent
  id = "projects/${var.project_id}/locations/${var.region}/repositories/agent"
}

import {
  to = google_storage_bucket.terraform_state
  id = "${var.project_id}-tfstate"
}

import {
  to = google_service_account.runtime
  id = "projects/${var.project_id}/serviceAccounts/agent-runtime@${var.project_id}.iam.gserviceaccount.com"
}

import {
  to = google_service_account.deployer["preview"]
  id = "projects/${var.project_id}/serviceAccounts/agent-preview-deployer@${var.project_id}.iam.gserviceaccount.com"
}

import {
  to = google_service_account.deployer["production"]
  id = "projects/${var.project_id}/serviceAccounts/agent-prod-deployer@${var.project_id}.iam.gserviceaccount.com"
}

import {
  to = google_iam_workload_identity_pool.github
  id = "projects/${var.project_id}/locations/global/workloadIdentityPools/github"
}

import {
  to = google_iam_workload_identity_pool_provider.preview
  id = "projects/${var.project_id}/locations/global/workloadIdentityPools/github/providers/github-preview"
}

import {
  to = google_iam_workload_identity_pool_provider.production
  id = "projects/${var.project_id}/locations/global/workloadIdentityPools/github/providers/github-production"
}

import {
  for_each = local.production_secret_names

  to = google_secret_manager_secret.runtime[each.value]
  id = "projects/${var.project_id}/secrets/${each.value}"
}
