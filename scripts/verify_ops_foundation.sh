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
SCRIPT_PATH="${BASH_SOURCE[0]}"
if [[ "$SCRIPT_PATH" != /* ]]; then
  SCRIPT_PATH="$(pwd -P)/${SCRIPT_PATH}"
fi
SCRIPT_PARENT="${SCRIPT_PATH%/*}"
SCRIPT_DIR="$(cd -- "$SCRIPT_PARENT" && pwd -P)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly REPO_ROOT
readonly TERRAFORM_DIR="${REPO_ROOT}/infra/gcp"
readonly CONTRACT_SCRIPT="${REPO_ROOT}/scripts/ops_foundation_contract.py"
readonly LIVE_GCP_VERIFIER="${REPO_ROOT}/scripts/verify_gcp_project_readiness.py"
readonly LIVE_TOOLCHAIN_VERIFIER="${REPO_ROOT}/scripts/ops_foundation_live_toolchain.py"
readonly LIVE_READINESS_ORACLE="${REPO_ROOT}/scripts/gcp_project_readiness_contract.json"
readonly GOVERNANCE_MANIFEST="${REPO_ROOT}/.github/repository-governance.json"
readonly GOVERNANCE_VERIFIER="${REPO_ROOT}/scripts/verify_repository_governance.py"
LIVE_TRUSTED_HOME=""
LIVE_BOOTSTRAP_PYTHON_BIN=""
LIVE_UV_BIN=""
LIVE_PYTHON_BIN=""
LIVE_GH_BIN=""
LIVE_GCLOUD_BIN=""
readonly LIVE_CHILD_PATH="/usr/bin:/bin:/usr/sbin:/sbin"
readonly LIVE_SELECTION_PATH="${PATH:-}"

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

verify_static_file_contract() {
  [[ -f "$LIVE_GCP_VERIFIER" && ! -L "$LIVE_GCP_VERIFIER" ]] ||
    fail "exact-project live verifier must be a regular non-symlink file"
  [[ -f "$LIVE_TOOLCHAIN_VERIFIER" && ! -L "$LIVE_TOOLCHAIN_VERIFIER" ]] ||
    fail "live toolchain verifier must be a regular non-symlink file"
  [[ -f "$LIVE_READINESS_ORACLE" && ! -L "$LIVE_READINESS_ORACLE" ]] ||
    fail "exact-project readiness oracle must be a regular non-symlink file"

  if [[ -e "$GOVERNANCE_MANIFEST" && ! -f "$GOVERNANCE_VERIFIER" ]] ||
    [[ -e "$GOVERNANCE_VERIFIER" && ! -f "$GOVERNANCE_MANIFEST" ]]; then
    fail "canonical repository governance manifest and verifier must land together"
  fi
}

verify_static_contract() {
  require_command uv
  verify_static_file_contract
  uv run --frozen --package syshin0116-dev-agent \
    python "$CONTRACT_SCRIPT" static --repo-root "$REPO_ROOT"

  printf 'OK: credential-free Terraform security contract verified.\n'
}

resolve_live_tool() {
  local tool="$1"

  /usr/bin/env -i \
    PATH="$LIVE_SELECTION_PATH" \
    "$LIVE_BOOTSTRAP_PYTHON_BIN" -I -s \
    "$LIVE_TOOLCHAIN_VERIFIER" resolve "$tool"
}

reject_live_google_overrides() {
  local overrides

  overrides="$(
    compgen -A variable CLOUDSDK_ || true
    compgen -A variable GOOGLE_ || true
  )"
  [[ -z "$overrides" ]] ||
    fail "caller Google/gcloud environment overrides are forbidden"
}

clear_live_loader_overrides() {
  local name
  local overrides

  overrides="$(
    compgen -A variable DYLD_ || true
    compgen -A variable LD_ || true
  )"
  while IFS= read -r name; do
    [[ -z "$name" ]] || unset "$name"
  done <<<"$overrides"
}

prepare_live_toolchain() {
  local include_gcloud="${1:-true}"

  reject_live_google_overrides
  clear_live_loader_overrides
  [[ -x /usr/bin/python3 ]] ||
    fail "trusted system Python is required for live toolchain preflight"
  verify_static_file_contract
  LIVE_BOOTSTRAP_PYTHON_BIN="$(
    /usr/bin/env -i \
      PATH="$LIVE_CHILD_PATH" \
      /usr/bin/python3 -I -s "$LIVE_TOOLCHAIN_VERIFIER" \
      validate /usr/bin/python3
  )" || fail "cannot validate the trusted system Python"
  LIVE_TRUSTED_HOME="$(
    /usr/bin/env -i \
      PATH="$LIVE_CHILD_PATH" \
      "$LIVE_BOOTSTRAP_PYTHON_BIN" -I -s \
      "$LIVE_TOOLCHAIN_VERIFIER" home
  )" || fail "cannot resolve the trusted local home"
  LIVE_UV_BIN="$(resolve_live_tool uv)" || fail "cannot resolve trusted uv"
  LIVE_GH_BIN="$(resolve_live_tool gh)" || fail "cannot resolve trusted gh"
  if [[ "$include_gcloud" == "true" ]]; then
    LIVE_GCLOUD_BIN="$(resolve_live_tool gcloud)" ||
      fail "cannot resolve trusted gcloud"
  fi
}

prepare_live_python() {
  LIVE_PYTHON_BIN="$(
    /usr/bin/env -i \
      PATH="$LIVE_CHILD_PATH" \
      "$LIVE_BOOTSTRAP_PYTHON_BIN" -I -s "$LIVE_TOOLCHAIN_VERIFIER" \
      validate "${REPO_ROOT}/.venv/bin/python3"
  )" || fail "cannot resolve the trusted frozen-workspace Python"
  /usr/bin/env -i \
    HOME="$LIVE_TRUSTED_HOME" \
    PATH="$LIVE_CHILD_PATH" \
    "$LIVE_PYTHON_BIN" -I -s -c \
    'import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] <= (3, 14) else 1)' ||
    fail "live Python must be within the reviewed 3.12-3.14 range"
}

run_live_uv() {
  /usr/bin/env -i \
    HOME="$LIVE_TRUSTED_HOME" \
    PATH="$LIVE_CHILD_PATH" \
    "$LIVE_UV_BIN" run --frozen --package syshin0116-dev-agent "$@"
}

verify_static_contract_live() {
  run_live_uv \
    python "$CONTRACT_SCRIPT" static --repo-root "$REPO_ROOT"
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
    (
      cd "$REPO_ROOT"
      run_live_uv \
        python "$GOVERNANCE_VERIFIER" --live --gh-bin "$LIVE_GH_BIN"
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
  prepare_live_toolchain
  verify_static_contract_live
  prepare_live_python
  /usr/bin/env -i \
    HOME="$LIVE_TRUSTED_HOME" \
    OPS_FOUNDATION_GCLOUD_ACCOUNT="${OPS_FOUNDATION_GCLOUD_ACCOUNT:-}" \
    PATH="$LIVE_CHILD_PATH" \
    "$LIVE_PYTHON_BIN" -E -s "$LIVE_GCP_VERIFIER" \
    --gcloud-bin "$LIVE_GCLOUD_BIN"
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
    prepare_live_toolchain false
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
