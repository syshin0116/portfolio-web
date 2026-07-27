#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ID="festive-ally-503605-v7"
readonly EXPECTED_PROJECT_NUMBER="72919926064"
readonly REGION="us-east4"
readonly HCL2_VERSION="7.3.1"
readonly STATE_BUCKET="${PROJECT_ID}-tfstate"
readonly STATE_OBJECT="syshin0116.dev/gcp/foundation/default.tfstate"
readonly PRODUCTION_RUNTIME_SA="agent-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PREVIEW_RUNTIME_SA="agent-preview-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PREVIEW_DEPLOYER_SA="agent-preview-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PRODUCTION_DEPLOYER_SA="agent-prod-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly REPO_ROOT
readonly TERRAFORM_DIR="${REPO_ROOT}/infra/gcp"
readonly CONTRACT_SCRIPT="${REPO_ROOT}/scripts/ops_foundation_contract.py"
readonly GOVERNANCE_MANIFEST="${REPO_ROOT}/.github/repository-governance.json"
readonly GOVERNANCE_VERIFIER="${REPO_ROOT}/scripts/verify_repository_governance.py"

readonly REQUIRED_APIS=(
  artifactregistry.googleapis.com
  cloudresourcemanager.googleapis.com
  iam.googleapis.com
  iamcredentials.googleapis.com
  run.googleapis.com
  secretmanager.googleapis.com
  storage.googleapis.com
  sts.googleapis.com
)

readonly PRODUCTION_SECRET_NAMES=(
  agent-auth-secret
  agent-database-url
  anthropic-api-key
  langsmith-api-key
  openai-api-key
)

readonly PREVIEW_SECRET_NAMES=(
  agent-preview-anthropic-api-key
  agent-preview-auth-secret
  agent-preview-database-url
  agent-preview-langsmith-api-key
  agent-preview-openai-api-key
)

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null || fail "missing command: $1"
}

verify_disk_contract() {
  require_command python3
  python3 "$CONTRACT_SCRIPT" disk-inventory --repo-root "$REPO_ROOT"
}

verify_static_contract() {
  require_command uv
  uv run \
    --no-project \
    --with "python-hcl2==${HCL2_VERSION}" \
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

policy_has_member() {
  local policy_json="$1"
  local role="$2"
  local member="$3"

  jq -e \
    --arg role "$role" \
    --arg member "$member" \
    '.bindings[]? | select(.role == $role) | .members[]? | select(. == $member)' \
    >/dev/null <<<"$policy_json"
}

assert_policy_lacks_member() {
  local policy_json="$1"
  local role="$2"
  local member="$3"
  local description="$4"

  if policy_has_member "$policy_json" "$role" "$member"; then
    fail "$description"
  fi
}

assert_exact_role_member() {
  local policy_json="$1"
  local role="$2"
  local expected_member="$3"
  local description="$4"

  jq -e \
    --arg role "$role" \
    --arg expected_member "$expected_member" \
    '([.bindings[]? | select(.role == $role) | .members[]?] | unique | sort) == [$expected_member]' \
    >/dev/null <<<"$policy_json" || fail "$description"
}

assert_policy_lacks_role() {
  local policy_json="$1"
  local role="$2"
  local description="$3"

  jq -e \
    --arg role "$role" \
    '[.bindings[]? | select(.role == $role) | .members[]?] | length == 0' \
    >/dev/null <<<"$policy_json" || fail "$description"
}

assert_member_has_no_direct_roles() {
  local policy_json="$1"
  local member="$2"
  local description="$3"

  jq -e \
    --arg member "$member" \
    '[.bindings[]? | select((.members // []) | index($member)) | .role] | length == 0' \
    >/dev/null <<<"$policy_json" || fail "$description"
}

assert_policy_has_no_public_members() {
  local policy_json="$1"
  local description="$2"

  jq -e \
    '[.bindings[]?.members[]? | select(. == "allUsers" or . == "allAuthenticatedUsers")] | length == 0' \
    >/dev/null <<<"$policy_json" || fail "$description"
}

assert_policy_roles_exactly() {
  local policy_json="$1"
  local expected_role="$2"
  local description="$3"

  jq -e \
    --arg expected_role "$expected_role" \
    '
      ([.bindings[]?.role] | unique | sort) == [$expected_role]
      and ([.bindings[]? | select(has("condition"))] | length == 0)
    ' >/dev/null <<<"$policy_json" || fail "$description"
}

describe_iam_role() {
  local role="$1"
  local parent_type
  local parent_id
  local role_id
  local extra

  case "$role" in
    roles/*)
      gcloud iam roles describe "$role" --format=json
      ;;
    projects/*/roles/* | organizations/*/roles/*)
      IFS=/ read -r parent_type parent_id extra role_id <<<"$role"
      [[ "$extra" == "roles" && -n "$parent_id" && -n "$role_id" ]] ||
        fail "invalid custom IAM role name: ${role}"
      if [[ "$parent_type" == "projects" ]]; then
        gcloud iam roles describe "$role_id" \
          --project "$parent_id" \
          --format=json
      else
        gcloud iam roles describe "$role_id" \
          --organization "$parent_id" \
          --format=json
      fi
      ;;
    *)
      fail "unsupported IAM role name in live policy: ${role}"
      ;;
  esac
}

role_permissions_for_policy() {
  local policy_json="$1"
  local role
  local role_json
  local permissions_json
  local inventory="{}"

  jq -e '
    (.bindings // []) as $bindings
    | ($bindings | type) == "array"
    and all($bindings[]?; (.role | type) == "string")
  ' >/dev/null <<<"$policy_json" ||
    fail "live IAM policy bindings are not structurally valid"

  while IFS= read -r role; do
    [[ -n "$role" ]] || continue
    role_json="$(describe_iam_role "$role")"
    permissions_json="$(
      jq -ce '
        .includedPermissions
        | select(type == "array")
        | select(all(.[]; type == "string" and length > 0))
      ' <<<"$role_json"
    )" || fail "cannot resolve includedPermissions for IAM role ${role}"
    inventory="$(
      jq -cn \
        --argjson inventory "$inventory" \
        --arg role "$role" \
        --argjson permissions "$permissions_json" \
        '$inventory + {($role): $permissions}'
    )"
  done < <(
    jq -r '[.bindings[]?.role] | unique[]' <<<"$policy_json"
  )

  printf '%s\n' "$inventory"
}

audit_iam_policy() {
  local policy_json="$1"
  local scope="$2"
  local reviewed_bindings_env="$3"
  local require_all_bindings="${4:-false}"
  local role_permissions
  local -a audit_args

  role_permissions="$(role_permissions_for_policy "$policy_json")"
  audit_args=(
    audit-policy
    --scope "$scope"
    --reviewed-bindings-env "$reviewed_bindings_env"
  )
  if [[ "$require_all_bindings" == "true" ]]; then
    audit_args+=(--require-all-bindings)
  fi
  jq -cn \
    --argjson policy "$policy_json" \
    --argjson role_permissions "$role_permissions" \
    '{policy: $policy, rolePermissions: $role_permissions}' |
    python3 "$CONTRACT_SCRIPT" "${audit_args[@]}"
}

verify_ancestor_policies() {
  local ancestors_json
  local ancestor_type
  local ancestor_id
  local policy_json

  ancestors_json="$(
    gcloud projects get-ancestors "$PROJECT_ID" --format=json
  )"
  jq -e \
    --arg project_id "$PROJECT_ID" \
    --arg project_number "$EXPECTED_PROJECT_NUMBER" \
    '
      type == "array"
      and length > 0
      and all(.[];
        (.type == "project" or .type == "folder" or .type == "organization")
        and ((.id | tostring) | length > 0)
      )
      and ([.[] | select(.type == "project")] | length == 1)
      and (
        [.[] | select(
          .type == "project"
          and ((.id | tostring) == $project_id or (.id | tostring) == $project_number)
        )] | length == 1
      )
    ' >/dev/null <<<"$ancestors_json" ||
    fail "project ancestor inventory is unreadable or does not identify the reviewed project"

  while IFS=$'\t' read -r ancestor_type ancestor_id; do
    case "$ancestor_type" in
      project)
        ;;
      folder)
        policy_json="$(
          gcloud resource-manager folders get-iam-policy \
            "$ancestor_id" \
            --format=json
        )"
        audit_iam_policy \
          "$policy_json" \
          "folders/${ancestor_id}" \
          "OPS_FOUNDATION_REVIEWED_IAM_BINDINGS"
        ;;
      organization)
        policy_json="$(
          gcloud organizations get-iam-policy \
            "$ancestor_id" \
            --format=json
        )"
        audit_iam_policy \
          "$policy_json" \
          "organizations/${ancestor_id}" \
          "OPS_FOUNDATION_REVIEWED_IAM_BINDINGS"
        ;;
      *)
        fail "unexpected ancestor type after validation: ${ancestor_type}"
        ;;
    esac
  done < <(
    jq -r '.[] | [.type, (.id | tostring)] | @tsv' <<<"$ancestors_json"
  )
}

verify_canonical_repository_governance() {
  if [[ -f "$GOVERNANCE_MANIFEST" && -f "$GOVERNANCE_VERIFIER" ]]; then
    require_command uv
    require_command gh
    (
      cd "$REPO_ROOT"
      uv run \
        --no-project \
        --with pyyaml==6.0.3 \
        python "$GOVERNANCE_VERIFIER" --live
    )
  elif [[ -e "$GOVERNANCE_MANIFEST" || -e "$GOVERNANCE_VERIFIER" ]]; then
    fail "canonical repository governance manifest and verifier must land together"
  else
    printf '%s\n' \
      "INFO: canonical repository-governance files are not present on this branch; GitHub environment policy is intentionally not claimed here."
  fi
}

verify_service_account_has_no_user_keys() {
  local service_account="$1"
  local user_key_count

  gcloud iam service-accounts describe \
    "$service_account" \
    --project "$PROJECT_ID" \
    --format=none
  user_key_count="$(
    gcloud iam service-accounts keys list \
      --iam-account "$service_account" \
      --managed-by=user \
      --format='value(name)' | wc -l | tr -d ' '
  )"
  [[ "$user_key_count" == "0" ]] ||
    fail "user-managed key exists for ${service_account}"
}

verify_runtime_secret_policy() {
  local secret_name="$1"
  local expected_runtime="$2"
  local policy_json

  gcloud secrets describe \
    "$secret_name" \
    --project "$PROJECT_ID" \
    --format=none
  policy_json="$(
    gcloud secrets get-iam-policy \
      "$secret_name" \
      --project "$PROJECT_ID" \
      --format=json
  )"
  python3 "$CONTRACT_SCRIPT" secret-policy \
    --expected-member "serviceAccount:${expected_runtime}" \
    <<<"$policy_json"
}

verify_live_contract() {
  local enabled_apis
  local artifact_json
  local bucket_json
  local bucket_policy
  local project_json
  local project_number
  local state_object_json
  local project_policy
  local repository_policy
  local production_runtime_policy
  local preview_runtime_policy
  local preview_deployer_policy
  local production_deployer_policy
  local pool_json
  local listed_providers_json
  local preview_provider_json
  local production_provider_json
  local service_account
  local deployer
  local secret_name

  for command_name in gcloud jq python3; do
    require_command "$command_name"
  done
  [[ -n "${OPS_FOUNDATION_REVIEWED_IAM_BINDINGS:-}" ]] ||
    fail "OPS_FOUNDATION_REVIEWED_IAM_BINDINGS must be an exact reviewed JSON scope/role/member inventory"
  [[ -n "${OPS_FOUNDATION_REVIEWED_STATE_BUCKET_BINDINGS:-}" ]] ||
    fail "OPS_FOUNDATION_REVIEWED_STATE_BUCKET_BINDINGS must be an exact reviewed JSON bucket binding inventory"

  project_json="$(
    gcloud projects describe "$PROJECT_ID" --format=json
  )"
  project_number="$(
    jq -er '.projectNumber | tostring' <<<"$project_json"
  )"
  [[ "$project_number" == "$EXPECTED_PROJECT_NUMBER" ]] ||
    fail "live project number does not match the reviewed project inventory"

  enabled_apis="$(
    gcloud services list \
      --enabled \
      --project "$PROJECT_ID" \
      --format='value(config.name)'
  )"
  for api in "${REQUIRED_APIS[@]}"; do
    grep -Fxq "$api" <<<"$enabled_apis" || fail "API is not enabled: ${api}"
  done

  artifact_json="$(
    gcloud artifacts repositories describe agent \
      --project "$PROJECT_ID" \
      --location "$REGION" \
      --format=json
  )"
  jq -e \
    --arg expected_name "projects/${PROJECT_ID}/locations/${REGION}/repositories/agent" \
    '.name == $expected_name and .dockerConfig.immutableTags == true' \
    >/dev/null <<<"$artifact_json" ||
    fail "Artifact Registry name, region, or immutable-tags setting is incorrect"

  bucket_json="$(
    gcloud storage buckets describe \
      "gs://${STATE_BUCKET}" \
      --format=json
  )"
  verify_state_bucket_metadata <<<"$bucket_json"

  state_object_json="$(
    gcloud storage objects describe \
      "gs://${STATE_BUCKET}/${STATE_OBJECT}" \
      --format=json
  )"
  jq -e \
    --arg expected_name "$STATE_OBJECT" \
    '.name == $expected_name and ((.generation | tonumber) > 0) and ((.size | tonumber) > 0)' \
    >/dev/null <<<"$state_object_json" ||
    fail "remote Terraform state object path, generation, or size is invalid"

  bucket_policy="$(
    gcloud storage buckets get-iam-policy \
      "gs://${STATE_BUCKET}" \
      --format=json
  )"
  audit_iam_policy \
    "$bucket_policy" \
    "buckets/${STATE_BUCKET}" \
    "OPS_FOUNDATION_REVIEWED_STATE_BUCKET_BINDINGS" \
    true

  for service_account in \
    "$PRODUCTION_RUNTIME_SA" \
    "$PREVIEW_RUNTIME_SA" \
    "$PREVIEW_DEPLOYER_SA" \
    "$PRODUCTION_DEPLOYER_SA"; do
    verify_service_account_has_no_user_keys "$service_account"
  done

  project_policy="$(
    gcloud projects get-iam-policy "$PROJECT_ID" --format=json
  )"
  audit_iam_policy \
    "$project_policy" \
    "projects/${PROJECT_ID}" \
    "OPS_FOUNDATION_REVIEWED_IAM_BINDINGS"
  verify_ancestor_policies
  for inherited_role in \
    "roles/iam.serviceAccountUser" \
    "roles/iam.serviceAccountTokenCreator" \
    "roles/secretmanager.secretAccessor" \
    "roles/secretmanager.admin"; do
    assert_policy_lacks_role \
      "$project_policy" \
      "$inherited_role" \
      "project-wide ${inherited_role} would bypass resource-scoped identity boundaries"
  done

  repository_policy="$(
    gcloud artifacts repositories get-iam-policy agent \
      --project "$PROJECT_ID" \
      --location "$REGION" \
      --format=json
  )"
  audit_iam_policy \
    "$repository_policy" \
    "projects/${PROJECT_ID}/locations/${REGION}/repositories/agent" \
    "OPS_FOUNDATION_REVIEWED_IAM_BINDINGS"
  for repository_role in \
    "roles/artifactregistry.reader" \
    "roles/artifactregistry.writer"; do
    assert_policy_lacks_role \
      "$repository_policy" \
      "$repository_role" \
      "foundation Artifact Registry must not have a direct ${repository_role} binding before the reviewed builder/image-pull identities exist"
  done
  for deployer in "$PREVIEW_DEPLOYER_SA" "$PRODUCTION_DEPLOYER_SA"; do
    assert_member_has_no_direct_roles \
      "$project_policy" \
      "serviceAccount:${deployer}" \
      "${deployer} must not hold any direct project-level role"
    assert_member_has_no_direct_roles \
      "$repository_policy" \
      "serviceAccount:${deployer}" \
      "${deployer} must not hold any direct Artifact Registry role"
    assert_policy_lacks_member \
      "$project_policy" \
      "roles/run.admin" \
      "serviceAccount:${deployer}" \
      "${deployer} still has project-wide Cloud Run admin"
    assert_policy_lacks_member \
      "$project_policy" \
      "roles/artifactregistry.writer" \
      "serviceAccount:${deployer}" \
      "${deployer} still has project-wide image-writer access"
    assert_policy_lacks_member \
      "$repository_policy" \
      "roles/artifactregistry.writer" \
      "serviceAccount:${deployer}" \
      "${deployer} still has repository image-writer access"
    assert_policy_lacks_member \
      "$project_policy" \
      "roles/secretmanager.secretAccessor" \
      "serviceAccount:${deployer}" \
      "${deployer} must not read runtime secrets"
  done
  for service_account in "$PRODUCTION_RUNTIME_SA" "$PREVIEW_RUNTIME_SA"; do
    assert_member_has_no_direct_roles \
      "$project_policy" \
      "serviceAccount:${service_account}" \
      "${service_account} must not hold any direct project-level role"
    assert_member_has_no_direct_roles \
      "$repository_policy" \
      "serviceAccount:${service_account}" \
      "${service_account} must not hold any direct Artifact Registry role"
    assert_policy_lacks_member \
      "$project_policy" \
      "roles/secretmanager.secretAccessor" \
      "serviceAccount:${service_account}" \
      "${service_account} must receive secret access on exact secrets, not the project"
  done

  production_runtime_policy="$(
    gcloud iam service-accounts get-iam-policy \
      "$PRODUCTION_RUNTIME_SA" \
      --project "$PROJECT_ID" \
      --format=json
  )"
  preview_runtime_policy="$(
    gcloud iam service-accounts get-iam-policy \
      "$PREVIEW_RUNTIME_SA" \
      --project "$PROJECT_ID" \
      --format=json
  )"
  assert_exact_role_member \
    "$production_runtime_policy" \
    "roles/iam.serviceAccountUser" \
    "serviceAccount:${PRODUCTION_DEPLOYER_SA}" \
    "only the production deployer may act as the production runtime"
  assert_exact_role_member \
    "$preview_runtime_policy" \
    "roles/iam.serviceAccountUser" \
    "serviceAccount:${PREVIEW_DEPLOYER_SA}" \
    "only the preview deployer may act as the preview runtime"
  assert_policy_lacks_role \
    "$production_runtime_policy" \
    "roles/iam.serviceAccountTokenCreator" \
    "production runtime must not expose a direct token-creator escalation path"
  assert_policy_lacks_role \
    "$preview_runtime_policy" \
    "roles/iam.serviceAccountTokenCreator" \
    "preview runtime must not expose a direct token-creator escalation path"
  assert_policy_has_no_public_members \
    "$production_runtime_policy" \
    "production runtime IAM must not trust public principals"
  assert_policy_has_no_public_members \
    "$preview_runtime_policy" \
    "preview runtime IAM must not trust public principals"
  assert_policy_roles_exactly \
    "$production_runtime_policy" \
    "roles/iam.serviceAccountUser" \
    "production runtime must expose only its reviewed direct act-as role"
  assert_policy_roles_exactly \
    "$preview_runtime_policy" \
    "roles/iam.serviceAccountUser" \
    "preview runtime must expose only its reviewed direct act-as role"

  for secret_name in "${PRODUCTION_SECRET_NAMES[@]}"; do
    verify_runtime_secret_policy "$secret_name" "$PRODUCTION_RUNTIME_SA"
  done
  for secret_name in "${PREVIEW_SECRET_NAMES[@]}"; do
    verify_runtime_secret_policy "$secret_name" "$PREVIEW_RUNTIME_SA"
  done

  pool_json="$(
    gcloud iam workload-identity-pools describe github \
      --project "$PROJECT_ID" \
      --location global \
      --format=json
  )"
  listed_providers_json="$(
    gcloud iam workload-identity-pools providers list \
      --project "$PROJECT_ID" \
      --location global \
      --workload-identity-pool github \
      --format=json
  )"
  preview_provider_json="$(
    gcloud iam workload-identity-pools providers describe github-preview \
      --project "$PROJECT_ID" \
      --location global \
      --workload-identity-pool github \
      --format=json
  )"
  production_provider_json="$(
    gcloud iam workload-identity-pools providers describe github-production \
      --project "$PROJECT_ID" \
      --location global \
      --workload-identity-pool github \
      --format=json
  )"
  jq -cn \
    --argjson pool "$pool_json" \
    --argjson listed "$listed_providers_json" \
    --argjson preview "$preview_provider_json" \
    --argjson production "$production_provider_json" \
    '{
      pool: $pool,
      listed: $listed,
      described: [$preview, $production]
    }' |
    python3 "$CONTRACT_SCRIPT" wif-live

  preview_deployer_policy="$(
    gcloud iam service-accounts get-iam-policy \
      "$PREVIEW_DEPLOYER_SA" \
      --project "$PROJECT_ID" \
      --format=json
  )"
  production_deployer_policy="$(
    gcloud iam service-accounts get-iam-policy \
      "$PRODUCTION_DEPLOYER_SA" \
      --project "$PROJECT_ID" \
      --format=json
  )"
  assert_exact_role_member \
    "$preview_deployer_policy" \
    "roles/iam.workloadIdentityUser" \
    "principalSet://iam.googleapis.com/projects/${project_number}/locations/global/workloadIdentityPools/github/attribute.environment/Preview" \
    "preview deployer must trust only the Preview environment principal set"
  assert_exact_role_member \
    "$production_deployer_policy" \
    "roles/iam.workloadIdentityUser" \
    "principalSet://iam.googleapis.com/projects/${project_number}/locations/global/workloadIdentityPools/github/attribute.environment/Production" \
    "production deployer must trust only the Production environment principal set"
  assert_policy_has_no_public_members \
    "$preview_deployer_policy" \
    "preview deployer IAM must not trust public principals"
  assert_policy_has_no_public_members \
    "$production_deployer_policy" \
    "production deployer IAM must not trust public principals"
  assert_policy_roles_exactly \
    "$preview_deployer_policy" \
    "roles/iam.workloadIdentityUser" \
    "preview deployer must expose only its reviewed direct federation role"
  assert_policy_roles_exactly \
    "$production_deployer_policy" \
    "roles/iam.workloadIdentityUser" \
    "production deployer must expose only its reviewed direct federation role"

  verify_canonical_repository_governance

  printf 'OK: live GCP foundation metadata, ancestor IAM, and keyless constraints verified for project %s (%s).\n' \
    "$PROJECT_ID" "$project_number"
}

usage() {
  printf '%s\n' \
    "Usage: ${0##*/} [--static|--terraform-fmt|--terraform-init|" \
    "  --terraform-validate|--terraform-test|--state-bucket-metadata|" \
    "  --live|--governance-live]"
}

mode="${1:---live}"
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
  --live)
    verify_static_contract
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
