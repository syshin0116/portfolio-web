#!/usr/bin/env bash
set -euo pipefail

readonly project_id="festive-ally-503605-v7"
readonly provider="projects/72919926064/locations/global/workloadIdentityPools/github/providers/github-production"

for variable_name in DELIVERY_ROLE DELIVERY_TARGET; do
  [[ -n "${!variable_name:-}" ]] || {
    printf 'missing required delivery selector: %s\n' "$variable_name" >&2
    exit 1
  }
done

case "$DELIVERY_TARGET" in
  preview)
    readonly expected_environment="Agent Preview"
    readonly builder="agent-preview-image-builder@${project_id}.iam.gserviceaccount.com"
    readonly deployer="agent-preview-deployer@${project_id}.iam.gserviceaccount.com"
    readonly image_repository="us-east4-docker.pkg.dev/${project_id}/agent-preview/agent"
    readonly cloud_run_service="agent-preview"
    readonly migration_job="agent-preview-migrate"
    readonly grant_probe_job="agent-preview-grants"
    readonly maintenance_job="agent-preview-maintenance"
    ;;
  production)
    readonly expected_environment="Agent Production"
    readonly builder="agent-image-builder@${project_id}.iam.gserviceaccount.com"
    readonly deployer="agent-prod-deployer@${project_id}.iam.gserviceaccount.com"
    readonly image_repository="us-east4-docker.pkg.dev/${project_id}/agent/agent"
    readonly cloud_run_service="agent"
    readonly migration_job="agent-migrate"
    readonly grant_probe_job="agent-grants"
    readonly maintenance_job="agent-maintenance"
    ;;
  *)
    printf 'unexpected agent delivery target\n' >&2
    exit 1
    ;;
esac

case "$DELIVERY_ROLE" in
  builder)
    [[ -z "${DELIVERY_ENVIRONMENT:-}" ]] || {
      printf 'builder must not receive a GitHub deployment environment\n' >&2
      exit 1
    }
    printf 'workload_identity_provider=%s\n' "$provider"
    printf 'service_account=%s\n' "$builder"
    printf 'image_repository=%s\n' "$image_repository"
    ;;
  deployer)
    [[ "${DELIVERY_ENVIRONMENT:-}" == "$expected_environment" ]] || {
      printf 'deployer environment does not match the delivery target\n' >&2
      exit 1
    }
    printf 'workload_identity_provider=%s\n' "$provider"
    printf 'service_account=%s\n' "$deployer"
    printf 'cloud_run_service=%s\n' "$cloud_run_service"
    printf 'migration_job=%s\n' "$migration_job"
    printf 'grant_probe_job=%s\n' "$grant_probe_job"
    printf 'maintenance_job=%s\n' "$maintenance_job"
    ;;
  *)
    printf 'unexpected agent delivery role\n' >&2
    exit 1
    ;;
esac
