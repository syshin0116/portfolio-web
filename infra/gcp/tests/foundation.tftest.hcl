mock_provider "google" {}

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
  target          = google_project_iam_custom_role.cloud_run_delivery
  override_during = plan
  values = {
    name = "projects/festive-ally-503605-v7/roles/cloudRunAgentDelivery"
  }
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
  target          = google_service_account.preview_builder
  override_during = plan
  values = {
    email = "agent-preview-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com"
    name  = "projects/festive-ally-503605-v7/serviceAccounts/agent-preview-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com"
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
  target = google_secret_manager_secret.migration["preview"]
}

override_resource {
  target = google_secret_manager_secret.migration["production"]
}

run "foundation_security_contract" {
  command = plan

  variables {
    agent_delivery_stage          = "services"
    agent_bootstrap_image         = "us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    agent_preview_bootstrap_image = "us-east4-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent@sha256:1111111111111111111111111111111111111111111111111111111111111111"
    agent_secret_versions = {
      agent-auth-secret                    = "11"
      agent-database-url                   = "12"
      agent-migration-database-url         = "13"
      agent-preview-anthropic-api-key      = "21"
      agent-preview-auth-secret            = "22"
      agent-preview-database-url           = "23"
      agent-preview-langsmith-api-key      = "24"
      agent-preview-migration-database-url = "25"
      anthropic-api-key                    = "14"
      langsmith-api-key                    = "15"
    }
  }

  assert {
    condition = (
      !google_artifact_registry_repository.agent.docker_config[0].immutable_tags
      && !google_artifact_registry_repository.preview_agent.docker_config[0].immutable_tags
      && !google_artifact_registry_repository.agent.cleanup_policy_dry_run
      && !google_artifact_registry_repository.preview_agent.cleanup_policy_dry_run
    )
    error_message = "Both registries must allow expired tagged versions to be deleted by active cleanup policies."
  }

  assert {
    condition = (
      length(google_artifact_registry_repository.agent.cleanup_policies) == 2
      && one([
        for policy in google_artifact_registry_repository.agent.cleanup_policies : policy
        if policy.id == "delete-after-90-days"
      ]).action == "DELETE"
      && one([
        for policy in google_artifact_registry_repository.agent.cleanup_policies : policy
        if policy.id == "delete-after-90-days"
      ]).condition[0].tag_state == "ANY"
      && one([
        for policy in google_artifact_registry_repository.agent.cleanup_policies : policy
        if policy.id == "delete-after-90-days"
      ]).condition[0].older_than == "7776000s"
      && one([
        for policy in google_artifact_registry_repository.agent.cleanup_policies : policy
        if policy.id == "keep-last-30"
      ]).action == "KEEP"
      && one([
        for policy in google_artifact_registry_repository.agent.cleanup_policies : policy
        if policy.id == "keep-last-30"
      ]).most_recent_versions[0].keep_count == 30
    )
    error_message = "Production images must retain at least 30 versions and 90 days of rollback history."
  }

  assert {
    condition = (
      length(google_artifact_registry_repository.preview_agent.cleanup_policies) == 2
      && one([
        for policy in google_artifact_registry_repository.preview_agent.cleanup_policies : policy
        if policy.id == "delete-after-14-days"
      ]).action == "DELETE"
      && one([
        for policy in google_artifact_registry_repository.preview_agent.cleanup_policies : policy
        if policy.id == "delete-after-14-days"
      ]).condition[0].tag_state == "ANY"
      && one([
        for policy in google_artifact_registry_repository.preview_agent.cleanup_policies : policy
        if policy.id == "delete-after-14-days"
      ]).condition[0].older_than == "1209600s"
      && one([
        for policy in google_artifact_registry_repository.preview_agent.cleanup_policies : policy
        if policy.id == "keep-last-20"
      ]).action == "KEEP"
      && one([
        for policy in google_artifact_registry_repository.preview_agent.cleanup_policies : policy
        if policy.id == "keep-last-20"
      ]).most_recent_versions[0].keep_count == 20
    )
    error_message = "Preview images must retain at least 20 versions and 14 days of history."
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
      && google_iam_workload_identity_pool_provider.preview.disabled
      && !google_iam_workload_identity_pool_provider.production.disabled
    )
    error_message = "The legacy Preview provider must remain managed disabled and github-production must remain the sole active delivery provider."
  }

  assert {
    condition     = google_iam_workload_identity_pool_provider.preview.attribute_condition == "attribute.repository_id == '__legacy_provider_disabled__'"
    error_message = "The retained legacy provider condition must be inert even before its disabled state is evaluated."
  }

  assert {
    condition     = google_iam_workload_identity_pool_provider.production.attribute_condition == "attribute.repository_id == '1102380057' && attribute.repository_owner_id == '99532836' && attribute.delivery_role in ['preview-builder', 'preview-deployer', 'production-builder', 'production-deployer']"
    error_message = "Active federation must accept only mapped immutable repository/owner IDs and one of the four exact delivery roles."
  }

  assert {
    condition = (
      google_iam_workload_identity_pool_provider.preview.attribute_mapping
      == tomap({
        "google.subject"          = "assertion.sub"
        "attribute.repository_id" = "assertion.repository_id"
      })
      && google_iam_workload_identity_pool_provider.production.attribute_mapping
      == tomap({
        "google.subject"                = "assertion.sub"
        "attribute.repository_id"       = "assertion.repository_id"
        "attribute.repository_owner_id" = "assertion.repository_owner_id"
        "attribute.delivery_role"       = "assertion.event_name == 'pull_request' && assertion.workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/preview-agent.yml@' + assertion.ref ? (assertion.job_workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/agent-image-build.yml@' + assertion.ref ? 'preview-builder' : assertion.environment == 'Agent Preview' && assertion.job_workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/agent-release.yml@' + assertion.ref ? 'preview-deployer' : 'invalid') : assertion.event_name in ['push', 'workflow_dispatch'] && assertion.ref == 'refs/heads/main' && assertion.workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/deploy-agent.yml@refs/heads/main' ? (assertion.job_workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/agent-image-build.yml@refs/heads/main' ? 'production-builder' : assertion.environment == 'Agent Production' && assertion.job_workflow_ref == 'syshin0116/syshin0116.dev/.github/workflows/agent-release.yml@refs/heads/main' ? 'production-deployer' : 'invalid') : 'invalid'"
      })
    )
    error_message = "Every provider condition field must be mapped, and only the active provider may map the exact four machine-safe delivery roles."
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
      == "principalSet://iam.googleapis.com/projects/72919926064/locations/global/workloadIdentityPools/github/attribute.delivery_role/preview-deployer"
      && google_service_account_iam_member.github_production.member
      == "principalSet://iam.googleapis.com/projects/72919926064/locations/global/workloadIdentityPools/github/attribute.delivery_role/production-deployer"
      && google_service_account_iam_member.github_builder.member
      == "principalSet://iam.googleapis.com/projects/72919926064/locations/global/workloadIdentityPools/github/attribute.delivery_role/production-builder"
      && google_service_account_iam_member.github_preview_builder.member
      == "principalSet://iam.googleapis.com/projects/72919926064/locations/global/workloadIdentityPools/github/attribute.delivery_role/preview-builder"
      && length(toset([
        google_service_account_iam_member.github_preview.member,
        google_service_account_iam_member.github_production.member,
        google_service_account_iam_member.github_builder.member,
        google_service_account_iam_member.github_preview_builder.member,
      ])) == 4
    )
    error_message = "Each builder/deployer must trust exactly one distinct delivery role, preventing cross-environment or cross-phase impersonation."
  }

  assert {
    condition     = length(google_secret_manager_secret.runtime) == 4 && length(google_secret_manager_secret.preview_runtime) == 4 && length(google_secret_manager_secret.migration) == 2
    error_message = "Each runtime environment must own exactly four runtime secrets and one separate migration URL."
  }

  assert {
    condition     = toset(keys(google_secret_manager_secret.runtime)) == local.production_secret_names && toset(keys(google_secret_manager_secret.preview_runtime)) == local.preview_secret_names && length(setintersection(local.production_secret_names, local.preview_secret_names)) == 0
    error_message = "Preview and production secret sets must be exact and disjoint."
  }

  assert {
    condition     = length(google_secret_manager_secret_iam_member.runtime_accessor) == 4 && length(google_secret_manager_secret_iam_member.preview_runtime_accessor) == 4
    error_message = "Each environment must bind only its four runtime secrets."
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
      && google_artifact_registry_repository_iam_member.builder_writer.repository == "agent"
      && google_artifact_registry_repository_iam_member.preview_builder_writer.member == "serviceAccount:agent-preview-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com"
      && google_artifact_registry_repository_iam_member.preview_builder_writer.repository == "agent-preview"
      && length(google_artifact_registry_repository_iam_member.deployer_reader) == 1
      && google_artifact_registry_repository_iam_member.deployer_reader["production"].member == "serviceAccount:agent-prod-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
      && google_artifact_registry_repository_iam_member.preview_deployer_reader.member == "serviceAccount:agent-preview-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
      && google_artifact_registry_repository_iam_member.cloud_run_reader.role == "roles/artifactregistry.reader"
      && google_artifact_registry_repository_iam_member.cloud_run_reader.member == "serviceAccount:service-72919926064@serverless-robot-prod.iam.gserviceaccount.com"
      && google_artifact_registry_repository_iam_member.preview_cloud_run_reader.member == "serviceAccount:service-72919926064@serverless-robot-prod.iam.gserviceaccount.com"
      && google_service_account_iam_member.github_builder.member == local.github_delivery_role_principals.production_builder
      && google_service_account_iam_member.github_preview_builder.member == local.github_delivery_role_principals.preview_builder
    )
    error_message = "Preview and production builders, repositories, readers, and WIF principals must remain disjoint."
  }

  assert {
    condition = alltrue([
      for environment, service in google_cloud_run_v2_service.agent :
      service.template[0].scaling[0].max_instance_count == 1
      && service.template[0].max_instance_request_concurrency == 8
      && service.template[0].containers[0].image == (
        environment == "preview"
        ? var.agent_preview_bootstrap_image
        : var.agent_bootstrap_image
      )
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
      && length(service.template[0].containers[0].env) == 17
      && {
        for env in service.template[0].containers[0].env :
        env.name => env.value
        if try(env.value, null) != null
      } == local.cloud_run_runtime_environment
      && length([
        for env in service.template[0].containers[0].env : env
        if try(env.value_source[0].secret_key_ref[0].version, null) != null
      ]) == 4
      && alltrue([
        for env in service.template[0].containers[0].env :
        try(
          env.value_source[0].secret_key_ref[0].version
          == var.agent_secret_versions[env.value_source[0].secret_key_ref[0].secret],
          true,
        )
      ])
    ])
    error_message = "Both services must keep the immutable image, one-instance/one-worker runtime, deletion protection, and exact numeric secret pins."
  }

  assert {
    condition = (
      length(google_cloud_run_v2_job.migration) == 2
      && length(google_cloud_run_v2_job.grant_probe) == 2
      && alltrue([
        for environment, job in google_cloud_run_v2_job.migration :
        job.template[0].template[0].containers[0].image == (
          environment == "preview"
          ? var.agent_preview_bootstrap_image
          : var.agent_bootstrap_image
        )
        && job.template[0].template[0].containers[0].args == tolist(["-m", "agent.migrate"])
        && job.template[0].template[0].max_retries == 0
        && job.template[0].template[0].execution_environment == "EXECUTION_ENVIRONMENT_GEN2"
        && length([
          for env in job.template[0].template[0].containers[0].env : env
          if try(env.value_source[0].secret_key_ref[0].version, null) != null
        ]) == 1
        && alltrue([
          for env in job.template[0].template[0].containers[0].env :
          env.value_source[0].secret_key_ref[0].version
          == var.agent_secret_versions[env.value_source[0].secret_key_ref[0].secret]
          if try(env.value_source[0].secret_key_ref[0].version, null) != null
        ])
        && job.deletion_protection
      ])
      && alltrue([
        for environment, job in google_cloud_run_v2_job.grant_probe :
        job.template[0].template[0].containers[0].image == (
          environment == "preview"
          ? var.agent_preview_bootstrap_image
          : var.agent_bootstrap_image
        )
        && job.template[0].template[0].containers[0].args == tolist(["-m", "agent.neon_grant_probe"])
        && job.template[0].template[0].max_retries == 0
        && job.template[0].template[0].execution_environment == "EXECUTION_ENVIRONMENT_GEN2"
        && length([
          for env in job.template[0].template[0].containers[0].env : env
          if try(env.value_source[0].secret_key_ref[0].version, null) != null
        ]) == 1
        && alltrue([
          for env in job.template[0].template[0].containers[0].env :
          env.value_source[0].secret_key_ref[0].version
          == var.agent_secret_versions[env.value_source[0].secret_key_ref[0].secret]
          if try(env.value_source[0].secret_key_ref[0].version, null) != null
        ])
        && job.deletion_protection
      ])
    )
    error_message = "Every environment must run same-image one-shot jobs using exact numeric secret pins."
  }

  assert {
    condition = (
      length(google_cloud_run_v2_service_iam_member.deployer_service_update) == 2
      && length(google_cloud_run_v2_job_iam_member.deployer_migration_job) == 2
      && length(google_cloud_run_v2_job_iam_member.deployer_grant_probe_job) == 2
      && toset(google_project_iam_custom_role.cloud_run_delivery.permissions) == toset([
        "run.jobs.get",
        "run.jobs.run",
        "run.jobs.update",
        "run.operations.get",
        "run.revisions.get",
        "run.services.get",
        "run.services.update",
      ])
      && alltrue([
        for environment, binding in google_cloud_run_v2_service_iam_member.deployer_service_update :
        binding.role == google_project_iam_custom_role.cloud_run_delivery.name
        && binding.member == "serviceAccount:${local.cloud_run_environments[environment].deployer_service_account}"
      ])
      && alltrue([
        for environment, binding in google_cloud_run_v2_job_iam_member.deployer_migration_job :
        binding.role == google_project_iam_custom_role.cloud_run_delivery.name
        && binding.member == "serviceAccount:${local.cloud_run_environments[environment].deployer_service_account}"
      ])
      && alltrue([
        for environment, binding in google_cloud_run_v2_job_iam_member.deployer_grant_probe_job :
        binding.role == google_project_iam_custom_role.cloud_run_delivery.name
        && binding.member == "serviceAccount:${local.cloud_run_environments[environment].deployer_service_account}"
      ])
    )
    error_message = "Deployers must keep only the exact seven-permission custom role on their matching service and one-shot jobs."
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

run "foundation_bootstrap_contract" {
  command = plan

  variables {
    agent_delivery_stage          = "foundation"
    agent_bootstrap_image         = null
    agent_preview_bootstrap_image = null
    agent_secret_versions         = null
  }

  assert {
    condition = (
      length(google_cloud_run_v2_service.agent) == 0
      && length(google_cloud_run_v2_job.migration) == 0
      && length(google_cloud_run_v2_job.grant_probe) == 0
      && length(google_cloud_run_v2_service_iam_member.public_invoker) == 0
      && length(google_cloud_run_v2_service_iam_member.deployer_service_update) == 0
      && length(google_cloud_run_v2_job_iam_member.deployer_migration_job) == 0
      && length(google_cloud_run_v2_job_iam_member.deployer_grant_probe_job) == 0
    )
    error_message = "The foundation stage must create no Cloud Run service, job, or resource-scoped delivery binding."
  }

  assert {
    condition = (
      length(google_secret_manager_secret.runtime) == 4
      && length(google_secret_manager_secret.preview_runtime) == 4
      && length(google_secret_manager_secret.migration) == 2
      && google_artifact_registry_repository.agent.repository_id == "agent"
      && google_artifact_registry_repository.preview_agent.repository_id == "agent-preview"
    )
    error_message = "The foundation stage must still create the registry and all empty secret resources needed before delivery."
  }

  assert {
    condition = (
      output.preview_cloud_run_service == null
      && output.production_cloud_run_service == null
      && output.preview_migration_job == null
      && output.production_migration_job == null
      && output.preview_grant_probe_job == null
      && output.production_grant_probe_job == null
    )
    error_message = "Foundation-stage Cloud Run outputs must remain null."
  }
}

run "jobs_bootstrap_contract" {
  command = plan

  variables {
    agent_delivery_stage          = "jobs"
    agent_bootstrap_image         = "us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    agent_preview_bootstrap_image = "us-east4-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent@sha256:1111111111111111111111111111111111111111111111111111111111111111"
    agent_secret_versions = {
      agent-auth-secret                    = "11"
      agent-database-url                   = "12"
      agent-migration-database-url         = "13"
      agent-preview-anthropic-api-key      = "21"
      agent-preview-auth-secret            = "22"
      agent-preview-database-url           = "23"
      agent-preview-langsmith-api-key      = "24"
      agent-preview-migration-database-url = "25"
      anthropic-api-key                    = "14"
      langsmith-api-key                    = "15"
    }
  }

  assert {
    condition = (
      length(google_cloud_run_v2_service.agent) == 0
      && length(google_cloud_run_v2_service_iam_member.public_invoker) == 0
      && length(google_cloud_run_v2_service_iam_member.deployer_service_update) == 0
      && length(google_cloud_run_v2_job.migration) == 2
      && length(google_cloud_run_v2_job.grant_probe) == 2
      && length(google_cloud_run_v2_job_iam_member.deployer_migration_job) == 2
      && length(google_cloud_run_v2_job_iam_member.deployer_grant_probe_job) == 2
    )
    error_message = "The jobs stage must create both environments' jobs and bindings without creating a serving surface."
  }

  assert {
    condition = (
      alltrue([
        for environment, job in google_cloud_run_v2_job.migration :
        job.template[0].template[0].containers[0].image == (
          environment == "preview"
          ? var.agent_preview_bootstrap_image
          : var.agent_bootstrap_image
        )
        && alltrue([
          for env in job.template[0].template[0].containers[0].env :
          can(regex("^[1-9][0-9]*$", env.value_source[0].secret_key_ref[0].version))
          if try(env.value_source[0].secret_key_ref[0].version, null) != null
        ])
      ])
      && alltrue([
        for environment, job in google_cloud_run_v2_job.grant_probe :
        job.template[0].template[0].containers[0].image == (
          environment == "preview"
          ? var.agent_preview_bootstrap_image
          : var.agent_bootstrap_image
        )
        && alltrue([
          for env in job.template[0].template[0].containers[0].env :
          can(regex("^[1-9][0-9]*$", env.value_source[0].secret_key_ref[0].version))
          if try(env.value_source[0].secret_key_ref[0].version, null) != null
        ])
      ])
    )
    error_message = "The jobs stage must use the reviewed digest and positive numeric secret versions."
  }

  assert {
    condition = (
      output.preview_cloud_run_service == null
      && output.production_cloud_run_service == null
      && output.preview_migration_job == "agent-preview-migrate"
      && output.production_migration_job == "agent-migrate"
      && output.preview_grant_probe_job == "agent-preview-grants"
      && output.production_grant_probe_job == "agent-grants"
    )
    error_message = "The jobs stage must expose only the four one-shot job names."
  }
}
