#!/bin/bash -p

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  /usr/bin/printf '%s\n' \
    "FAIL: sourcing this verifier is unsupported" >&2
  return 1
fi

if [[ "$-" != *p* ]]; then
  /usr/bin/printf '%s\n' \
    "FAIL: invoke this verifier directly; 'bash script' is not a supported security boundary" >&2
  /bin/kill -s KILL "$$"
fi

set -euo pipefail

readonly PROJECT_ID="festive-ally-503605-v7"
readonly EXPECTED_PROJECT_NUMBER="72919926064"
readonly REGION="us-east4"
readonly PRODUCTION_RUNTIME_SA="agent-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PREVIEW_RUNTIME_SA="agent-preview-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PREVIEW_DEPLOYER_SA="agent-preview-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PRODUCTION_DEPLOYER_SA="agent-prod-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
readonly BUILDER_SA="agent-image-builder@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PREVIEW_BUILDER_SA="agent-preview-image-builder@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PREVIEW_MIGRATOR_SA="agent-preview-migrator@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PRODUCTION_MIGRATOR_SA="agent-prod-migrator@${PROJECT_ID}.iam.gserviceaccount.com"
readonly MAINTENANCE_SCHEDULER_SA="agent-maintenance-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"
readonly -a WORKLOAD_SERVICE_ACCOUNTS=(
  "$PRODUCTION_RUNTIME_SA"
  "$PREVIEW_RUNTIME_SA"
  "$PREVIEW_DEPLOYER_SA"
  "$PRODUCTION_DEPLOYER_SA"
  "$BUILDER_SA"
  "$PREVIEW_BUILDER_SA"
  "$PREVIEW_MIGRATOR_SA"
  "$PRODUCTION_MIGRATOR_SA"
  "$MAINTENANCE_SCHEDULER_SA"
)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly REPO_ROOT
readonly TERRAFORM_DIR="${REPO_ROOT}/infra/gcp"
readonly CONTRACT_SCRIPT="${REPO_ROOT}/scripts/ops_foundation_contract.py"
readonly LIVE_GCP_VERIFIER="${REPO_ROOT}/scripts/verify_gcp_project_readiness.py"
readonly GOVERNANCE_MANIFEST="${REPO_ROOT}/.github/repository-governance.json"
readonly GOVERNANCE_VERIFIER="${REPO_ROOT}/scripts/verify_repository_governance.py"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null || fail "missing command: $1"
}

verify_offline_admin_evidence_structure() {
  local -a evidence_args
  local service_account

  require_command python3
  [[ -n "${OPS_FOUNDATION_ADMIN_EVIDENCE_FILE:-}" ]] ||
    fail "OPS_FOUNDATION_ADMIN_EVIDENCE_FILE is required for unsigned structure validation"
  evidence_args=(
    offline-admin-evidence-structure
    --evidence-file "$OPS_FOUNDATION_ADMIN_EVIDENCE_FILE"
    --repo-root "$REPO_ROOT"
    --expected-project-id "$PROJECT_ID"
    --expected-project-number "$EXPECTED_PROJECT_NUMBER"
  )
  for service_account in "${WORKLOAD_SERVICE_ACCOUNTS[@]}"; do
    evidence_args+=(
      --expected-workload-service-account "$service_account"
    )
  done
  python3 "$CONTRACT_SCRIPT" "${evidence_args[@]}"
}

verify_disk_contract() {
  require_command python3
  python3 "$CONTRACT_SCRIPT" disk-inventory --repo-root "$REPO_ROOT"
}

verify_static_contract() {
  require_command uv
  [[ -f "$LIVE_GCP_VERIFIER" && ! -L "$LIVE_GCP_VERIFIER" ]] ||
    fail "exact-project live verifier must be a regular non-symlink file"
  uv run --frozen --package syshin0116-dev-agent \
    python "$CONTRACT_SCRIPT" static --repo-root "$REPO_ROOT"

  if [[ -e "$GOVERNANCE_MANIFEST" && ! -f "$GOVERNANCE_VERIFIER" ]] ||
    [[ -e "$GOVERNANCE_VERIFIER" && ! -f "$GOVERNANCE_MANIFEST" ]]; then
    fail "canonical repository governance manifest and verifier must land together"
  fi

  printf 'OK: credential-free Terraform security contract verified.\n'
}

verify_terraform_format() {
  verify_disk_contract
  require_command terraform
  terraform fmt -check -recursive "$TERRAFORM_DIR"
}

verify_terraform_init() {
  verify_disk_contract
  require_command terraform
  terraform -chdir="$TERRAFORM_DIR" init \
    -backend=false \
    -input=false \
    -lockfile=readonly
}

verify_terraform_validate() {
  verify_disk_contract
  require_command terraform
  terraform -chdir="$TERRAFORM_DIR" validate
}

verify_terraform_tests() {
  verify_disk_contract
  require_command terraform
  terraform -chdir="$TERRAFORM_DIR" test -json |
    python3 "$CONTRACT_SCRIPT" terraform-test-result
}

verify_state_bucket_metadata() {
  local bucket_json

  require_command jq
  bucket_json="$(cat)"
  jq -e \
    --arg expected_location "$REGION" \
    '
      (.location | ascii_upcase) == ($expected_location | ascii_upcase)
      and (.public_access_prevention // .iamConfiguration.publicAccessPrevention) == "enforced"
      and (.uniform_bucket_level_access // .iamConfiguration.uniformBucketLevelAccess.enabled) == true
      and (.versioning_enabled // .versioning.enabled) == true
      and (
        (
          .soft_delete_policy.retentionDurationSeconds
          // .soft_delete_policy.retention_duration_seconds
          // .softDeletePolicy.retentionDurationSeconds
          // 0
        ) | tonumber
      ) >= 2592000
    ' >/dev/null <<<"$bucket_json" ||
    fail "state bucket location must be exactly ${REGION} and must enforce public-access prevention, uniform access, versioning, and 30-day soft delete"
}

verify_canonical_repository_governance() {
  local required="${1:-false}"

  if [[ -f "$GOVERNANCE_MANIFEST" && -f "$GOVERNANCE_VERIFIER" ]]; then
    require_command uv
    require_command gh
    (
      cd "$REPO_ROOT"
      uv run --frozen --package syshin0116-dev-agent \
        python "$GOVERNANCE_VERIFIER" --live
    )
  elif [[ -e "$GOVERNANCE_MANIFEST" || -e "$GOVERNANCE_VERIFIER" ]]; then
    fail "canonical repository-governance manifest and verifier must land together"
  elif [[ "$required" == "true" ]]; then
    fail "canonical repository-governance manifest and verifier are required for live readiness"
  else
    printf '%s\n' \
      "INFO: canonical repository-governance files are not present on this branch; GitHub environment policy is intentionally not claimed here."
  fi
}

verify_live_contract() {
  verify_static_contract
  require_command python3
  python3 -E -s "$LIVE_GCP_VERIFIER"
  verify_canonical_repository_governance true
  printf '%s\n' \
    "OK: exact GCP-project direct state and canonical GitHub governance verified; public launch, spend safety, project parent, and inherited IAM are not claimed."
}

usage() {
  printf '%s\n' \
    "Usage: ${0##*/} [--static|--terraform-fmt|--terraform-init|" \
    "  --terraform-validate|--terraform-test|--state-bucket-metadata|" \
    "  --offline-admin-evidence-structure|--live|--governance-live]"
}

if (($# > 1)); then
  usage >&2
  fail "expected at most one mode argument"
fi

mode="${1:---static}"
case "$mode" in
  --static)
    verify_static_contract
    ;;
  --terraform-fmt)
    verify_terraform_format
    ;;
  --terraform-init)
    verify_terraform_init
    ;;
  --terraform-validate)
    verify_terraform_validate
    ;;
  --terraform-test)
    verify_terraform_tests
    ;;
  --state-bucket-metadata)
    verify_state_bucket_metadata
    ;;
  --offline-admin-evidence-structure)
    verify_offline_admin_evidence_structure
    ;;
  --live)
    verify_live_contract
    ;;
  --governance-live)
    verify_canonical_repository_governance
    ;;
  -h | --help)
    usage
    ;;
  *)
    usage >&2
    fail "unknown mode: ${mode}"
    ;;
esac
