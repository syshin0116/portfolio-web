#!/usr/bin/env bash
set -euo pipefail

for variable_name in \
  BUILDER_SERVICE_ACCOUNT \
  DELIVERY_ENVIRONMENT \
  DEPLOYER_SERVICE_ACCOUNT \
  WORKLOAD_IDENTITY_PROVIDER; do
  [[ -n "${!variable_name:-}" ]] || {
    printf 'missing required delivery identity: %s\n' "$variable_name" >&2
    exit 1
  }
done

case "$DELIVERY_ENVIRONMENT" in
  "Agent Preview")
    readonly expected_builder="agent-preview-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com"
    readonly expected_deployer="agent-preview-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
    readonly expected_provider="projects/72919926064/locations/global/workloadIdentityPools/github/providers/github-preview"
    readonly image_repository="us-east4-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent"
    ;;
  "Agent Production")
    readonly expected_builder="agent-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com"
    readonly expected_deployer="agent-prod-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
    readonly expected_provider="projects/72919926064/locations/global/workloadIdentityPools/github/providers/github-production"
    readonly image_repository="us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent"
    ;;
  *)
    printf 'unexpected agent delivery environment\n' >&2
    exit 1
    ;;
esac

[[ "$BUILDER_SERVICE_ACCOUNT" == "$expected_builder" ]] || {
  printf 'builder identity does not match the delivery environment\n' >&2
  exit 1
}
[[ "$DEPLOYER_SERVICE_ACCOUNT" == "$expected_deployer" ]] || {
  printf 'deployer identity does not match the delivery environment\n' >&2
  exit 1
}
[[ "$WORKLOAD_IDENTITY_PROVIDER" == "$expected_provider" ]] || {
  printf 'workload identity provider does not match the delivery environment\n' >&2
  exit 1
}

printf 'image_repository=%s\n' "$image_repository"
