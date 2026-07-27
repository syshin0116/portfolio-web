locals {
  cloud_run_environments = {
    preview = {
      service_name             = "agent-preview"
      migration_job_name       = "agent-preview-migrate"
      grant_probe_job_name     = "agent-preview-grants"
      runtime_service_account  = google_service_account.preview_runtime.email
      migrator_service_account = google_service_account.migrator["preview"].email
      deployer_service_account = google_service_account.deployer["preview"].email
      bootstrap_image          = var.agent_preview_bootstrap_image
      migration_secret         = google_secret_manager_secret.migration["preview"].secret_id
      migration_secret_version = try(var.agent_secret_versions["agent-preview-migration-database-url"], null)
      project_label            = "syshin0116-agent-preview"
      runtime_secrets = {
        AGENT_AUTH_SECRET = {
          secret  = google_secret_manager_secret.preview_runtime["agent-preview-auth-secret"].secret_id
          version = try(var.agent_secret_versions["agent-preview-auth-secret"], null)
        }
        ANTHROPIC_API_KEY = {
          secret  = google_secret_manager_secret.preview_runtime["agent-preview-anthropic-api-key"].secret_id
          version = try(var.agent_secret_versions["agent-preview-anthropic-api-key"], null)
        }
        DATABASE_URL = {
          secret  = google_secret_manager_secret.preview_runtime["agent-preview-database-url"].secret_id
          version = try(var.agent_secret_versions["agent-preview-database-url"], null)
        }
        LANGCHAIN_API_KEY = {
          secret  = google_secret_manager_secret.preview_runtime["agent-preview-langsmith-api-key"].secret_id
          version = try(var.agent_secret_versions["agent-preview-langsmith-api-key"], null)
        }
        OPENAI_API_KEY = {
          secret  = google_secret_manager_secret.preview_runtime["agent-preview-openai-api-key"].secret_id
          version = try(var.agent_secret_versions["agent-preview-openai-api-key"], null)
        }
      }
    }
    production = {
      service_name             = "agent"
      migration_job_name       = "agent-migrate"
      grant_probe_job_name     = "agent-grants"
      runtime_service_account  = google_service_account.runtime.email
      migrator_service_account = google_service_account.migrator["production"].email
      deployer_service_account = google_service_account.deployer["production"].email
      bootstrap_image          = var.agent_bootstrap_image
      migration_secret         = google_secret_manager_secret.migration["production"].secret_id
      migration_secret_version = try(var.agent_secret_versions["agent-migration-database-url"], null)
      project_label            = "syshin0116-agent-production"
      runtime_secrets = {
        AGENT_AUTH_SECRET = {
          secret  = google_secret_manager_secret.runtime["agent-auth-secret"].secret_id
          version = try(var.agent_secret_versions["agent-auth-secret"], null)
        }
        ANTHROPIC_API_KEY = {
          secret  = google_secret_manager_secret.runtime["anthropic-api-key"].secret_id
          version = try(var.agent_secret_versions["anthropic-api-key"], null)
        }
        DATABASE_URL = {
          secret  = google_secret_manager_secret.runtime["agent-database-url"].secret_id
          version = try(var.agent_secret_versions["agent-database-url"], null)
        }
        LANGCHAIN_API_KEY = {
          secret  = google_secret_manager_secret.runtime["langsmith-api-key"].secret_id
          version = try(var.agent_secret_versions["langsmith-api-key"], null)
        }
        OPENAI_API_KEY = {
          secret  = google_secret_manager_secret.runtime["openai-api-key"].secret_id
          version = try(var.agent_secret_versions["openai-api-key"], null)
        }
      }
    }
  }

  cloud_run_runtime_environment = {
    AEGRA_CONFIG              = "/app/aegra.json"
    BG_JOB_MAX_RETRIES        = "0"
    ENV_MODE                  = "PRODUCTION"
    FF_V2_EVENT_STREAMING     = "true"
    HOST                      = "0.0.0.0"
    LANGGRAPH_MAX_POOL_SIZE   = "4"
    LANGGRAPH_MIN_POOL_SIZE   = "1"
    MODEL                     = "anthropic:claude-sonnet-4-6"
    PORT                      = "8080"
    REDIS_BROKER_ENABLED      = "false"
    RUN_MIGRATIONS_ON_STARTUP = "false"
    SQLALCHEMY_MAX_OVERFLOW   = "0"
    SQLALCHEMY_POOL_SIZE      = "2"
  }
}

resource "google_cloud_run_v2_service" "agent" {
  for_each = var.agent_delivery_stage == "services" ? local.cloud_run_environments : {}

  project             = var.project_id
  name                = each.value.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = true

  template {
    service_account                  = each.value.runtime_service_account
    timeout                          = "300s"
    max_instance_request_concurrency = 8
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      name    = "agent"
      image   = each.value.bootstrap_image
      command = ["uvicorn"]
      args = [
        "aegra_api.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
        "--workers",
        "1",
      ]

      ports {
        name           = "http1"
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.cloud_run_runtime_environment
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = each.value.runtime_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value.secret
              version = env.value.version
            }
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 5
        period_seconds        = 5
        failure_threshold     = 24

        http_get {
          path = "/ready"
          port = 8080
        }
      }

      liveness_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 5
        period_seconds        = 30
        failure_threshold     = 3

        http_get {
          path = "/live"
          port = 8080
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_artifact_registry_repository_iam_member.cloud_run_reader,
    google_artifact_registry_repository_iam_member.preview_cloud_run_reader,
    google_secret_manager_secret_iam_member.preview_runtime_accessor,
    google_secret_manager_secret_iam_member.runtime_accessor,
  ]

  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      template[0].containers[0].image,
      traffic,
    ]
  }
}

resource "google_cloud_run_v2_job" "migration" {
  for_each = var.agent_delivery_stage == "foundation" ? {} : local.cloud_run_environments

  project             = var.project_id
  name                = each.value.migration_job_name
  location            = var.region
  deletion_protection = true

  template {
    template {
      service_account       = each.value.migrator_service_account
      max_retries           = 0
      timeout               = "900s"
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

      containers {
        name    = "migration"
        image   = each.value.bootstrap_image
        command = ["python"]
        args    = ["-m", "agent.migrate"]

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }

        env {
          name  = "ENV_MODE"
          value = "PRODUCTION"
        }

        env {
          name  = "RUN_MIGRATIONS_ON_STARTUP"
          value = "false"
        }

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = each.value.migration_secret
              version = each.value.migration_secret_version
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_artifact_registry_repository_iam_member.cloud_run_reader,
    google_artifact_registry_repository_iam_member.preview_cloud_run_reader,
    google_secret_manager_secret_iam_member.migrator_accessor,
  ]

  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
  }
}

resource "google_cloud_run_v2_job" "grant_probe" {
  for_each = var.agent_delivery_stage == "foundation" ? {} : local.cloud_run_environments

  project             = var.project_id
  name                = each.value.grant_probe_job_name
  location            = var.region
  deletion_protection = true

  template {
    template {
      service_account       = each.value.runtime_service_account
      max_retries           = 0
      timeout               = "600s"
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

      containers {
        name    = "grant-probe"
        image   = each.value.bootstrap_image
        command = ["python"]
        args    = ["-m", "agent.neon_grant_probe"]

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }

        env {
          name  = "ENV_MODE"
          value = "PRODUCTION"
        }

        env {
          name  = "RUN_MIGRATIONS_ON_STARTUP"
          value = "false"
        }

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = each.value.runtime_secrets.DATABASE_URL.secret
              version = each.value.runtime_secrets.DATABASE_URL.version
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_artifact_registry_repository_iam_member.cloud_run_reader,
    google_artifact_registry_repository_iam_member.preview_cloud_run_reader,
    google_secret_manager_secret_iam_member.preview_runtime_accessor,
    google_secret_manager_secret_iam_member.runtime_accessor,
  ]

  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  for_each = google_cloud_run_v2_service.agent

  project  = var.project_id
  location = each.value.location
  name     = each.value.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "deployer_service_update" {
  for_each = google_cloud_run_v2_service.agent

  project  = var.project_id
  location = each.value.location
  name     = each.value.name
  role     = google_project_iam_custom_role.cloud_run_delivery.name
  member   = "serviceAccount:${local.cloud_run_environments[each.key].deployer_service_account}"
}

resource "google_cloud_run_v2_job_iam_member" "deployer_migration_job" {
  for_each = google_cloud_run_v2_job.migration

  project  = var.project_id
  location = each.value.location
  name     = each.value.name
  role     = google_project_iam_custom_role.cloud_run_delivery.name
  member   = "serviceAccount:${local.cloud_run_environments[each.key].deployer_service_account}"
}

resource "google_cloud_run_v2_job_iam_member" "deployer_grant_probe_job" {
  for_each = google_cloud_run_v2_job.grant_probe

  project  = var.project_id
  location = each.value.location
  name     = each.value.name
  role     = google_project_iam_custom_role.cloud_run_delivery.name
  member   = "serviceAccount:${local.cloud_run_environments[each.key].deployer_service_account}"
}
