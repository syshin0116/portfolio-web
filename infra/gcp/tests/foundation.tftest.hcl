mock_provider "google" {}

run "foundation_security_contract" {
  command = plan

  variables {
    agent_bootstrap_image = "us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  }

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
    target          = google_service_account.builder
    override_during = plan
    values = {
      email = "agent-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com"
      name  = "projects/festive-ally-503605-v7/serviceAccounts/agent-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com"
    }
  }

  override_resource {
    target          = google_service_account.migrator["preview"]
    override_during = plan
    values = {
      email = "agent-preview-migrator@festive-ally-503605-v7.iam.gserviceaccount.com"
      name  = "projects/festive-ally-503605-v7/serviceAccounts/agent-preview-migrator@festive-ally-503605-v7.iam.gserviceaccount.com"
    }
  }

  override_resource {
    target          = google_service_account.migrator["production"]
    override_during = plan
    values = {
      email = "agent-prod-migrator@festive-ally-503605-v7.iam.gserviceaccount.com"
      name  = "projects/festive-ally-503605-v7/serviceAccounts/agent-prod-migrator@festive-ally-503605-v7.iam.gserviceaccount.com"
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

  override_resource {
    target = google_secret_manager_secret.migration["preview"]
  }

  override_resource {
    target = google_secret_manager_secret.migration["production"]
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
    condition     = google_iam_workload_identity_pool_provider.preview.attribute_condition == "assertion.repository_id == '1102380057' && assertion.repository_owner_id == '99532836' && assertion.event_name == 'pull_request' && assertion.environment == 'Agent Preview' && assertion.workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/preview-agent.yml@' + assertion.ref && assertion.job_workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/agent-delivery.yml@' + assertion.ref"
    error_message = "Preview federation must exactly pin repository, owner, event, environment, caller, and reusable workflow."
  }

  assert {
    condition     = google_iam_workload_identity_pool_provider.production.attribute_condition == "assertion.repository_id == '1102380057' && assertion.repository_owner_id == '99532836' && assertion.event_name in ['push', 'workflow_dispatch'] && assertion.ref == 'refs/heads/main' && assertion.environment == 'Agent Production' && assertion.workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/deploy-agent.yml@refs/heads/main' && assertion.job_workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/agent-delivery.yml@refs/heads/main'"
    error_message = "Production federation must exactly pin repository, owner, event, main, environment, caller, and reusable workflow."
  }

  assert {
    condition = (
      google_iam_workload_identity_pool_provider.preview.attribute_mapping
      == tomap({
        "google.subject"                = "assertion.sub"
        "attribute.environment"         = "assertion.environment"
        "attribute.event_name"          = "assertion.event_name"
        "attribute.job_workflow_ref"    = "assertion.job_workflow_ref"
        "attribute.ref"                 = "assertion.ref"
        "attribute.repository_id"       = "assertion.repository_id"
        "attribute.repository_owner_id" = "assertion.repository_owner_id"
        "attribute.workflow_ref"        = "assertion.workflow_ref"
      })
      && google_iam_workload_identity_pool_provider.production.attribute_mapping
      == tomap({
        "google.subject"                = "assertion.sub"
        "attribute.environment"         = "assertion.environment"
        "attribute.event_name"          = "assertion.event_name"
        "attribute.job_workflow_ref"    = "assertion.job_workflow_ref"
        "attribute.ref"                 = "assertion.ref"
        "attribute.repository_id"       = "assertion.repository_id"
        "attribute.repository_owner_id" = "assertion.repository_owner_id"
        "attribute.workflow_ref"        = "assertion.workflow_ref"
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
      == "principalSet://iam.googleapis.com/projects/72919926064/locations/global/workloadIdentityPools/github/attribute.environment/Agent Preview"
      && google_service_account_iam_member.github_production.member
      == "principalSet://iam.googleapis.com/projects/72919926064/locations/global/workloadIdentityPools/github/attribute.environment/Agent Production"
    )
    error_message = "WIF principal sets must derive the current project's numeric ID."
  }

  assert {
    condition     = length(google_secret_manager_secret.runtime) == 5 && length(google_secret_manager_secret.preview_runtime) == 5 && length(google_secret_manager_secret.migration) == 2
    error_message = "Each runtime environment must own exactly five runtime secrets and one separate migration URL."
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
    condition = (
      length(google_service_account_iam_member.deployer_uses_migrator) == 2
      && google_service_account_iam_member.deployer_uses_migrator["preview"].service_account_id == google_service_account.migrator["preview"].name
      && google_service_account_iam_member.deployer_uses_migrator["production"].service_account_id == google_service_account.migrator["production"].name
    )
    error_message = "Each deployer may act only as its environment-specific migration identity."
  }

  assert {
    condition = (
      google_artifact_registry_repository_iam_member.builder_writer.role == "roles/artifactregistry.writer"
      && google_artifact_registry_repository_iam_member.builder_writer.member == "serviceAccount:agent-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com"
      && google_artifact_registry_repository_iam_member.cloud_run_reader.role == "roles/artifactregistry.reader"
      && google_artifact_registry_repository_iam_member.cloud_run_reader.member == "serviceAccount:service-72919926064@serverless-robot-prod.iam.gserviceaccount.com"
    )
    error_message = "Only the builder writes images and only the Cloud Run service agent is the explicit reader."
  }

  assert {
    condition = alltrue([
      for environment, service in google_cloud_run_v2_service.agent :
      service.template[0].scaling[0].max_instance_count == 1
      && service.template[0].max_instance_request_concurrency == 8
      && service.template[0].containers[0].image == var.agent_bootstrap_image
      && service.template[0].containers[0].command == tolist(["uvicorn"])
      && service.template[0].containers[0].args == tolist([
        "aegra_api.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
        "--workers",
        "1",
      ])
      && service.deletion_protection
    ])
    error_message = "Both services must keep the immutable image, one-instance/one-worker runtime, and deletion protection."
  }

  assert {
    condition = (
      length(google_cloud_run_v2_job.migration) == 2
      && length(google_cloud_run_v2_job.grant_probe) == 2
      && alltrue([
        for environment, job in google_cloud_run_v2_job.migration :
        job.template[0].template[0].containers[0].image == var.agent_bootstrap_image
        && job.template[0].template[0].containers[0].args == tolist(["-m", "agent.migrate"])
        && job.template[0].template[0].max_retries == 0
        && job.deletion_protection
      ])
      && alltrue([
        for environment, job in google_cloud_run_v2_job.grant_probe :
        job.template[0].template[0].containers[0].image == var.agent_bootstrap_image
        && job.template[0].template[0].containers[0].args == tolist(["-m", "agent.neon_grant_probe"])
        && job.template[0].template[0].max_retries == 0
        && job.deletion_protection
      ])
    )
    error_message = "Every environment must run same-image one-shot migration and grant-probe jobs."
  }

  assert {
    condition = (
      length(google_cloud_run_v2_service_iam_member.deployer_service_update) == 2
      && length(google_cloud_run_v2_job_iam_member.deployer_migration_job) == 2
      && length(google_cloud_run_v2_job_iam_member.deployer_grant_probe_job) == 2
      && alltrue([
        for environment, binding in google_cloud_run_v2_service_iam_member.deployer_service_update :
        binding.role == "roles/run.developer"
        && binding.member == "serviceAccount:${local.cloud_run_environments[environment].deployer_service_account}"
      ])
    )
    error_message = "Deployers must remain resource-scoped to their matching service and one-shot jobs."
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
