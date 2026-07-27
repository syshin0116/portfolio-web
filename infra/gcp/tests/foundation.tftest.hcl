mock_provider "google" {}

run "foundation_security_contract" {
  command = plan

  override_data {
    target = data.google_project.current
    values = {
      number     = "72919926064"
      project_id = "festive-ally-503605-v7"
    }
  }

  override_resource {
    target = google_artifact_registry_repository.agent
  }

  override_resource {
    target = google_storage_bucket.terraform_state
  }

  override_resource {
    target          = google_service_account.runtime
    override_during = plan
    values = {
      email = "agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
      name  = "projects/festive-ally-503605-v7/serviceAccounts/agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
    }
  }

  override_resource {
    target          = google_service_account.preview_runtime
    override_during = plan
    values = {
      email = "agent-preview-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
      name  = "projects/festive-ally-503605-v7/serviceAccounts/agent-preview-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
    }
  }

  override_resource {
    target          = google_service_account.deployer["preview"]
    override_during = plan
    values = {
      email = "agent-preview-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
      name  = "projects/festive-ally-503605-v7/serviceAccounts/agent-preview-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
    }
  }

  override_resource {
    target          = google_service_account.deployer["production"]
    override_during = plan
    values = {
      email = "agent-prod-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
      name  = "projects/festive-ally-503605-v7/serviceAccounts/agent-prod-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
    }
  }

  override_resource {
    target = google_iam_workload_identity_pool.github
  }

  override_resource {
    target = google_iam_workload_identity_pool_provider.preview
  }

  override_resource {
    target = google_iam_workload_identity_pool_provider.production
  }

  override_resource {
    target = google_secret_manager_secret.runtime["agent-auth-secret"]
  }

  override_resource {
    target = google_secret_manager_secret.runtime["agent-database-url"]
  }

  override_resource {
    target = google_secret_manager_secret.runtime["anthropic-api-key"]
  }

  override_resource {
    target = google_secret_manager_secret.runtime["langsmith-api-key"]
  }

  override_resource {
    target = google_secret_manager_secret.runtime["openai-api-key"]
  }

  assert {
    condition     = google_artifact_registry_repository.agent.docker_config[0].immutable_tags
    error_message = "Artifact Registry tags must be immutable."
  }

  assert {
    condition     = google_service_account.runtime.account_id == "agent-runtime"
    error_message = "The existing agent-runtime address must remain the production runtime."
  }

  assert {
    condition     = google_service_account.preview_runtime.account_id == "agent-preview-runtime"
    error_message = "Preview must use a distinct runtime identity."
  }

  assert {
    condition     = google_iam_workload_identity_pool.github.workload_identity_pool_id == "github" && !google_iam_workload_identity_pool.github.disabled
    error_message = "The GitHub workload identity pool must keep the exact ID and remain enabled."
  }

  assert {
    condition = (
      google_iam_workload_identity_pool_provider.preview.workload_identity_pool_provider_id == "github-preview"
      && google_iam_workload_identity_pool_provider.production.workload_identity_pool_provider_id == "github-production"
      && !google_iam_workload_identity_pool_provider.preview.disabled
      && !google_iam_workload_identity_pool_provider.production.disabled
    )
    error_message = "The exact Preview and Production WIF providers must remain enabled."
  }

  assert {
    condition     = google_iam_workload_identity_pool_provider.preview.attribute_condition == "assertion.repository_id == '1102380057' && assertion.repository_owner_id == '99532836' && assertion.event_name == 'pull_request' && assertion.environment == 'Preview'"
    error_message = "Preview federation must exactly pin repository, owner, pull_request, and Preview without alternate CEL branches."
  }

  assert {
    condition     = google_iam_workload_identity_pool_provider.production.attribute_condition == "assertion.repository_id == '1102380057' && assertion.repository_owner_id == '99532836' && assertion.event_name == 'push' && assertion.ref == 'refs/heads/main' && assertion.environment == 'Production'"
    error_message = "Production federation must exactly pin repository, owner, push, main, and Production without alternate CEL branches."
  }

  assert {
    condition = (
      google_iam_workload_identity_pool_provider.preview.attribute_mapping
      == tomap({
        "google.subject"                = "assertion.sub"
        "attribute.environment"         = "assertion.environment"
        "attribute.event_name"          = "assertion.event_name"
        "attribute.ref"                 = "assertion.ref"
        "attribute.repository_id"       = "assertion.repository_id"
        "attribute.repository_owner_id" = "assertion.repository_owner_id"
      })
      && google_iam_workload_identity_pool_provider.production.attribute_mapping
      == tomap({
        "google.subject"                = "assertion.sub"
        "attribute.environment"         = "assertion.environment"
        "attribute.event_name"          = "assertion.event_name"
        "attribute.ref"                 = "assertion.ref"
        "attribute.repository_id"       = "assertion.repository_id"
        "attribute.repository_owner_id" = "assertion.repository_owner_id"
      })
    )
    error_message = "Both WIF providers must expose only the reviewed GitHub OIDC claim mapping."
  }

  assert {
    condition = (
      try(length(google_iam_workload_identity_pool_provider.preview.oidc[0].allowed_audiences), 0) == 0
      && try(length(google_iam_workload_identity_pool_provider.production.oidc[0].allowed_audiences), 0) == 0
    )
    error_message = "Both WIF providers must use Google's default audience."
  }

  assert {
    condition = (
      google_service_account_iam_member.github_preview.member
      == "principalSet://iam.googleapis.com/projects/72919926064/locations/global/workloadIdentityPools/github/attribute.environment/Preview"
      && google_service_account_iam_member.github_production.member
      == "principalSet://iam.googleapis.com/projects/72919926064/locations/global/workloadIdentityPools/github/attribute.environment/Production"
    )
    error_message = "WIF principal sets must derive the current project's numeric ID."
  }

  assert {
    condition     = length(google_secret_manager_secret.runtime) == 5 && length(google_secret_manager_secret.preview_runtime) == 5
    error_message = "Each runtime environment must own exactly five empty secret resources."
  }

  assert {
    condition     = toset(keys(google_secret_manager_secret.runtime)) == local.production_secret_names && toset(keys(google_secret_manager_secret.preview_runtime)) == local.preview_secret_names && length(setintersection(local.production_secret_names, local.preview_secret_names)) == 0
    error_message = "Preview and production secret sets must be exact and disjoint."
  }

  assert {
    condition     = length(google_secret_manager_secret_iam_member.runtime_accessor) == 5 && length(google_secret_manager_secret_iam_member.preview_runtime_accessor) == 5
    error_message = "Each environment must bind only its five runtime secrets."
  }

  assert {
    condition = (
      alltrue([
        for binding in google_secret_manager_secret_iam_member.runtime_accessor :
        binding.member == "serviceAccount:agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
      ])
      && alltrue([
        for binding in google_secret_manager_secret_iam_member.preview_runtime_accessor :
        binding.member == "serviceAccount:agent-preview-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
      ])
    )
    error_message = "Each managed secretAccessor member must target its matching runtime."
  }

  assert {
    condition = (
      length(google_service_account_iam_member.deployer_uses_runtime) == 2
      && google_service_account_iam_member.deployer_uses_runtime["preview"].service_account_id == google_service_account.preview_runtime.name
      && google_service_account_iam_member.deployer_uses_runtime["production"].service_account_id == google_service_account.runtime.name
    )
    error_message = "Each managed actAs member must target its environment-specific runtime."
  }

  assert {
    condition     = !google_storage_bucket.terraform_state.force_destroy && google_storage_bucket.terraform_state.public_access_prevention == "enforced" && google_storage_bucket.terraform_state.uniform_bucket_level_access
    error_message = "The Terraform state bucket must resist deletion, block public access, and use uniform access."
  }

  assert {
    condition     = google_storage_bucket.terraform_state.versioning[0].enabled && google_storage_bucket.terraform_state.soft_delete_policy[0].retention_duration_seconds >= 2592000
    error_message = "The Terraform state bucket must retain recoverable generations."
  }
}
