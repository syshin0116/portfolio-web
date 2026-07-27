import {
  to = google_artifact_registry_repository.agent
  id = "projects/festive-ally-503605-v7/locations/us-east4/repositories/agent"
}

import {
  to = google_storage_bucket.terraform_state
  id = "festive-ally-503605-v7-tfstate"
}

import {
  to = google_service_account.runtime
  id = "projects/festive-ally-503605-v7/serviceAccounts/agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
}

import {
  to = google_service_account.deployer["preview"]
  id = "projects/festive-ally-503605-v7/serviceAccounts/agent-preview-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
}

import {
  to = google_service_account.deployer["production"]
  id = "projects/festive-ally-503605-v7/serviceAccounts/agent-prod-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
}

import {
  to = google_iam_workload_identity_pool.github
  id = "projects/festive-ally-503605-v7/locations/global/workloadIdentityPools/github"
}

import {
  to = google_iam_workload_identity_pool_provider.preview
  id = "projects/festive-ally-503605-v7/locations/global/workloadIdentityPools/github/providers/github-preview"
}

import {
  to = google_iam_workload_identity_pool_provider.production
  id = "projects/festive-ally-503605-v7/locations/global/workloadIdentityPools/github/providers/github-production"
}

import {
  for_each = local.production_secret_names

  to = google_secret_manager_secret.runtime[each.value]
  id = "projects/festive-ally-503605-v7/secrets/${each.value}"
}
