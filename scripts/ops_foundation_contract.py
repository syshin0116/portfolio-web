#!/usr/bin/env python3
"""Credential-free static and JSON policy contracts for the GCP foundation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

EXPECTED_TERRAFORM_FILES = frozenset(
    {
        "infra/gcp/backend.tf",
        "infra/gcp/cloud_run.tf",
        "infra/gcp/iam.tf",
        "infra/gcp/imports.tf",
        "infra/gcp/main.tf",
        "infra/gcp/outputs.tf",
        "infra/gcp/state.tf",
        "infra/gcp/variables.tf",
        "infra/gcp/versions.tf",
    }
)
EXPECTED_TERRAFORM_TEST_FILES = {
    "infra/gcp/tests/foundation.tftest.hcl": (
        "48c4532361c47c46159707e98d173bfca66b3311ad457ddc59e7b6872ba09d1b"
    )
}
EXPECTED_PINNED_TERRAFORM_FILES = {
    # cloud_run.tf is deliberately pinned byte-for-byte because its deeply nested
    # service/job templates are materially easier to weaken through small drift
    # than through a reviewed replacement of the complete file.
    "infra/gcp/cloud_run.tf": (
        "33ba0e5fdfff34c134ed27bfdc06e11a942fadc01d9ea4be1f1db97038624092"
    )
}
EXPECTED_PINNED_READINESS_FILES = {
    "scripts/gcp_project_readiness_contract.json": (
        "2023140bd0d70b73b73e5da3bb711457583ec075cc75577aa2c90f0102aca61e"
    )
}
EXPECTED_PINNED_RESOURCE_KEYS = frozenset(
    {
        ("google_cloud_run_v2_job", "grant_probe"),
        ("google_cloud_run_v2_job", "maintenance"),
        ("google_cloud_run_v2_job", "migration"),
        ("google_cloud_run_v2_job", "scheduled_maintenance"),
        ("google_cloud_run_v2_job_iam_member", "deployer_grant_probe_job"),
        ("google_cloud_run_v2_job_iam_member", "deployer_maintenance_job"),
        ("google_cloud_run_v2_job_iam_member", "deployer_migration_job"),
        (
            "google_cloud_run_v2_job_iam_member",
            "deployer_scheduled_maintenance_job",
        ),
        ("google_cloud_run_v2_job_iam_member", "scheduler_maintenance_job"),
        ("google_cloud_run_v2_service", "agent"),
        ("google_cloud_run_v2_service_iam_member", "deployer_service_update"),
        ("google_cloud_run_v2_service_iam_member", "public_invoker"),
        ("google_cloud_scheduler_job", "guest_maintenance"),
    }
)
EXPECTED_TERRAFORM_TEST_ABSTRACT = {
    "tests/foundation.tftest.hcl": [
        "foundation_security_contract",
        "foundation_bootstrap_contract",
        "jobs_bootstrap_contract",
        "services_bootstrap_contract",
    ]
}
EXPECTED_TERRAFORM_TEST_SUMMARY = {
    "status": "pass",
    "passed": 4,
    "failed": 0,
    "errored": 0,
    "skipped": 0,
}
EXPECTED_TERRAFORM_LOADABLE_FILES = EXPECTED_TERRAFORM_FILES | frozenset(
    EXPECTED_TERRAFORM_TEST_FILES
)
HCL2_VERSION = "7.3.1"
TERRAFORM_VERSION = "1.15.8"
EXPECTED_TOP_LEVEL_KEYS = {
    "infra/gcp/backend.tf": frozenset({"terraform"}),
    "infra/gcp/cloud_run.tf": frozenset({"locals", "resource"}),
    "infra/gcp/iam.tf": frozenset({"locals", "resource"}),
    "infra/gcp/imports.tf": frozenset({"import", "moved", "removed"}),
    "infra/gcp/main.tf": frozenset({"check", "locals", "resource"}),
    "infra/gcp/outputs.tf": frozenset({"output"}),
    "infra/gcp/state.tf": frozenset({"resource"}),
    "infra/gcp/variables.tf": frozenset({"variable"}),
    "infra/gcp/versions.tf": frozenset({"data", "provider", "terraform"}),
}
EXPECTED_DATA = frozenset({("google_project", "current")})
EXPECTED_LEGACY_ATTRIBUTE_MAPPING = {
    "attribute.repository_id": "assertion.repository_id",
    "google.subject": "assertion.sub",
}
EXPECTED_LIVE_DELIVERY_ROLE_MAPPING = (
    "assertion.event_name == 'pull_request' && assertion.workflow_ref == "
    "'syshin0116/syshin0116.dev/.github/workflows/preview-agent.yml@' + "
    "assertion.ref ? (assertion.job_workflow_ref == "
    "'syshin0116/syshin0116.dev/.github/workflows/agent-image-build.yml@' + "
    "assertion.ref ? 'preview-builder' : assertion.environment == "
    "'Agent Preview' && assertion.job_workflow_ref == "
    "'syshin0116/syshin0116.dev/.github/workflows/agent-release.yml@' + "
    "assertion.ref ? 'preview-deployer' : 'invalid') : assertion.event_name in "
    "['push', 'workflow_dispatch'] && assertion.ref == 'refs/heads/main' && "
    "assertion.workflow_ref == "
    "'syshin0116/syshin0116.dev/.github/workflows/deploy-agent.yml@"
    "refs/heads/main' ? (assertion.job_workflow_ref == "
    "'syshin0116/syshin0116.dev/.github/workflows/agent-image-build.yml@"
    "refs/heads/main' ? 'production-builder' : assertion.environment == "
    "'Agent Production' && assertion.job_workflow_ref == "
    "'syshin0116/syshin0116.dev/.github/workflows/agent-release.yml@"
    "refs/heads/main' ? 'production-deployer' : 'invalid') : 'invalid'"
)
EXPECTED_SOURCE_DELIVERY_ROLE_MAPPING = EXPECTED_LIVE_DELIVERY_ROLE_MAPPING.replace(
    "'Agent Preview'", "'${var.github_preview_environment}'"
).replace("'Agent Production'", "'${var.github_production_environment}'")
EXPECTED_SOURCE_DELIVERY_ATTRIBUTE_MAPPING = {
    "attribute.delivery_role": "${local.delivery_role_mapping}",
    "attribute.repository_id": "assertion.repository_id",
    "attribute.repository_owner_id": "assertion.repository_owner_id",
    "google.subject": "assertion.sub",
}
EXPECTED_LIVE_ATTRIBUTE_MAPPINGS = {
    "github-preview": EXPECTED_LEGACY_ATTRIBUTE_MAPPING,
    "github-production": {
        "attribute.delivery_role": EXPECTED_LIVE_DELIVERY_ROLE_MAPPING,
        "attribute.repository_id": "assertion.repository_id",
        "attribute.repository_owner_id": "assertion.repository_owner_id",
        "google.subject": "assertion.sub",
    },
}
EXPECTED_SOURCE_CONDITIONS = {
    "disabled_preview": "attribute.repository_id == '__legacy_provider_disabled__'",
    "delivery": (
        "attribute.repository_id == '${var.github_repository_id}' && "
        "attribute.repository_owner_id == '${var.github_owner_id}' && "
        "attribute.delivery_role in ['preview-builder', 'preview-deployer', "
        "'production-builder', 'production-deployer']"
    ),
}
EXPECTED_LIVE_CONDITIONS = {
    "github-preview": EXPECTED_SOURCE_CONDITIONS["disabled_preview"],
    "github-production": (
        EXPECTED_SOURCE_CONDITIONS["delivery"]
        .replace("${var.github_repository_id}", "1102380057")
        .replace("${var.github_owner_id}", "99532836")
        .replace("${var.github_preview_environment}", "Agent Preview")
        .replace("${var.github_production_environment}", "Agent Production")
    ),
}
EXPECTED_PROVIDER_IDS = {
    "preview": "github-preview",
    "production": "github-production",
}
EXPECTED_ISSUER = "https://token.actions.githubusercontent.com"
EXPECTED_TERRAFORM_BLOCKS = {
    "infra/gcp/backend.tf": [
        {
            "backend": [
                {
                    "gcs": {
                        "bucket": "festive-ally-503605-v7-tfstate",
                        "prefix": "syshin0116.dev/gcp/foundation",
                    }
                }
            ]
        }
    ],
    "infra/gcp/versions.tf": [
        {
            "required_version": "= 1.15.8",
            "required_providers": [
                {
                    "google": {
                        "source": "hashicorp/google",
                        "version": "7.43.0",
                    }
                }
            ],
        }
    ],
}
EXPECTED_PROVIDER_BLOCKS = [
    {
        "google": {
            "project": "${var.project_id}",
            "region": "${var.region}",
        }
    }
]
EXPECTED_IMPORT_BLOCKS = [
    {
        "to": "${google_artifact_registry_repository.agent}",
        "id": (
            "projects/${var.project_id}/locations/"
            "${local.legacy_artifact_registry_region}/repositories/agent"
        ),
    },
    {
        "to": "${google_storage_bucket.terraform_state}",
        "id": "${var.project_id}-tfstate",
    },
    {
        "to": "${google_service_account.runtime}",
        "id": (
            "projects/${var.project_id}/serviceAccounts/"
            "agent-runtime@${var.project_id}.iam.gserviceaccount.com"
        ),
    },
    {
        "to": '${google_service_account.deployer["preview"]}',
        "id": (
            "projects/${var.project_id}/serviceAccounts/"
            "agent-preview-deployer@${var.project_id}.iam.gserviceaccount.com"
        ),
    },
    {
        "to": '${google_service_account.deployer["production"]}',
        "id": (
            "projects/${var.project_id}/serviceAccounts/"
            "agent-prod-deployer@${var.project_id}.iam.gserviceaccount.com"
        ),
    },
    {
        "to": "${google_iam_workload_identity_pool.github}",
        "id": (
            "projects/${var.project_id}/locations/global/workloadIdentityPools/github"
        ),
    },
    {
        "to": "${google_iam_workload_identity_pool_provider.preview}",
        "id": (
            "projects/${var.project_id}/locations/global/"
            "workloadIdentityPools/github/providers/github-preview"
        ),
    },
    {
        "to": "${google_iam_workload_identity_pool_provider.production}",
        "id": (
            "projects/${var.project_id}/locations/global/"
            "workloadIdentityPools/github/providers/github-production"
        ),
    },
    {
        "for_each": "${local.production_secret_names}",
        "to": "${google_secret_manager_secret.runtime[each.value]}",
        "id": "projects/${var.project_id}/secrets/${each.value}",
    },
]
EXPECTED_MOVED_BLOCKS = [
    {
        "from": (
            "${google_secret_manager_secret.preview_runtime["
            '"agent-preview-openai-api-key"]}'
        ),
        "to": "${google_secret_manager_secret.retired_openai_preview}",
    },
]
EXPECTED_REMOVED_BLOCKS = [
    {
        "from": "${google_secret_manager_secret.retired_openai_preview}",
        "lifecycle": [{"destroy": False}],
    },
]
EXPECTED_VARIABLES = {
    "project_id": {
        "description": "Existing GCP project dedicated to syshin0116.dev.",
        "type": "string",
        "default": "festive-ally-503605-v7",
        "validation": [
            {
                "condition": '${var.project_id == "festive-ally-503605-v7"}',
                "error_message": (
                    "This state and backend are dedicated to festive-ally-503605-v7; "
                    "use a separate root module for another project."
                ),
            }
        ],
    },
    "region": {
        "description": "Active Cloud Run, Scheduler, and Artifact Registry region.",
        "type": "string",
        "default": "asia-southeast1",
        "validation": [
            {
                "condition": '${var.region == "asia-southeast1"}',
                "error_message": (
                    "Active agent delivery is fixed to asia-southeast1; legacy "
                    "us-east4 registries and state storage remain separately pinned."
                ),
            }
        ],
    },
    "github_repository_id": {
        "description": "Immutable numeric GitHub repository ID.",
        "type": "string",
        "default": "1102380057",
        "validation": [
            {
                "condition": '${var.github_repository_id == "1102380057"}',
                "error_message": (
                    "This federation root is dedicated to syshin0116/syshin0116.dev "
                    "repository ID 1102380057."
                ),
            }
        ],
    },
    "github_owner_id": {
        "description": "Immutable numeric GitHub repository owner ID.",
        "type": "string",
        "default": "99532836",
        "validation": [
            {
                "condition": '${var.github_owner_id == "99532836"}',
                "error_message": (
                    "This federation root is dedicated to GitHub owner ID 99532836."
                ),
            }
        ],
    },
    "github_preview_environment": {
        "description": (
            "Exact GitHub environment claim accepted only for the preview "
            "deployer role."
        ),
        "type": "string",
        "default": "Agent Preview",
        "validation": [
            {
                "condition": '${var.github_preview_environment == "Agent Preview"}',
                "error_message": (
                    "The preview deployer role must remain bound to the exact "
                    "Agent Preview environment."
                ),
            }
        ],
    },
    "github_production_environment": {
        "description": (
            "Exact GitHub environment claim accepted only for the production "
            "deployer role."
        ),
        "type": "string",
        "default": "Agent Production",
        "validation": [
            {
                "condition": (
                    '${var.github_production_environment == "Agent Production"}'
                ),
                "error_message": (
                    "The production deployer role must remain bound to the "
                    "exact Agent Production environment."
                ),
            }
        ],
    },
    "agent_delivery_stage": {
        "description": (
            "Explicit bootstrap stage: foundation creates prerequisites, jobs "
            "creates one-shot jobs, services creates the smokeable serving surface, "
            "and launch adds the active reviewed schedule."
        ),
        "type": "string",
        "default": "foundation",
        "validation": [
            {
                "condition": (
                    "${contains([foundation, jobs, services, launch], "
                    "var.agent_delivery_stage)}"
                ),
                "error_message": (
                    "agent_delivery_stage must be exactly foundation, jobs, "
                    "services, or launch."
                ),
            },
            {
                "condition": (
                    '${var.agent_delivery_stage == "foundation" ? '
                    "(var.agent_bootstrap_image == null && "
                    "var.agent_preview_bootstrap_image == null && "
                    "var.agent_secret_versions == null) : "
                    "(var.agent_bootstrap_image != null && "
                    "var.agent_preview_bootstrap_image == null && "
                    "var.agent_secret_versions != null)}"
                ),
                "error_message": (
                    "foundation requires null image/version inputs; every later stage "
                    "requires one immutable production image, no preview image, and "
                    "the complete reviewed production numeric version map."
                ),
            },
        ],
    },
    "agent_bootstrap_image": {
        "description": (
            "Reviewed immutable agent image for the jobs, services, and launch stages; "
            "null during foundation bootstrap, after which CD owns digest changes."
        ),
        "type": "string",
        "default": None,
        "validation": [
            {
                "condition": (
                    "${var.agent_bootstrap_image == None || "
                    'can(regex("^asia-southeast1-docker\\\\.pkg\\\\.dev/'
                    'festive-ally-503605-v7/agent/agent@sha256:[0-9a-f]{64}$", '
                    "var.agent_bootstrap_image))}"
                ),
                "error_message": (
                    "When set, agent_bootstrap_image must be the exact regional "
                    "agent repository path at a lowercase sha256 digest."
                ),
            }
        ],
    },
    "agent_preview_bootstrap_image": {
        "description": (
            "Dormant preview delivery input. It must remain null while "
            "production-only Cloud Run delivery is active."
        ),
        "type": "string",
        "default": None,
        "validation": [
            {
                "condition": "${var.agent_preview_bootstrap_image == null}",
                "error_message": (
                    "agent_preview_bootstrap_image must remain null until preview "
                    "Cloud Run resources are reviewed and restored."
                ),
            }
        ],
    },
    "agent_secret_versions": {
        "description": (
            "Reviewed numeric versions for the five production delivery secrets; "
            "null only during foundation bootstrap. Dormant secret containers stay "
            "versionless here and payloads never enter Terraform."
        ),
        "type": "${map(string)}",
        "default": None,
        "validation": [
            {
                "condition": (
                    "${var.agent_secret_versions == null ? True : "
                    "alltrue([for version in values(var.agent_secret_versions) : "
                    'can(regex("^[1-9][0-9]*$", version))])}'
                ),
                "error_message": (
                    "Every agent_secret_versions value must be a positive numeric "
                    "Secret Manager version; latest and aliases are forbidden."
                ),
            },
            {
                "condition": (
                    "${var.agent_secret_versions == null ? True : "
                    "toset(keys(var.agent_secret_versions)) == toset(["
                    "agent-auth-secret, agent-database-url, "
                    "agent-migration-database-url, langsmith-api-key, "
                    "openai-api-key])}"
                ),
                "error_message": (
                    "agent_secret_versions must contain exactly auth, runtime DB, "
                    "migration DB, LangSmith, and OpenAI production secret IDs."
                ),
            },
        ],
    },
}
FORBIDDEN_EXECUTION_KEYS = frozenset(
    {"connection", "local-exec", "provisioner", "remote-exec"}
)
EXPECTED_DATA_CONFIGS = {
    ("google_project", "current"): {
        "project_id": "${var.project_id}",
    }
}
EXPECTED_RESOURCE_CONFIGS = {
    ("google_project_service", "required"): {
        "for_each": "${local.required_services}",
        "project": "${var.project_id}",
        "service": "${each.value}",
        "disable_on_destroy": False,
    },
    ("google_artifact_registry_repository", "agent"): {
        "project": "${var.project_id}",
        "location": "${local.legacy_artifact_registry_region}",
        "repository_id": "agent",
        "description": "Production agent images with bounded rollback retention",
        "format": "DOCKER",
        "docker_config": [{"immutable_tags": False}],
        "cleanup_policy_dry_run": False,
        "cleanup_policies": [
            {
                "id": "delete-after-90-days",
                "action": "DELETE",
                "condition": [{"tag_state": "ANY", "older_than": "7776000s"}],
            },
            {
                "id": "keep-last-30",
                "action": "KEEP",
                "most_recent_versions": [{"keep_count": 30}],
            },
        ],
        "depends_on": ["${google_project_service.required}"],
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_artifact_registry_repository", "preview_agent"): {
        "project": "${var.project_id}",
        "location": "${local.legacy_artifact_registry_region}",
        "repository_id": "agent-preview",
        "description": "Preview agent images with short-lived retention",
        "format": "DOCKER",
        "docker_config": [{"immutable_tags": False}],
        "cleanup_policy_dry_run": False,
        "cleanup_policies": [
            {
                "id": "delete-after-14-days",
                "action": "DELETE",
                "condition": [{"tag_state": "ANY", "older_than": "1209600s"}],
            },
            {
                "id": "keep-last-20",
                "action": "KEEP",
                "most_recent_versions": [{"keep_count": 20}],
            },
        ],
        "depends_on": ["${google_project_service.required}"],
        "lifecycle": [
            {
                "ignore_changes": ["${docker_config}"],
                "prevent_destroy": True,
            }
        ],
    },
    ("google_artifact_registry_repository", "active_agent"): {
        "project": "${var.project_id}",
        "location": "${var.region}",
        "repository_id": "agent",
        "description": (
            "Singapore production agent images with bounded rollback retention"
        ),
        "format": "DOCKER",
        "docker_config": [{"immutable_tags": False}],
        "cleanup_policy_dry_run": False,
        "cleanup_policies": [
            {
                "id": "delete-after-90-days",
                "action": "DELETE",
                "condition": [{"tag_state": "ANY", "older_than": "7776000s"}],
            },
            {
                "id": "keep-last-30",
                "action": "KEEP",
                "most_recent_versions": [{"keep_count": 30}],
            },
        ],
        "depends_on": ["${google_project_service.required}"],
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_artifact_registry_repository", "active_preview_agent"): {
        "project": "${var.project_id}",
        "location": "${var.region}",
        "repository_id": "agent-preview",
        "description": (
            "Singapore preview image foundation retained dormant by delivery gates"
        ),
        "format": "DOCKER",
        "docker_config": [{"immutable_tags": False}],
        "cleanup_policy_dry_run": False,
        "cleanup_policies": [
            {
                "id": "delete-after-14-days",
                "action": "DELETE",
                "condition": [{"tag_state": "ANY", "older_than": "1209600s"}],
            },
            {
                "id": "keep-last-20",
                "action": "KEEP",
                "most_recent_versions": [{"keep_count": 20}],
            },
        ],
        "depends_on": ["${google_project_service.required}"],
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_service_account", "runtime"): {
        "project": "${var.project_id}",
        "account_id": "agent-runtime",
        "display_name": "Cloud Run production agent runtime",
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_service_account", "preview_runtime"): {
        "project": "${var.project_id}",
        "account_id": "agent-preview-runtime",
        "display_name": "Cloud Run preview agent runtime",
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_service_account", "maintenance_scheduler"): {
        "project": "${var.project_id}",
        "account_id": "agent-maintenance-scheduler",
        "display_name": "Cloud Scheduler production maintenance invoker",
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_service_account", "deployer"): {
        "for_each": "${local.deployers}",
        "project": "${var.project_id}",
        "account_id": "${each.value.account_id}",
        "display_name": "${each.value.display_name}",
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_service_account", "builder"): {
        "project": "${var.project_id}",
        "account_id": "agent-image-builder",
        "display_name": "GitHub production agent image builder",
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_service_account", "preview_builder"): {
        "project": "${var.project_id}",
        "account_id": "agent-preview-image-builder",
        "display_name": "GitHub preview agent image builder",
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_service_account", "migrator"): {
        "for_each": "${local.migrators}",
        "project": "${var.project_id}",
        "account_id": "${each.value.account_id}",
        "display_name": "${each.value.display_name}",
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_project_iam_custom_role", "cloud_run_delivery"): {
        "project": "${var.project_id}",
        "role_id": "cloudRunAgentDelivery",
        "title": "Cloud Run agent delivery",
        "description": (
            "Update and verify only existing agent services and jobs, then run jobs "
            "without overrides."
        ),
        "stage": "GA",
        "permissions": [
            "run.jobs.get",
            "run.jobs.run",
            "run.jobs.update",
            "run.operations.get",
            "run.revisions.get",
            "run.services.get",
            "run.services.update",
        ],
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_project_iam_custom_role", "scheduled_maintenance_delivery"): {
        "project": "${var.project_id}",
        "role_id": "cloudRunScheduledMaintenanceDelivery",
        "title": "Cloud Run scheduled maintenance delivery",
        "description": (
            "Update and verify only the existing scheduled maintenance job; "
            "execution remains exclusive to Cloud Scheduler."
        ),
        "stage": "GA",
        "permissions": [
            "run.jobs.get",
            "run.jobs.update",
            "run.operations.get",
        ],
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_secret_manager_secret", "runtime"): {
        "for_each": "${local.production_secret_names}",
        "project": "${var.project_id}",
        "secret_id": "${each.value}",
        "replication": [{"auto": [{}]}],
        "depends_on": ["${google_project_service.required}"],
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_secret_manager_secret", "preview_runtime"): {
        "for_each": "${local.preview_secret_names}",
        "project": "${var.project_id}",
        "secret_id": "${each.value}",
        "replication": [{"auto": [{}]}],
        "depends_on": ["${google_project_service.required}"],
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_secret_manager_secret", "migration"): {
        "for_each": "${local.migration_secret_names}",
        "project": "${var.project_id}",
        "secret_id": "${each.value}",
        "replication": [{"auto": [{}]}],
        "depends_on": ["${google_project_service.required}"],
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_iam_workload_identity_pool", "github"): {
        "project": "${var.project_id}",
        "workload_identity_pool_id": "github",
        "display_name": "GitHub Actions",
        "description": "GitHub Actions federation; no service-account keys.",
        "disabled": False,
        "depends_on": ["${google_project_service.required}"],
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_iam_workload_identity_pool_provider", "preview"): {
        "project": "${var.project_id}",
        "workload_identity_pool_id": (
            "${google_iam_workload_identity_pool.github.workload_identity_pool_id}"
        ),
        "workload_identity_pool_provider_id": "github-preview",
        "display_name": "Legacy GitHub Preview (disabled)",
        "disabled": True,
        "attribute_mapping": EXPECTED_LEGACY_ATTRIBUTE_MAPPING,
        "attribute_condition": ("${local.disabled_preview_wif_attribute_condition}"),
        "oidc": [{"issuer_uri": EXPECTED_ISSUER}],
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_iam_workload_identity_pool_provider", "production"): {
        "project": "${var.project_id}",
        "workload_identity_pool_id": (
            "${google_iam_workload_identity_pool.github.workload_identity_pool_id}"
        ),
        "workload_identity_pool_provider_id": "github-production",
        "display_name": "GitHub Agent Delivery",
        "disabled": False,
        "attribute_mapping": EXPECTED_SOURCE_DELIVERY_ATTRIBUTE_MAPPING,
        "attribute_condition": "${local.delivery_wif_attribute_condition}",
        "oidc": [{"issuer_uri": EXPECTED_ISSUER}],
        "lifecycle": [{"prevent_destroy": True}],
    },
    ("google_service_account_iam_member", "deployer_uses_runtime"): {
        "for_each": "${local.deployer_service_accounts}",
        "service_account_id": "${local.runtime_service_account_ids[each.key]}",
        "role": "roles/iam.serviceAccountUser",
        "member": "serviceAccount:${each.value}",
    },
    ("google_service_account_iam_member", "deployer_uses_migrator"): {
        "for_each": "${local.deployer_service_accounts}",
        "service_account_id": "${local.migrator_service_account_ids[each.key]}",
        "role": "roles/iam.serviceAccountUser",
        "member": "serviceAccount:${each.value}",
    },
    ("google_secret_manager_secret_iam_member", "runtime_accessor"): {
        "for_each": "${local.production_runtime_secret_names}",
        "project": "${var.project_id}",
        "secret_id": "${google_secret_manager_secret.runtime[each.key].secret_id}",
        "role": "roles/secretmanager.secretAccessor",
        "member": "serviceAccount:${local.runtime_service_accounts.production}",
    },
    ("google_secret_manager_secret_iam_member", "preview_runtime_accessor"): {
        "for_each": "${google_secret_manager_secret.preview_runtime}",
        "project": "${var.project_id}",
        "secret_id": "${each.value.secret_id}",
        "role": "roles/secretmanager.secretAccessor",
        "member": "serviceAccount:${local.runtime_service_accounts.preview}",
    },
    ("google_secret_manager_secret_iam_member", "migrator_accessor"): {
        "for_each": "${google_secret_manager_secret.migration}",
        "project": "${var.project_id}",
        "secret_id": "${each.value.secret_id}",
        "role": "roles/secretmanager.secretAccessor",
        "member": "serviceAccount:${local.migrator_service_accounts[each.key]}",
    },
    ("google_service_account_iam_member", "github_preview"): {
        "service_account_id": ('${google_service_account.deployer["preview"].name}'),
        "role": "roles/iam.workloadIdentityUser",
        "member": "${local.github_delivery_role_principals.preview_deployer}",
    },
    ("google_service_account_iam_member", "github_production"): {
        "service_account_id": ('${google_service_account.deployer["production"].name}'),
        "role": "roles/iam.workloadIdentityUser",
        "member": "${local.github_delivery_role_principals.production_deployer}",
    },
    ("google_service_account_iam_member", "github_builder"): {
        "service_account_id": "${google_service_account.builder.name}",
        "role": "roles/iam.workloadIdentityUser",
        "member": "${local.github_delivery_role_principals.production_builder}",
    },
    ("google_service_account_iam_member", "github_preview_builder"): {
        "service_account_id": "${google_service_account.preview_builder.name}",
        "role": "roles/iam.workloadIdentityUser",
        "member": "${local.github_delivery_role_principals.preview_builder}",
    },
    ("google_artifact_registry_repository_iam_member", "builder_writer"): {
        "project": "${var.project_id}",
        "location": "${local.legacy_artifact_registry_region}",
        "repository": "${google_artifact_registry_repository.agent.repository_id}",
        "role": "roles/artifactregistry.writer",
        "member": "serviceAccount:${google_service_account.builder.email}",
    },
    ("google_artifact_registry_repository_iam_member", "preview_builder_writer"): {
        "project": "${var.project_id}",
        "location": "${local.legacy_artifact_registry_region}",
        "repository": (
            "${google_artifact_registry_repository.preview_agent.repository_id}"
        ),
        "role": "roles/artifactregistry.writer",
        "member": "serviceAccount:${google_service_account.preview_builder.email}",
    },
    ("google_artifact_registry_repository_iam_member", "deployer_reader"): {
        "for_each": {
            "production": "${local.deployer_service_accounts.production}",
        },
        "project": "${var.project_id}",
        "location": "${local.legacy_artifact_registry_region}",
        "repository": "${google_artifact_registry_repository.agent.repository_id}",
        "role": "roles/artifactregistry.reader",
        "member": "serviceAccount:${each.value}",
    },
    ("google_artifact_registry_repository_iam_member", "preview_deployer_reader"): {
        "project": "${var.project_id}",
        "location": "${local.legacy_artifact_registry_region}",
        "repository": (
            "${google_artifact_registry_repository.preview_agent.repository_id}"
        ),
        "role": "roles/artifactregistry.reader",
        "member": "serviceAccount:${local.deployer_service_accounts.preview}",
    },
    ("google_artifact_registry_repository_iam_member", "cloud_run_reader"): {
        "project": "${var.project_id}",
        "location": "${local.legacy_artifact_registry_region}",
        "repository": "${google_artifact_registry_repository.agent.repository_id}",
        "role": "roles/artifactregistry.reader",
        "member": "${local.cloud_run_image_pull_principal}",
        "depends_on": ["${google_project_service.required}"],
    },
    ("google_artifact_registry_repository_iam_member", "preview_cloud_run_reader"): {
        "project": "${var.project_id}",
        "location": "${local.legacy_artifact_registry_region}",
        "repository": (
            "${google_artifact_registry_repository.preview_agent.repository_id}"
        ),
        "role": "roles/artifactregistry.reader",
        "member": "${local.cloud_run_image_pull_principal}",
        "depends_on": ["${google_project_service.required}"],
    },
    ("google_artifact_registry_repository_iam_member", "active_builder_writer"): {
        "project": "${var.project_id}",
        "location": "${var.region}",
        "repository": (
            "${google_artifact_registry_repository.active_agent.repository_id}"
        ),
        "role": "roles/artifactregistry.writer",
        "member": "serviceAccount:${google_service_account.builder.email}",
    },
    (
        "google_artifact_registry_repository_iam_member",
        "active_preview_builder_writer",
    ): {
        "project": "${var.project_id}",
        "location": "${var.region}",
        "repository": (
            "${google_artifact_registry_repository.active_preview_agent.repository_id}"
        ),
        "role": "roles/artifactregistry.writer",
        "member": "serviceAccount:${google_service_account.preview_builder.email}",
    },
    ("google_artifact_registry_repository_iam_member", "active_deployer_reader"): {
        "for_each": {
            "production": "${local.deployer_service_accounts.production}",
        },
        "project": "${var.project_id}",
        "location": "${var.region}",
        "repository": (
            "${google_artifact_registry_repository.active_agent.repository_id}"
        ),
        "role": "roles/artifactregistry.reader",
        "member": "serviceAccount:${each.value}",
    },
    (
        "google_artifact_registry_repository_iam_member",
        "active_preview_deployer_reader",
    ): {
        "project": "${var.project_id}",
        "location": "${var.region}",
        "repository": (
            "${google_artifact_registry_repository.active_preview_agent.repository_id}"
        ),
        "role": "roles/artifactregistry.reader",
        "member": "serviceAccount:${local.deployer_service_accounts.preview}",
    },
    ("google_artifact_registry_repository_iam_member", "active_cloud_run_reader"): {
        "project": "${var.project_id}",
        "location": "${var.region}",
        "repository": (
            "${google_artifact_registry_repository.active_agent.repository_id}"
        ),
        "role": "roles/artifactregistry.reader",
        "member": "${local.cloud_run_image_pull_principal}",
        "depends_on": ["${google_project_service.required}"],
    },
    (
        "google_artifact_registry_repository_iam_member",
        "active_preview_cloud_run_reader",
    ): {
        "project": "${var.project_id}",
        "location": "${var.region}",
        "repository": (
            "${google_artifact_registry_repository.active_preview_agent.repository_id}"
        ),
        "role": "roles/artifactregistry.reader",
        "member": "${local.cloud_run_image_pull_principal}",
        "depends_on": ["${google_project_service.required}"],
    },
    ("google_storage_bucket", "terraform_state"): {
        "name": "${var.project_id}-tfstate",
        "project": "${var.project_id}",
        "location": "${local.legacy_artifact_registry_region}",
        "force_destroy": False,
        "public_access_prevention": "enforced",
        "uniform_bucket_level_access": True,
        "versioning": [{"enabled": True}],
        "soft_delete_policy": [{"retention_duration_seconds": 2592000}],
        "lifecycle": [{"prevent_destroy": True}],
    },
}
EXPECTED_LOCALS_BY_FILE = {
    "infra/gcp/main.tf": [
        {
            "legacy_artifact_registry_region": "us-east4",
            "disabled_preview_wif_attribute_condition": (
                EXPECTED_SOURCE_CONDITIONS["disabled_preview"]
            ),
            "delivery_role_mapping": EXPECTED_SOURCE_DELIVERY_ROLE_MAPPING,
            "delivery_wif_attribute_condition": EXPECTED_SOURCE_CONDITIONS["delivery"],
            "required_services": (
                "${toset([artifactregistry.googleapis.com, "
                "cloudscheduler.googleapis.com, "
                "cloudresourcemanager.googleapis.com, iam.googleapis.com, "
                "iamcredentials.googleapis.com, run.googleapis.com, "
                "secretmanager.googleapis.com, storage.googleapis.com, "
                "sts.googleapis.com])}"
            ),
            "production_secret_names": (
                "${toset([agent-auth-secret, agent-database-url, anthropic-api-key, "
                "langsmith-api-key, openai-api-key])}"
            ),
            "production_runtime_secret_names": (
                "${toset([agent-auth-secret, agent-database-url, "
                "langsmith-api-key, openai-api-key])}"
            ),
            "preview_secret_names": (
                "${toset([agent-preview-anthropic-api-key, "
                "agent-preview-auth-secret, agent-preview-database-url, "
                "agent-preview-langsmith-api-key])}"
            ),
            "migration_secret_names": {
                "preview": "agent-preview-migration-database-url",
                "production": "agent-migration-database-url",
            },
            "required_agent_secret_names": (
                "${setunion(local.production_secret_names, "
                "local.preview_secret_names, "
                "toset(values(local.migration_secret_names)))}"
            ),
            "required_production_delivery_secret_names": (
                "${toset([agent-auth-secret, agent-database-url, "
                "agent-migration-database-url, langsmith-api-key, "
                "openai-api-key])}"
            ),
            "deployers": {
                "preview": {
                    "account_id": "agent-preview-deployer",
                    "display_name": "GitHub preview deployer",
                },
                "production": {
                    "account_id": "agent-prod-deployer",
                    "display_name": "GitHub production deployer",
                },
            },
            "migrators": {
                "preview": {
                    "account_id": "agent-preview-migrator",
                    "display_name": "Cloud Run preview migration identity",
                },
                "production": {
                    "account_id": "agent-prod-migrator",
                    "display_name": "Cloud Run production migration identity",
                },
            },
        }
    ],
    "infra/gcp/iam.tf": [
        {
            "runtime_service_account_ids": {
                "preview": "${google_service_account.preview_runtime.name}",
                "production": "${google_service_account.runtime.name}",
            },
            "runtime_service_accounts": {
                "preview": "${google_service_account.preview_runtime.email}",
                "production": "${google_service_account.runtime.email}",
            },
            "deployer_service_accounts": (
                "${{for name , account in google_service_account.deployer : "
                "name => account.email}}"
            ),
            "migrator_service_account_ids": (
                "${{for name , account in google_service_account.migrator : "
                "name => account.name}}"
            ),
            "migrator_service_accounts": (
                "${{for name , account in google_service_account.migrator : "
                "name => account.email}}"
            ),
            "github_delivery_role_principals": {
                "preview_builder": (
                    "principalSet://iam.googleapis.com/projects/"
                    "${data.google_project.current.number}/locations/global/"
                    "workloadIdentityPools/"
                    "${google_iam_workload_identity_pool.github."
                    "workload_identity_pool_id}/attribute.delivery_role/"
                    "preview-builder"
                ),
                "preview_deployer": (
                    "principalSet://iam.googleapis.com/projects/"
                    "${data.google_project.current.number}/locations/global/"
                    "workloadIdentityPools/"
                    "${google_iam_workload_identity_pool.github."
                    "workload_identity_pool_id}/attribute.delivery_role/"
                    "preview-deployer"
                ),
                "production_builder": (
                    "principalSet://iam.googleapis.com/projects/"
                    "${data.google_project.current.number}/locations/global/"
                    "workloadIdentityPools/"
                    "${google_iam_workload_identity_pool.github."
                    "workload_identity_pool_id}/attribute.delivery_role/"
                    "production-builder"
                ),
                "production_deployer": (
                    "principalSet://iam.googleapis.com/projects/"
                    "${data.google_project.current.number}/locations/global/"
                    "workloadIdentityPools/"
                    "${google_iam_workload_identity_pool.github."
                    "workload_identity_pool_id}/attribute.delivery_role/"
                    "production-deployer"
                ),
            },
            "cloud_run_image_pull_principal": (
                "serviceAccount:service-${data.google_project.current.number}@"
                "serverless-robot-prod.iam.gserviceaccount.com"
            ),
        }
    ],
}
EXPECTED_CHECK_BLOCKS = [
    {
        "runtime_environments_are_disjoint": {
            "assert": [
                {
                    "condition": (
                        "${length(setintersection(local.production_secret_names, "
                        "local.preview_secret_names)) == 0}"
                    ),
                    "error_message": (
                        "Preview and production Secret Manager resource names "
                        "must be disjoint."
                    ),
                }
            ]
        }
    },
    {
        "agent_delivery_stage_inputs": {
            "assert": [
                {
                    "condition": (
                        '${var.agent_delivery_stage == "foundation" ? '
                        "(var.agent_bootstrap_image == null && "
                        "var.agent_preview_bootstrap_image == null && "
                        "var.agent_secret_versions == null) : "
                        "(var.agent_bootstrap_image != null && "
                        "var.agent_preview_bootstrap_image == null && "
                        "var.agent_secret_versions != null)}"
                    ),
                    "error_message": (
                        "foundation requires null image/version inputs; every later "
                        "stage requires one immutable production image, no preview "
                        "image, and the complete reviewed production numeric version map."
                    ),
                }
            ]
        }
    },
    {
        "agent_secret_version_inventory": {
            "assert": [
                {
                    "condition": (
                        '${var.agent_delivery_stage == "foundation" ? True : '
                        "(var.agent_secret_versions != null && "
                        "toset(keys(var.agent_secret_versions)) == "
                        "local.required_production_delivery_secret_names)}"
                    ),
                    "error_message": (
                        "every non-foundation stage requires exactly the five production "
                        "delivery secret IDs, with no missing or extra version keys."
                    ),
                }
            ]
        }
    },
]
EXPECTED_OUTPUTS = {
    "artifact_registry_repository": {
        "value": "${google_artifact_registry_repository.active_agent.name}",
    },
    "preview_artifact_registry_repository": {
        "value": "${google_artifact_registry_repository.active_preview_agent.name}",
    },
    "legacy_artifact_registry_repository": {
        "value": "${google_artifact_registry_repository.agent.name}",
    },
    "legacy_preview_artifact_registry_repository": {
        "value": "${google_artifact_registry_repository.preview_agent.name}",
    },
    "runtime_service_account": {
        "description": (
            "Production runtime service account; retained for compatibility."
        ),
        "value": "${google_service_account.runtime.email}",
    },
    "production_runtime_service_account": {
        "value": "${google_service_account.runtime.email}",
    },
    "preview_runtime_service_account": {
        "value": "${google_service_account.preview_runtime.email}",
    },
    "preview_deployer_service_account": {
        "value": '${google_service_account.deployer["preview"].email}',
    },
    "production_deployer_service_account": {
        "value": '${google_service_account.deployer["production"].email}',
    },
    "builder_service_account": {
        "value": "${google_service_account.builder.email}",
    },
    "preview_builder_service_account": {
        "value": "${google_service_account.preview_builder.email}",
    },
    "preview_migrator_service_account": {
        "value": '${google_service_account.migrator["preview"].email}',
    },
    "production_migrator_service_account": {
        "value": '${google_service_account.migrator["production"].email}',
    },
    "preview_cloud_run_service": {
        "value": '${try(google_cloud_run_v2_service.agent["preview"].name, null)}',
    },
    "production_cloud_run_service": {
        "value": '${try(google_cloud_run_v2_service.agent["production"].name, null)}',
    },
    "preview_migration_job": {
        "value": '${try(google_cloud_run_v2_job.migration["preview"].name, null)}',
    },
    "production_migration_job": {
        "value": '${try(google_cloud_run_v2_job.migration["production"].name, null)}',
    },
    "preview_grant_probe_job": {
        "value": '${try(google_cloud_run_v2_job.grant_probe["preview"].name, null)}',
    },
    "production_grant_probe_job": {
        "value": '${try(google_cloud_run_v2_job.grant_probe["production"].name, null)}',
    },
    "preview_maintenance_job": {
        "value": '${try(google_cloud_run_v2_job.maintenance["preview"].name, null)}',
    },
    "production_maintenance_job": {
        "value": '${try(google_cloud_run_v2_job.maintenance["production"].name, null)}',
    },
    "maintenance_scheduler_service_account": {
        "value": "${google_service_account.maintenance_scheduler.email}",
    },
    "production_guest_maintenance_schedule": {
        "value": (
            '${try(google_cloud_scheduler_job.guest_maintenance["production"].name, '
            "null)}"
        ),
    },
    "preview_workload_identity_provider": {
        "description": (
            "Retained legacy provider; managed disabled and not trusted by any "
            "service account."
        ),
        "value": "${google_iam_workload_identity_pool_provider.preview.name}",
    },
    "production_workload_identity_provider": {
        "description": (
            "Canonical active provider for all four phase-specific delivery roles."
        ),
        "value": "${google_iam_workload_identity_pool_provider.production.name}",
    },
    "delivery_workload_identity_provider": {
        "description": (
            "Canonical active provider for preview/production builder/deployer roles."
        ),
        "value": "${google_iam_workload_identity_pool_provider.production.name}",
    },
    "terraform_state_bucket": {
        "value": "${google_storage_bucket.terraform_state.name}",
    },
}

PUBLIC_MEMBERS = frozenset({"allAuthenticatedUsers", "allUsers"})
REVIEW_REQUIRED_MEMBER_PREFIXES = (
    "group:",
    "domain:",
    "deleted:group:",
    "deleted:domain:",
    "principal:",
    "principalSet:",
)
OFFLINE_ADMIN_EVIDENCE_SCHEMA = "syshin0116.gcp-admin-iam-evidence/v1"
OFFLINE_ADMIN_EVIDENCE_MAX_AGE = timedelta(hours=24)
OFFLINE_ADMIN_EVIDENCE_MAX_BYTES = 10 * 1024 * 1024
OFFLINE_ADMIN_EVIDENCE_SAFE_PERMISSION_VERBS = frozenset(
    {
        "get",
        "getIamPolicy",
        "list",
        "listEffectiveTags",
        "listTagBindings",
        "testIamPermissions",
    }
)
OFFLINE_ADMIN_EVIDENCE_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
FORBIDDEN_INHERITED_MEMBER_PREFIXES = (
    "group:",
    "domain:",
    "deleted:group:",
    "deleted:domain:",
)
RESOURCE_MANAGER_SERVICE_ACCOUNT_SET = re.compile(
    r"^principalSet://cloudresourcemanager\.googleapis\.com/"
    r"(?:projects|folders|organizations)/[^/]+/type/ServiceAccount$"
)


class ContractError(ValueError):
    """The foundation contract is incomplete or unsafe."""


def _fail(message: str) -> None:
    raise ContractError(message)


def _json_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{label} must be a JSON object")
    return value


def _json_array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{label} must be a JSON array")
    return value


def _read_stdin_json() -> dict[str, Any]:
    try:
        return _json_object(json.load(sys.stdin), "input")
    except (json.JSONDecodeError, OSError) as exc:
        raise ContractError(f"input must be valid JSON: {exc}") from exc


def _read_stdin_json_lines() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(sys.stdin, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(
                f"Terraform test output line {line_number} must be valid JSON: {exc}"
            ) from exc
        records.append(
            _json_object(parsed, f"Terraform test output line {line_number}")
        )
    if not records:
        _fail("Terraform test output must contain JSON event records")
    return records


def _tracked_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "infra/gcp"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        _fail(f"cannot enumerate tracked Terraform files: {detail}")
    try:
        return [raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw]
    except UnicodeDecodeError as exc:
        raise ContractError("tracked infra/gcp paths must be UTF-8") from exc


def _is_terraform_loadable_name(name: str) -> bool:
    return name.endswith(
        (
            ".tf",
            ".tf.json",
            ".tfvars",
            ".tfvars.json",
            ".tftest.hcl",
            ".tftest.json",
            ".tfmock.hcl",
            ".tfmock.json",
        )
    )


def _file_kind(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "regular"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISBLK(mode):
        return "block-device"
    if stat.S_ISCHR(mode):
        return "character-device"
    return "non-regular"


def _require_real_directory(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ContractError(f"cannot inspect {label}: {exc}") from exc
    kind = _file_kind(mode)
    if kind != "directory":
        _fail(f"{label} must be a real directory; got={kind}")


def _on_disk_terraform_candidates(
    repo_root: Path,
) -> tuple[dict[str, str], frozenset[str]]:
    infra_dir = repo_root / "infra"
    _require_real_directory(infra_dir, "infra")
    terraform_dir = infra_dir / "gcp"
    _require_real_directory(terraform_dir, "infra/gcp")

    candidates: dict[str, str] = {}
    terraform_internal_dirs: set[str] = set()

    def visit(directory: Path, relative_directory: Path) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            relative = (Path("infra/gcp") / relative_directory).as_posix()
            raise ContractError(
                f"cannot enumerate Terraform candidate directory {relative}: {exc}"
            ) from exc

        for entry in entries:
            relative = relative_directory / entry.name
            repo_relative = (Path("infra/gcp") / relative).as_posix()
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise ContractError(
                    f"cannot inspect Terraform candidate path {repo_relative}: {exc}"
                ) from exc

            if entry.name == ".terraform":
                kind = _file_kind(mode)
                if kind != "directory":
                    _fail(f"{repo_relative} must be a real directory; got={kind}")
                terraform_internal_dirs.add(repo_relative)
                continue

            is_candidate = _is_terraform_loadable_name(entry.name)
            if is_candidate:
                candidates[repo_relative] = _file_kind(mode)

            if stat.S_ISDIR(mode) and not is_candidate:
                visit(Path(entry.path), relative)

    visit(terraform_dir, Path())
    return candidates, frozenset(terraform_internal_dirs)


def _git_path_is_ignored(repo_root: Path, relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", relative_path],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    detail = result.stderr.decode(errors="replace").strip()
    _fail(f"cannot check whether {relative_path} is gitignored: {detail}")


def validate_disk_inventory(repo_root: Path) -> list[str]:
    candidates, terraform_internal_dirs = _on_disk_terraform_candidates(repo_root)
    actual_files = frozenset(candidates)
    expected_files = EXPECTED_TERRAFORM_LOADABLE_FILES
    irregular = sorted(
        f"{path} ({kind})" for path, kind in candidates.items() if kind != "regular"
    )
    missing = sorted(expected_files - actual_files)
    unexpected = sorted(
        f"{path} ({candidates[path]})" for path in actual_files - expected_files
    )
    if missing or unexpected or irregular:
        _fail(
            "on-disk Terraform loadable inventory mismatch; "
            f"missing={missing}, unexpected={unexpected}, irregular={irregular}"
        )

    tracked_paths = _tracked_paths(repo_root)
    tracked_internal = sorted(
        path for path in tracked_paths if ".terraform" in Path(path).parts
    )
    if tracked_internal:
        _fail(f"tracked .terraform paths are forbidden; paths={tracked_internal}")
    for internal_dir in sorted(terraform_internal_dirs):
        if not _git_path_is_ignored(repo_root, internal_dir):
            _fail(f"{internal_dir} must be gitignored and untracked")

    tracked_loadable = frozenset(
        path for path in tracked_paths if _is_terraform_loadable_name(Path(path).name)
    )
    if tracked_loadable != expected_files:
        missing = sorted(expected_files - tracked_loadable)
        unexpected = sorted(tracked_loadable - expected_files)
        _fail(
            "tracked Terraform loadable inventory mismatch; "
            f"missing={missing}, unexpected={unexpected}"
        )
    return tracked_paths


def _load_hcl_documents(
    repo_root: Path,
    tracked_tf: Iterable[str],
) -> dict[str, dict[str, Any]]:
    try:
        hcl2 = importlib.import_module("hcl2")
        installed_version = importlib.metadata.version("python-hcl2")
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        raise ContractError(
            f"parser-backed Terraform verification requires python-hcl2=={HCL2_VERSION}"
        ) from exc
    if installed_version != HCL2_VERSION:
        _fail(
            "python-hcl2 version mismatch; "
            f"expected={HCL2_VERSION}, got={installed_version}"
        )

    documents: dict[str, dict[str, Any]] = {}
    for relative_path in sorted(tracked_tf):
        path = repo_root / relative_path
        if path.is_symlink():
            _fail(f"tracked Terraform file must not be a symlink: {relative_path}")
        try:
            source = path.read_text(encoding="utf-8")
            parsed = hcl2.loads(source)
        except OSError as exc:
            raise ContractError(
                f"cannot read tracked Terraform file {relative_path}: {exc}"
            ) from exc
        except Exception as exc:
            raise ContractError(
                f"cannot parse tracked Terraform file {relative_path}: {exc}"
            ) from exc
        documents[relative_path] = _json_object(
            parsed,
            f"parsed Terraform file {relative_path}",
        )
    return documents


def _two_label_blocks(
    documents: Mapping[str, Mapping[str, Any]],
    block_kind: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    blocks: dict[tuple[str, str], dict[str, Any]] = {}
    for relative_path, document in documents.items():
        raw_blocks = _json_array(
            document.get(block_kind, []),
            f"{relative_path}.{block_kind}",
        )
        for raw_block in raw_blocks:
            block = _json_object(raw_block, f"{relative_path}.{block_kind} block")
            if len(block) != 1:
                _fail(f"{relative_path} has malformed {block_kind} block labels")
            block_type, raw_names = next(iter(block.items()))
            names = _json_object(
                raw_names,
                f"{relative_path}.{block_kind}.{block_type}",
            )
            for block_name, raw_body in names.items():
                key = (block_type, block_name)
                if key in blocks:
                    _fail(
                        f"duplicate Terraform {block_kind} declaration: "
                        f"{block_type}.{block_name}"
                    )
                blocks[key] = _json_object(
                    raw_body,
                    f"{relative_path}.{block_kind}.{block_type}.{block_name}",
                )
    return blocks


def _single_label_blocks(
    documents: Mapping[str, Mapping[str, Any]],
    block_kind: str,
) -> dict[str, dict[str, Any]]:
    blocks: dict[str, dict[str, Any]] = {}
    for relative_path, document in documents.items():
        raw_blocks = _json_array(
            document.get(block_kind, []),
            f"{relative_path}.{block_kind}",
        )
        for raw_block in raw_blocks:
            block = _json_object(raw_block, f"{relative_path}.{block_kind} block")
            if len(block) != 1:
                _fail(f"{relative_path} has malformed {block_kind} block labels")
            block_name, raw_body = next(iter(block.items()))
            if block_name in blocks:
                _fail(f"duplicate Terraform {block_kind} declaration: {block_name}")
            blocks[block_name] = _json_object(
                raw_body,
                f"{relative_path}.{block_kind}.{block_name}",
            )
    return blocks


def _all_blocks(
    documents: Mapping[str, Mapping[str, Any]],
    block_kind: str,
) -> list[Any]:
    blocks: list[Any] = []
    for relative_path, document in documents.items():
        blocks.extend(
            _json_array(
                document.get(block_kind, []),
                f"{relative_path}.{block_kind}",
            )
        )
    return blocks


def _reject_execution_escape(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_EXECUTION_KEYS:
                _fail(
                    f"Terraform executable escape hatch {key!r} is forbidden at {path}"
                )
            _reject_execution_escape(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_execution_escape(child, f"{path}[{index}]")


def _validate_variables(variables: Mapping[str, Mapping[str, Any]]) -> None:
    if set(variables) != set(EXPECTED_VARIABLES):
        missing = sorted(set(EXPECTED_VARIABLES) - set(variables))
        unexpected = sorted(set(variables) - set(EXPECTED_VARIABLES))
        _fail(
            "Terraform variable inventory must exactly match the reviewed "
            f"contract; missing={missing}, unexpected={unexpected}"
        )

    for variable_name, expected in EXPECTED_VARIABLES.items():
        if variables[variable_name] != expected:
            _fail(f"variable {variable_name} body must exactly match")


def _validate_test_file_contract(
    repo_root: Path,
    tracked_paths: Iterable[str],
) -> None:
    tracked_test_files = frozenset(
        path for path in tracked_paths if path.endswith((".tftest.hcl", ".tftest.json"))
    )
    expected_test_files = frozenset(EXPECTED_TERRAFORM_TEST_FILES)
    if tracked_test_files != expected_test_files:
        missing = sorted(expected_test_files - tracked_test_files)
        unexpected = sorted(tracked_test_files - expected_test_files)
        _fail(
            "tracked Terraform test inventory mismatch; "
            f"missing={missing}, unexpected={unexpected}"
        )

    for relative_path, expected_sha256 in EXPECTED_TERRAFORM_TEST_FILES.items():
        path = repo_root / relative_path
        if path.is_symlink():
            _fail(f"tracked Terraform test must not be a symlink: {relative_path}")
        try:
            actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ContractError(
                f"cannot read tracked Terraform test {relative_path}: {exc}"
            ) from exc
        if actual_sha256 != expected_sha256:
            _fail(
                f"Terraform test content digest is not exact: {relative_path}; "
                f"expected={expected_sha256}, got={actual_sha256}"
            )

    version_path = "infra/gcp/.terraform-version"
    if version_path not in tracked_paths:
        _fail(f"tracked Terraform version pin is missing: {version_path}")
    path = repo_root / version_path
    if path.is_symlink():
        _fail(f"tracked Terraform version pin must not be a symlink: {version_path}")
    try:
        version_pin = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read {version_path}: {exc}") from exc
    if version_pin != f"{TERRAFORM_VERSION}\n".encode():
        _fail(f"{version_path} must exactly pin Terraform {TERRAFORM_VERSION}")


def _validate_pinned_terraform_file_contract(repo_root: Path) -> None:
    for relative_path, expected_sha256 in EXPECTED_PINNED_TERRAFORM_FILES.items():
        path = repo_root / relative_path
        if path.is_symlink():
            _fail(f"pinned Terraform source must not be a symlink: {relative_path}")
        try:
            actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ContractError(
                f"cannot read pinned Terraform source {relative_path}: {exc}"
            ) from exc
        if actual_sha256 != expected_sha256:
            _fail(
                f"Terraform source content digest is not exact: {relative_path}; "
                f"expected={expected_sha256}, got={actual_sha256}"
            )


def _validate_pinned_readiness_file_contract(repo_root: Path) -> None:
    for relative_path, expected_sha256 in EXPECTED_PINNED_READINESS_FILES.items():
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative_path],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if tracked.returncode == 1:
            _fail(f"pinned readiness oracle must be tracked: {relative_path}")
        if tracked.returncode != 0:
            detail = tracked.stderr.decode(errors="replace").strip()
            _fail(f"cannot verify tracked readiness oracle: {detail}")
        path = repo_root / relative_path
        if path.is_symlink():
            _fail(f"pinned readiness oracle must not be a symlink: {relative_path}")
        try:
            metadata = path.stat()
            actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ContractError(
                f"cannot read pinned readiness oracle {relative_path}: {exc}"
            ) from exc
        if not stat.S_ISREG(metadata.st_mode):
            _fail(f"pinned readiness oracle must be regular: {relative_path}")
        if actual_sha256 != expected_sha256:
            _fail(
                f"readiness oracle content digest is not exact: {relative_path}; "
                f"expected={expected_sha256}, got={actual_sha256}"
            )


def validate_static_contract(repo_root: Path) -> None:
    tracked_paths = validate_disk_inventory(repo_root)
    tracked_tf = frozenset(
        path for path in tracked_paths if path.endswith((".tf", ".tf.json"))
    )
    if tracked_tf != EXPECTED_TERRAFORM_FILES:
        missing = sorted(EXPECTED_TERRAFORM_FILES - tracked_tf)
        unexpected = sorted(tracked_tf - EXPECTED_TERRAFORM_FILES)
        _fail(
            "tracked Terraform inventory mismatch; "
            f"missing={missing}, unexpected={unexpected}. "
            "Nested Terraform modules are prohibited in this foundation."
        )
    _validate_test_file_contract(repo_root, tracked_paths)
    _validate_pinned_terraform_file_contract(repo_root)
    _validate_pinned_readiness_file_contract(repo_root)

    documents = _load_hcl_documents(repo_root, tracked_tf)
    modules = _single_label_blocks(documents, "module")
    if modules:
        _fail(
            "Terraform module blocks are prohibited in this foundation: "
            f"{sorted(modules)}"
        )
    for relative_path, document in documents.items():
        actual_keys = frozenset(document)
        if actual_keys != EXPECTED_TOP_LEVEL_KEYS[relative_path]:
            _fail(
                f"{relative_path} top-level block inventory is not exact; "
                f"expected={sorted(EXPECTED_TOP_LEVEL_KEYS[relative_path])}, "
                f"got={sorted(actual_keys)}"
            )
        _reject_execution_escape(document, relative_path)

    for relative_path, expected_blocks in EXPECTED_TERRAFORM_BLOCKS.items():
        if documents[relative_path].get("terraform") != expected_blocks:
            _fail(f"{relative_path} terraform/provider requirements are not exact")
    provider_blocks = _all_blocks(documents, "provider")
    if provider_blocks != EXPECTED_PROVIDER_BLOCKS:
        _fail(
            "Terraform provider configuration and aliases must exactly equal "
            "the single reviewed hashicorp/google provider"
        )
    import_blocks = _json_array(
        documents["infra/gcp/imports.tf"].get("import"),
        "infra/gcp/imports.tf.import",
    )
    if import_blocks != EXPECTED_IMPORT_BLOCKS:
        _fail(
            "Terraform import targets and live object IDs must exactly match "
            "the reviewed migration contract"
        )
    moved_blocks = _json_array(
        documents["infra/gcp/imports.tf"].get("moved"),
        "infra/gcp/imports.tf.moved",
    )
    if moved_blocks != EXPECTED_MOVED_BLOCKS:
        _fail(
            "Terraform moved targets must exactly match the reviewed credential "
            "retirement contract"
        )
    removed_blocks = _json_array(
        documents["infra/gcp/imports.tf"].get("removed"),
        "infra/gcp/imports.tf.removed",
    )
    if removed_blocks != EXPECTED_REMOVED_BLOCKS:
        _fail(
            "Terraform removed targets and state-only retention policy must exactly "
            "match the reviewed credential retirement contract"
        )

    data_blocks = _two_label_blocks(documents, "data")
    if frozenset(data_blocks) != EXPECTED_DATA:
        missing = sorted(EXPECTED_DATA - frozenset(data_blocks))
        unexpected = sorted(frozenset(data_blocks) - EXPECTED_DATA)
        _fail(
            "Terraform data declarations must exactly match the reviewed "
            f"allowlist; missing={missing}, unexpected={unexpected}"
        )
    for key, expected_config in EXPECTED_DATA_CONFIGS.items():
        if data_blocks[key] != expected_config:
            _fail(f"Terraform data configuration is not exact: {'.'.join(key)}")

    resources = _two_label_blocks(documents, "resource")
    expected_resources = frozenset(EXPECTED_RESOURCE_CONFIGS) | (
        EXPECTED_PINNED_RESOURCE_KEYS
    )
    if frozenset(resources) != expected_resources:
        missing = sorted(expected_resources - frozenset(resources))
        unexpected = sorted(frozenset(resources) - expected_resources)
        _fail(
            "Terraform resource declarations must exactly match the reviewed "
            f"allowlist; missing={missing}, unexpected={unexpected}"
        )
    for key, expected_config in EXPECTED_RESOURCE_CONFIGS.items():
        if resources[key] != expected_config:
            _fail(f"Terraform resource configuration is not exact: {'.'.join(key)}")

    variables = _single_label_blocks(documents, "variable")
    _validate_variables(variables)
    for relative_path, expected_locals in EXPECTED_LOCALS_BY_FILE.items():
        if documents[relative_path].get("locals") != expected_locals:
            _fail(f"Terraform locals configuration is not exact: {relative_path}")
    if documents["infra/gcp/main.tf"].get("check") != EXPECTED_CHECK_BLOCKS:
        _fail("Terraform check configuration is not exact: infra/gcp/main.tf")
    outputs = _single_label_blocks(documents, "output")
    if outputs != EXPECTED_OUTPUTS:
        _fail("Terraform output inventory and bodies must exactly match")


def validate_terraform_test_result(
    records: Iterable[Mapping[str, Any]],
) -> None:
    events = list(records)
    versions = [
        record.get("terraform") for record in events if record.get("type") == "version"
    ]
    if versions != [TERRAFORM_VERSION]:
        _fail(
            "Terraform test must run exactly once with the pinned version; "
            f"expected={[TERRAFORM_VERSION]}, got={versions}"
        )

    abstracts = [
        record.get("test_abstract")
        for record in events
        if record.get("type") == "test_abstract"
    ]
    if abstracts != [EXPECTED_TERRAFORM_TEST_ABSTRACT]:
        _fail(
            "Terraform test discovery must exactly equal the reviewed file/run inventory; "
            f"expected={EXPECTED_TERRAFORM_TEST_ABSTRACT}, got={abstracts}"
        )

    completed_runs = [
        record.get("test_run")
        for record in events
        if record.get("type") == "test_run"
        and isinstance(record.get("test_run"), dict)
        and record["test_run"].get("progress") == "complete"
    ]
    expected_runs = [
        {
            "path": "tests/foundation.tftest.hcl",
            "run": "foundation_security_contract",
            "progress": "complete",
            "status": "pass",
        },
        {
            "path": "tests/foundation.tftest.hcl",
            "run": "foundation_bootstrap_contract",
            "progress": "complete",
            "status": "pass",
        },
        {
            "path": "tests/foundation.tftest.hcl",
            "run": "jobs_bootstrap_contract",
            "progress": "complete",
            "status": "pass",
        },
        {
            "path": "tests/foundation.tftest.hcl",
            "run": "services_bootstrap_contract",
            "progress": "complete",
            "status": "pass",
        },
    ]
    if completed_runs != expected_runs:
        _fail(
            "Terraform test completion inventory must exactly equal the reviewed runs; "
            f"expected={expected_runs}, got={completed_runs}"
        )

    summaries = [
        record.get("test_summary")
        for record in events
        if record.get("type") == "test_summary"
    ]
    if summaries != [EXPECTED_TERRAFORM_TEST_SUMMARY]:
        _fail(
            "Terraform test summary must report exactly 4 passed, 0 failed, "
            f"0 errored, 0 skipped; got={summaries}"
        )


def _provider_id(provider: Mapping[str, Any]) -> str:
    name = provider.get("name")
    if not isinstance(name, str):
        _fail("WIF provider name must be a string")
    match = re.fullmatch(
        r"projects/[^/]+/locations/global/workloadIdentityPools/github/"
        r"providers/([^/]+)",
        name,
    )
    if match is None:
        _fail(f"WIF provider is outside the canonical github pool: {name!r}")
    return match.group(1)


def _validate_enabled(resource: Mapping[str, Any], label: str) -> None:
    if resource.get("state") != "ACTIVE":
        _fail(f"{label} must be ACTIVE")
    if resource.get("disabled", False) is not False:
        _fail(f"{label} must be enabled")


def _validate_disabled(resource: Mapping[str, Any], label: str) -> None:
    if resource.get("state") != "ACTIVE":
        _fail(f"{label} must remain an ACTIVE managed resource")
    if resource.get("disabled") is not True:
        _fail(f"{label} must remain disabled")


def validate_live_wif(document: Mapping[str, Any]) -> None:
    pool = _json_object(document.get("pool"), "pool")
    pool_name = pool.get("name")
    if not isinstance(pool_name, str) or not pool_name.endswith(
        "/locations/global/workloadIdentityPools/github"
    ):
        _fail("live WIF pool ID must exactly equal github")
    _validate_enabled(pool, "github WIF pool")

    listed = [
        _json_object(value, "listed provider")
        for value in _json_array(document.get("listed"), "listed")
    ]
    described = [
        _json_object(value, "described provider")
        for value in _json_array(document.get("described"), "described")
    ]

    expected_ids = frozenset(EXPECTED_LIVE_CONDITIONS)
    listed_by_id = {_provider_id(provider): provider for provider in listed}
    described_by_id = {_provider_id(provider): provider for provider in described}
    if len(listed_by_id) != len(listed):
        _fail("live WIF provider list contains duplicate IDs")
    if len(described_by_id) != len(described):
        _fail("described WIF provider set contains duplicate IDs")
    if frozenset(listed_by_id) != expected_ids:
        _fail(
            "live WIF provider set must exactly equal "
            f"{sorted(expected_ids)}, got {sorted(listed_by_id)}"
        )
    if frozenset(described_by_id) != expected_ids:
        _fail("described WIF provider set does not match the exact live list")

    for provider_id in sorted(expected_ids):
        state_validator = (
            _validate_disabled if provider_id == "github-preview" else _validate_enabled
        )
        state_validator(listed_by_id[provider_id], provider_id)
        provider = described_by_id[provider_id]
        state_validator(provider, provider_id)
        if provider.get("attributeCondition") != EXPECTED_LIVE_CONDITIONS[provider_id]:
            _fail(f"{provider_id} attributeCondition is not exact")
        if (
            provider.get("attributeMapping")
            != EXPECTED_LIVE_ATTRIBUTE_MAPPINGS[provider_id]
        ):
            _fail(f"{provider_id} attributeMapping is not exact")
        oidc = _json_object(provider.get("oidc"), f"{provider_id}.oidc")
        if oidc.get("issuerUri") != EXPECTED_ISSUER:
            _fail(f"{provider_id} issuerUri is not exact")
        audiences = oidc.get("allowedAudiences", [])
        if not isinstance(audiences, list) or audiences:
            _fail(f"{provider_id} allowedAudiences must be absent or empty")


def _policy_bindings(policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_bindings = policy.get("bindings", [])
    bindings = [
        _json_object(value, "IAM binding")
        for value in _json_array(raw_bindings, "policy.bindings")
    ]
    for binding in bindings:
        role = binding.get("role")
        members = binding.get("members")
        if not isinstance(role, str) or not role:
            _fail("IAM binding role must be a non-empty string")
        member_values = _json_array(members, f"{role}.members")
        if not member_values or not all(
            isinstance(member, str) and member for member in member_values
        ):
            _fail(f"{role}.members must contain non-empty strings")
        if len(set(member_values)) != len(member_values):
            _fail(f"{role}.members must not contain duplicates")
    return bindings


def _critical_member(member: str) -> bool:
    return member.startswith(REVIEW_REQUIRED_MEMBER_PREFIXES)


def _is_custom_role(role: str) -> bool:
    return (
        re.fullmatch(
            r"(?:projects|organizations)/[^/]+/roles/[^/]+",
            role,
        )
        is not None
    )


def _json_digest(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _permission_digest(permissions: Iterable[str]) -> str:
    return _json_digest(sorted(set(permissions)))


def _normalize_reviewed_bindings(
    raw_bindings: Iterable[Mapping[str, Any]],
    *,
    allow_empty: bool = False,
) -> dict[tuple[str, str, str], tuple[str | None, str | None]]:
    normalized: dict[
        tuple[str, str, str],
        tuple[str | None, str | None],
    ] = {}
    count = 0
    for index, raw_binding in enumerate(raw_bindings):
        count += 1
        binding = _json_object(raw_binding, f"reviewedBindings[{index}]")
        required_keys = {"member", "role", "scope"}
        allowed_keys = required_keys | {
            "condition_sha256",
            "permissions_sha256",
        }
        if not required_keys <= set(binding) or not set(binding) <= allowed_keys:
            _fail(
                f"reviewedBindings[{index}] must contain exact scope/role/member "
                "and only applicable digest fields"
            )
        scope = binding["scope"]
        role = binding["role"]
        member = binding["member"]
        if not all(
            isinstance(value, str) and value and value == value.strip()
            for value in (scope, role, member)
        ):
            _fail(
                f"reviewedBindings[{index}] scope/role/member must be exact "
                "non-empty strings"
            )
        if member in PUBLIC_MEMBERS:
            _fail("public members cannot be present in reviewed IAM bindings")

        custom_role = _is_custom_role(role)
        if not custom_role and re.fullmatch(r"roles/[^/]+", role) is None:
            _fail(f"reviewedBindings[{index}] has unsupported IAM role name")
        permissions_digest = binding.get("permissions_sha256")
        if custom_role:
            if (
                not isinstance(permissions_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", permissions_digest) is None
            ):
                _fail(
                    f"reviewedBindings[{index}] custom role requires exact "
                    "permissions_sha256"
                )
        elif permissions_digest is not None:
            _fail(
                f"reviewedBindings[{index}] predefined role must not declare "
                "permissions_sha256"
            )

        condition_digest = binding.get("condition_sha256")
        if condition_digest is not None and (
            not isinstance(condition_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", condition_digest) is None
        ):
            _fail(
                f"reviewedBindings[{index}] condition_sha256 must be lowercase SHA-256"
            )

        key = (scope, role, member)
        if key in normalized:
            _fail(
                "reviewed IAM bindings must not contain duplicate "
                f"scope/role/member triples: {key!r}"
            )
        normalized[key] = (permissions_digest, condition_digest)
    if count == 0 and not allow_empty:
        _fail("reviewed IAM bindings must be a non-empty JSON array")
    return normalized


def _permission_categories(permission: str) -> frozenset[str]:
    categories: set[str] = set()
    if permission in {
        "iam.serviceAccounts.actAs",
        "iam.serviceAccounts.getAccessToken",
        "iam.serviceAccounts.getOpenIdToken",
        "iam.serviceAccounts.implicitDelegation",
        "iam.serviceAccounts.signBlob",
        "iam.serviceAccounts.signJwt",
        "iam.serviceAccounts.setIamPolicy",
    } or (
        permission.startswith("iam.serviceAccountKeys.")
        and not permission.endswith((".get", ".list"))
    ):
        categories.add("service-account-impersonation")

    if permission.startswith("secretmanager."):
        safe_secret_suffixes = (
            ".get",
            ".list",
            ".listEffectiveTags",
            ".listTagBindings",
        )
        if permission == "secretmanager.versions.access" or not permission.endswith(
            safe_secret_suffixes
        ):
            categories.add("secret-read-or-mutation")

    if permission.startswith("artifactregistry."):
        verb = permission.rsplit(".", 1)[-1]
        if verb.startswith(("create", "delete", "import", "set", "update", "upload")):
            categories.add("artifact-registry-write")
        elif verb.startswith(("download", "export", "get", "list", "read")):
            categories.add("artifact-registry-read")
        else:
            # A new Artifact Registry power is sensitive until explicitly
            # classified; future provider roles must not bypass review.
            categories.add("artifact-registry-unclassified")

    if permission.startswith(
        ("storage.objects.", "storage.multipartUploads.")
    ) or permission in {
        "storage.buckets.delete",
        "storage.buckets.setIamPolicy",
        "storage.buckets.update",
    }:
        categories.add("terraform-state-read-or-write")

    if permission.endswith(".setIamPolicy") or permission in {
        "iam.roles.create",
        "iam.roles.delete",
        "iam.roles.update",
        "resourcemanager.projects.setIamPolicy",
    }:
        categories.add("iam-policy-escalation")
    return frozenset(categories)


def _offline_v1_permission_is_dangerous(permission: str) -> bool:
    if _permission_categories(permission):
        return True
    return (
        permission.rsplit(".", 1)[-1]
        not in OFFLINE_ADMIN_EVIDENCE_SAFE_PERMISSION_VERBS
    )


def validate_policy_audit(
    document: Mapping[str, Any],
    *,
    scope: str,
    reviewed_bindings: Iterable[Mapping[str, Any]],
    require_all_bindings: bool = False,
    allow_empty_reviewed_bindings: bool = False,
) -> None:
    policy = _json_object(document.get("policy"), "policy")
    bindings = _policy_bindings(policy)
    role_permissions_raw = _json_object(
        document.get("rolePermissions"),
        "rolePermissions",
    )
    reviewed = _normalize_reviewed_bindings(
        reviewed_bindings,
        allow_empty=allow_empty_reviewed_bindings,
    )

    roles = {binding["role"] for binding in bindings}
    if set(role_permissions_raw) != roles:
        missing = sorted(roles - set(role_permissions_raw))
        unexpected = sorted(set(role_permissions_raw) - roles)
        _fail(
            "role permission inventory must exactly match policy roles; "
            f"missing={missing}, unexpected={unexpected}"
        )

    role_permissions: dict[str, tuple[str, ...]] = {}
    for role, raw_permissions in role_permissions_raw.items():
        permissions = _json_array(raw_permissions, f"{role}.includedPermissions")
        if not all(
            isinstance(permission, str) and permission for permission in permissions
        ):
            _fail(f"{role}.includedPermissions must contain non-empty strings")
        if len(set(permissions)) != len(permissions):
            _fail(f"{role}.includedPermissions must not contain duplicates")
        role_permissions[role] = tuple(sorted(permissions))

    errors: list[str] = []
    actual_required: dict[
        tuple[str, str, str],
        tuple[str | None, str | None],
    ] = {}
    for binding in bindings:
        role = binding["role"]
        members = binding["members"]
        custom_role = _is_custom_role(role)
        categories = sorted(
            {
                category
                for permission in role_permissions[role]
                for category in _permission_categories(permission)
            }
        )
        binding_is_sensitive = bool(categories)
        condition_digest: str | None = None
        if "condition" in binding:
            condition = _json_object(binding["condition"], f"{role}.condition")
            condition_digest = _json_digest(condition)
        for member in members:
            if member in PUBLIC_MEMBERS:
                errors.append(f"{scope}: public principal {member!r} is forbidden")
                continue
            if (
                require_all_bindings
                or binding_is_sensitive
                or custom_role
                or _critical_member(member)
            ):
                key = (scope, role, member)
                if key in actual_required:
                    errors.append(
                        f"{scope}: duplicate role/member binding cannot be "
                        f"reviewed exactly: {role!r}, {member!r}"
                    )
                    continue
                permission_digest = (
                    _permission_digest(role_permissions[role]) if custom_role else None
                )
                actual_required[key] = (permission_digest, condition_digest)

    reviewed_for_scope = {
        key: digests for key, digests in reviewed.items() if key[0] == scope
    }
    actual_keys = set(actual_required)
    reviewed_keys = set(reviewed_for_scope)
    for missing in sorted(actual_keys - reviewed_keys):
        errors.append(
            "unreviewed exact IAM binding: "
            f"scope={missing[0]!r}, role={missing[1]!r}, member={missing[2]!r}"
        )
    for unexpected in sorted(reviewed_keys - actual_keys):
        errors.append(
            "review input has no matching live IAM binding: "
            f"scope={unexpected[0]!r}, role={unexpected[1]!r}, "
            f"member={unexpected[2]!r}"
        )
    for key in sorted(actual_keys & reviewed_keys):
        if actual_required[key] != reviewed_for_scope[key]:
            errors.append(
                "IAM binding permission/condition digest drift: "
                f"scope={key[0]!r}, role={key[1]!r}, member={key[2]!r}"
            )
    if errors:
        _fail("; ".join(sorted(set(errors))))


def _parse_offline_admin_timestamp(raw_timestamp: Any) -> datetime:
    if (
        not isinstance(raw_timestamp, str)
        or OFFLINE_ADMIN_EVIDENCE_TIMESTAMP.fullmatch(raw_timestamp) is None
    ):
        _fail("offline admin evidence capturedAt must be UTC RFC3339 whole seconds")
    try:
        return datetime.strptime(raw_timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError as exc:
        raise ContractError(
            "offline admin evidence capturedAt must be a real UTC timestamp"
        ) from exc


def _validate_offline_ancestor_document(
    ancestor: Mapping[str, Any],
    *,
    allowed_custom_role_parents: frozenset[str],
    workload_service_accounts: frozenset[str],
) -> None:
    if set(ancestor) != {"policy", "rolePermissions", "scope"}:
        _fail("offline admin ancestor records must contain exact schema keys")

    policy = _json_object(ancestor["policy"], "offline ancestor policy")
    if set(policy) != {"bindings"}:
        _fail("offline admin ancestor policies must contain only bindings")
    bindings = _json_array(policy["bindings"], "offline ancestor policy bindings")
    seen_role_members: set[tuple[str, str]] = set()
    for raw_binding in bindings:
        binding = _json_object(raw_binding, "offline ancestor IAM binding")
        if not {"members", "role"} <= set(binding) or not set(binding) <= {
            "condition",
            "members",
            "role",
        }:
            _fail("offline ancestor IAM bindings have an invalid schema")
        role = binding["role"]
        members = binding["members"]
        if not isinstance(role, str) or not role or role != role.strip():
            _fail("offline ancestor IAM roles must be exact non-empty strings")
        if re.fullmatch(r"roles/[^/]+", role) is None:
            custom_match = re.fullmatch(
                r"(projects|organizations)/([^/]+)/roles/[^/]+",
                role,
            )
            if custom_match is None:
                _fail("offline ancestor IAM role names are unsupported")
            if custom_match.group(1) == "projects":
                _fail(
                    "offline ancestor project custom roles are forbidden in "
                    "unsigned v1 structure"
                )
            custom_parent = f"{custom_match.group(1)}/{custom_match.group(2)}"
            if custom_parent not in allowed_custom_role_parents:
                _fail("offline ancestor custom role belongs to an unrelated scope")

        member_values = _json_array(members, "offline ancestor IAM members")
        if not member_values or not all(
            isinstance(member, str) and member and member == member.strip()
            for member in member_values
        ):
            _fail("offline ancestor IAM members must be exact non-empty strings")
        if len(set(member_values)) != len(member_values):
            _fail("offline ancestor IAM members must not contain duplicates")
        for member in member_values:
            role_member = (role, member)
            if role_member in seen_role_members:
                _fail("offline ancestor policies contain duplicate role/member pairs")
            seen_role_members.add(role_member)
            if member in PUBLIC_MEMBERS:
                _fail("offline ancestor policies must not contain public members")
            if member.startswith(FORBIDDEN_INHERITED_MEMBER_PREFIXES):
                _fail("offline ancestor policies must not contain group/domain members")
            if member.startswith(("deleted:", "principal:", "principalSet:")):
                _fail(
                    "offline ancestor policies must not contain federated, "
                    "deleted, or opaque principals"
                )
            if RESOURCE_MANAGER_SERVICE_ACCOUNT_SET.fullmatch(member) is not None:
                _fail(
                    "offline ancestor policies must not contain broad "
                    "service-account principal sets"
                )
            if member in {
                f"serviceAccount:{service_account}"
                for service_account in workload_service_accounts
            }:
                _fail(
                    "offline ancestor policies must not grant the target "
                    "workload accounts direct roles"
                )

        if "condition" in binding:
            condition = _json_object(
                binding["condition"],
                "offline ancestor IAM condition",
            )
            if not {"expression", "title"} <= set(condition) or not set(condition) <= {
                "description",
                "expression",
                "title",
            }:
                _fail("offline ancestor IAM conditions have an invalid schema")
            if not all(
                isinstance(value, str) and value for value in condition.values()
            ):
                _fail("offline ancestor IAM condition fields must be non-empty strings")

    role_permissions = _json_object(
        ancestor["rolePermissions"],
        "offline ancestor role permissions",
    )
    for role, raw_permissions in role_permissions.items():
        if not isinstance(role, str) or not role:
            _fail("offline ancestor role inventory keys must be non-empty strings")
        permissions = _json_array(
            raw_permissions,
            "offline ancestor included permissions",
        )
        if not permissions or not all(
            isinstance(permission, str)
            and permission
            and permission == permission.strip()
            for permission in permissions
        ):
            _fail(
                "offline ancestor role inventories must contain exact "
                "non-empty permissions"
            )
        if len(set(permissions)) != len(permissions):
            _fail(
                "offline ancestor role inventories must not contain "
                "duplicate permissions"
            )
        if permissions != sorted(permissions):
            _fail("offline ancestor role inventories must be sorted")
        if any(
            _offline_v1_permission_is_dangerous(permission)
            for permission in permissions
        ):
            _fail(
                "offline ancestor dangerous inherited permission is forbidden; "
                "unclassified verbs fail closed in unsigned v1 structure"
            )


def validate_offline_admin_evidence(
    document: Mapping[str, Any],
    *,
    expected_project_id: str,
    expected_project_number: str,
    workload_service_accounts: Iterable[str],
    now: datetime | None = None,
) -> None:
    if set(document) != {
        "ancestors",
        "capturedAt",
        "project",
        "reviewedBindings",
        "schemaVersion",
    }:
        _fail("offline admin evidence must contain exact top-level schema keys")
    if document["schemaVersion"] != OFFLINE_ADMIN_EVIDENCE_SCHEMA:
        _fail("offline admin evidence schemaVersion is unsupported")

    project = _json_object(document["project"], "offline admin evidence project")
    if set(project) != {"id", "number"}:
        _fail("offline admin evidence project must contain exact id/number keys")
    if (
        project["id"] != expected_project_id
        or project["number"] != expected_project_number
    ):
        _fail("offline admin evidence is not bound to the exact target project")

    captured_at = _parse_offline_admin_timestamp(document["capturedAt"])
    observed_at = now or datetime.now(UTC)
    if observed_at.tzinfo is None:
        _fail("offline admin evidence validation time must be timezone-aware")
    observed_at = observed_at.astimezone(UTC)
    if captured_at > observed_at:
        _fail("offline admin evidence capture time is in the future")
    if observed_at - captured_at > OFFLINE_ADMIN_EVIDENCE_MAX_AGE:
        _fail("offline admin evidence is stale")

    ancestors = _json_array(document["ancestors"], "offline admin ancestors")
    if not ancestors:
        _fail("offline admin evidence must include one declared organization")
    ancestor_scopes: list[str] = []
    for raw_ancestor in ancestors:
        ancestor = _json_object(raw_ancestor, "offline admin ancestor")
        scope = ancestor.get("scope")
        if (
            not isinstance(scope, str)
            or re.fullmatch(
                r"(?:folders|organizations)/[1-9][0-9]*",
                scope,
            )
            is None
        ):
            _fail("offline admin ancestor scopes must be canonical")
        ancestor_scopes.append(scope)
    if len(set(ancestor_scopes)) != len(ancestor_scopes):
        _fail("offline admin ancestor scopes must not contain duplicates")
    organization_scopes = [
        scope for scope in ancestor_scopes if scope.startswith("organizations/")
    ]
    if len(ancestors) != 1 or len(organization_scopes) != 1:
        _fail(
            "offline admin evidence v1 must contain exactly one declared "
            "organization and no asserted parent chain"
        )

    reviewed_bindings = [
        _json_object(binding, "offline admin reviewed binding")
        for binding in _json_array(
            document["reviewedBindings"],
            "offline admin reviewed bindings",
        )
    ]
    try:
        normalized_reviewed = _normalize_reviewed_bindings(
            reviewed_bindings,
            allow_empty=True,
        )
    except ContractError as exc:
        raise ContractError(
            "offline admin reviewed binding inventory is invalid"
        ) from exc
    if any(key[0] not in set(ancestor_scopes) for key in normalized_reviewed):
        _fail("offline admin reviewed bindings contain an unrelated scope")

    allowed_custom_role_parents = frozenset(organization_scopes)
    workload_accounts = frozenset(workload_service_accounts)
    if not workload_accounts or not all(
        isinstance(account, str)
        and account
        and account == account.strip()
        and account.endswith(f"@{expected_project_id}.iam.gserviceaccount.com")
        for account in workload_accounts
    ):
        _fail("offline admin workload-account inventory is invalid")

    for raw_ancestor in ancestors:
        ancestor = _json_object(raw_ancestor, "offline admin ancestor")
        _validate_offline_ancestor_document(
            ancestor,
            allowed_custom_role_parents=allowed_custom_role_parents,
            workload_service_accounts=workload_accounts,
        )
        try:
            validate_policy_audit(
                {
                    "policy": ancestor["policy"],
                    "rolePermissions": ancestor["rolePermissions"],
                },
                scope=ancestor["scope"],
                reviewed_bindings=reviewed_bindings,
                require_all_bindings=True,
                allow_empty_reviewed_bindings=True,
            )
        except ContractError as exc:
            raise ContractError(
                "offline admin evidence inherited-IAM audit failed"
            ) from exc


def _reject_duplicate_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            _fail("offline admin evidence contains a duplicate JSON key")
        parsed[key] = value
    return parsed


def _read_offline_admin_evidence_file(
    path: Path,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    if not path.is_absolute():
        _fail("offline admin evidence path must be absolute")
    try:
        path_metadata = os.lstat(path)
    except OSError as exc:
        raise ContractError(
            "offline admin evidence file is missing or unreadable"
        ) from exc
    if stat.S_ISLNK(path_metadata.st_mode) or not stat.S_ISREG(path_metadata.st_mode):
        _fail("offline admin evidence must be a regular non-symlink file")
    try:
        resolved_path = path.resolve(strict=True)
    except OSError as exc:
        raise ContractError(
            "offline admin evidence file is missing or unreadable"
        ) from exc
    if repo_root is not None and resolved_path.is_relative_to(
        repo_root.resolve(strict=True)
    ):
        _fail(
            "offline admin evidence must remain outside every Git worktree "
            "and repository"
        )
    if any((parent / ".git").exists() for parent in resolved_path.parents):
        _fail(
            "offline admin evidence must remain outside every Git worktree "
            "and repository"
        )

    open_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    open_flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, open_flags)
    except OSError as exc:
        raise ContractError(
            "offline admin evidence file is missing or unreadable"
        ) from exc
    try:
        opened_metadata = os.fstat(descriptor)
        if not stat.S_ISREG(opened_metadata.st_mode) or (
            opened_metadata.st_dev,
            opened_metadata.st_ino,
        ) != (path_metadata.st_dev, path_metadata.st_ino):
            _fail("offline admin evidence changed during secure open")
        permissions = stat.S_IMODE(opened_metadata.st_mode)
        if (
            opened_metadata.st_uid != os.geteuid()
            or permissions & ~0o600
            or permissions & stat.S_IRUSR == 0
        ):
            _fail(
                "offline admin evidence must be owner-read-only/owner-writable "
                "with no group or other permissions"
            )
        if opened_metadata.st_size > OFFLINE_ADMIN_EVIDENCE_MAX_BYTES:
            _fail("offline admin evidence exceeds the maximum accepted size")
        with os.fdopen(descriptor, encoding="utf-8") as evidence_stream:
            descriptor = -1
            try:
                parsed = json.load(
                    evidence_stream,
                    object_pairs_hook=_reject_duplicate_json_object,
                )
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ContractError(
                    "offline admin evidence must be valid UTF-8 JSON"
                ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return _json_object(parsed, "offline admin evidence")


def validate_offline_admin_evidence_file(
    path: Path,
    *,
    expected_project_id: str,
    expected_project_number: str,
    workload_service_accounts: Iterable[str],
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> None:
    document = _read_offline_admin_evidence_file(path, repo_root=repo_root)
    validate_offline_admin_evidence(
        document,
        expected_project_id=expected_project_id,
        expected_project_number=expected_project_number,
        workload_service_accounts=workload_service_accounts,
        now=now,
    )


def validate_secret_policy(
    policy: Mapping[str, Any],
    *,
    expected_member: str,
) -> None:
    bindings = _policy_bindings(policy)
    if len(bindings) != 1:
        _fail("secret IAM policy must contain exactly one role binding")
    binding = bindings[0]
    if binding.get("role") != "roles/secretmanager.secretAccessor":
        _fail(
            "secret IAM role set must exactly equal "
            "{roles/secretmanager.secretAccessor}"
        )
    if binding.get("members") != [expected_member]:
        _fail("secret accessor member must exactly equal the matching runtime")
    if "condition" in binding:
        _fail("secret accessor binding must not contain an unreviewed condition")


def _reviewed_bindings_from_env(
    variable_name: str,
) -> list[dict[str, Any]]:
    raw = os.environ.get(variable_name, "")
    if not raw.strip():
        _fail(f"{variable_name} must contain a reviewed JSON binding inventory")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractError(f"{variable_name} must contain valid JSON: {exc}") from exc
    return [
        _json_object(value, f"{variable_name}[{index}]")
        for index, value in enumerate(_json_array(parsed, variable_name))
    ]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    static = subparsers.add_parser("static")
    static.add_argument("--repo-root", type=Path, required=True)

    disk_inventory = subparsers.add_parser("disk-inventory")
    disk_inventory.add_argument("--repo-root", type=Path, required=True)

    subparsers.add_parser("terraform-test-result")
    subparsers.add_parser("wif-live")

    audit = subparsers.add_parser("audit-policy")
    audit.add_argument("--scope", required=True)
    audit.add_argument("--reviewed-bindings-env", required=True)
    audit.add_argument("--require-all-bindings", action="store_true")

    offline_admin = subparsers.add_parser("offline-admin-evidence-structure")
    offline_admin.add_argument("--evidence-file", type=Path, required=True)
    offline_admin.add_argument("--repo-root", type=Path, required=True)
    offline_admin.add_argument("--expected-project-id", required=True)
    offline_admin.add_argument("--expected-project-number", required=True)
    offline_admin.add_argument(
        "--expected-workload-service-account",
        action="append",
        required=True,
    )

    secret = subparsers.add_parser("secret-policy")
    secret.add_argument("--expected-member", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "static":
            validate_static_contract(args.repo_root.resolve())
        elif args.command == "disk-inventory":
            validate_disk_inventory(args.repo_root.resolve())
        elif args.command == "terraform-test-result":
            records = _read_stdin_json_lines()
            for record in records:
                message = record.get("@message")
                if isinstance(message, str):
                    print(message)
            validate_terraform_test_result(records)
        elif args.command == "wif-live":
            validate_live_wif(_read_stdin_json())
        elif args.command == "audit-policy":
            validate_policy_audit(
                _read_stdin_json(),
                scope=args.scope,
                reviewed_bindings=_reviewed_bindings_from_env(
                    args.reviewed_bindings_env
                ),
                require_all_bindings=args.require_all_bindings,
            )
        elif args.command == "offline-admin-evidence-structure":
            validate_offline_admin_evidence_file(
                args.evidence_file,
                expected_project_id=args.expected_project_id,
                expected_project_number=args.expected_project_number,
                workload_service_accounts=args.expected_workload_service_account,
                repo_root=args.repo_root,
            )
            print(
                "STRUCTURE ONLY / NOT AUTHENTICATED: unsigned v1 declares one "
                "organization; parent linkage and company-admin origin are unverified."
            )
            return 0
        elif args.command == "secret-policy":
            validate_secret_policy(
                _read_stdin_json(),
                expected_member=args.expected_member,
            )
        else:  # pragma: no cover - argparse owns this branch.
            raise AssertionError(args.command)
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {args.command} foundation contract verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
