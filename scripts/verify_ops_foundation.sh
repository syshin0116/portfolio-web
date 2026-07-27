#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ID="festive-ally-503605-v7"
readonly EXPECTED_PROJECT_NUMBER="72919926064"
readonly REGION="us-east4"
readonly REPOSITORY="syshin0116/syshin0116.dev"
readonly REQUIRED_REVIEWER_ID="99532836"
readonly EXPECTED_PREVIEW_LIVE_CONDITION="assertion.repository_id == '1102380057' && assertion.repository_owner_id == '99532836' && assertion.event_name == 'pull_request' && assertion.environment == 'Preview'"
readonly EXPECTED_PRODUCTION_LIVE_CONDITION="assertion.repository_id == '1102380057' && assertion.repository_owner_id == '99532836' && assertion.event_name == 'push' && assertion.ref == 'refs/heads/main' && assertion.environment == 'Production'"
readonly EXPECTED_PREVIEW_TERRAFORM_CONDITION="preview_wif_attribute_condition = \"assertion.repository_id == '\${var.github_repository_id}' && assertion.repository_owner_id == '\${var.github_owner_id}' && assertion.event_name == 'pull_request' && assertion.environment == '\${var.github_preview_environment}'\""
readonly EXPECTED_PRODUCTION_TERRAFORM_CONDITION="production_wif_attribute_condition = \"assertion.repository_id == '\${var.github_repository_id}' && assertion.repository_owner_id == '\${var.github_owner_id}' && assertion.event_name == 'push' && assertion.ref == 'refs/heads/main' && assertion.environment == '\${var.github_production_environment}'\""
readonly EXPECTED_IAM_RESOURCE_DECLARATIONS=$'google_secret_manager_secret_iam_member.preview_runtime_accessor\ngoogle_secret_manager_secret_iam_member.runtime_accessor\ngoogle_service_account_iam_member.deployer_uses_runtime\ngoogle_service_account_iam_member.github_preview\ngoogle_service_account_iam_member.github_production'
readonly EXPECTED_IAM_RESOURCE_TYPE_TOKENS=$'google_secret_manager_secret_iam_member\ngoogle_secret_manager_secret_iam_member\ngoogle_service_account_iam_member\ngoogle_service_account_iam_member\ngoogle_service_account_iam_member'
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

require_fragment() {
  local file_path="$1"
  local fragment="$2"
  local description="$3"

  grep -Fq -- "$fragment" "$file_path" || fail "$description"
}

require_exact_trimmed_line_once() {
  local file_path="$1"
  local expected_line="$2"
  local description="$3"
  local match_count

  match_count="$(
    awk -v expected="$expected_line" '
      {
        candidate = $0
        sub(/^[[:space:]]+/, "", candidate)
        sub(/[[:space:]]+$/, "", candidate)
        gsub(/[[:space:]]+=[[:space:]]+/, " = ", candidate)
        if (candidate == expected) {
          count += 1
        }
      }
      END { print count + 0 }
    ' "$file_path"
  )"
  [[ "$match_count" == "1" ]] || fail "$description"
}

forbid_terraform_pattern() {
  local pattern="$1"
  local description="$2"

  if grep -En -- "$pattern" "${TERRAFORM_DIR}"/*.tf >/dev/null; then
    fail "$description"
  fi
}

verify_exact_iam_resource_declarations() {
  local actual_declarations
  local actual_type_tokens

  actual_declarations="$(
    grep -Eh \
      '^[[:space:]]*resource "google_[^"]*_iam_(member|binding|policy)" "[^"]+"[[:space:]]*\{' \
      "${TERRAFORM_DIR}"/*.tf |
      sed -E \
        's/^[[:space:]]*resource "([^"]+)" "([^"]+)".*$/\1.\2/' |
      LC_ALL=C sort
  )"
  [[ "$actual_declarations" == "$EXPECTED_IAM_RESOURCE_DECLARATIONS" ]] ||
    fail "Terraform IAM resources must exactly match the reviewed additive-member allowlist"

  actual_type_tokens="$(
    grep -Eho \
      'google_[[:alnum:]_]+_iam_(member|binding|policy)' \
      "${TERRAFORM_DIR}"/*.tf |
      LC_ALL=C sort
  )"
  [[ "$actual_type_tokens" == "$EXPECTED_IAM_RESOURCE_TYPE_TOKENS" ]] ||
    fail "Terraform IAM resource type tokens must exactly match the reviewed allowlist"
}

verify_static_contract() {
  require_fragment \
    "${TERRAFORM_DIR}/main.tf" \
    "immutable_tags = true" \
    "Artifact Registry immutable tags are not enforced"
  require_exact_trimmed_line_once \
    "${TERRAFORM_DIR}/main.tf" \
    "$EXPECTED_PREVIEW_TERRAFORM_CONDITION" \
    "preview WIF CEL condition must exactly match the fail-closed contract"
  require_exact_trimmed_line_once \
    "${TERRAFORM_DIR}/main.tf" \
    "$EXPECTED_PRODUCTION_TERRAFORM_CONDITION" \
    "production WIF CEL condition must exactly match the fail-closed contract"
  require_exact_trimmed_line_once \
    "${TERRAFORM_DIR}/main.tf" \
    "attribute_condition = local.preview_wif_attribute_condition" \
    "preview provider must use only the reviewed CEL condition"
  require_exact_trimmed_line_once \
    "${TERRAFORM_DIR}/main.tf" \
    "attribute_condition = local.production_wif_attribute_condition" \
    "production provider must use only the reviewed CEL condition"
  require_fragment \
    "${TERRAFORM_DIR}/main.tf" \
    'account_id   = "agent-preview-runtime"' \
    "preview runtime service account is missing"
  require_fragment \
    "${TERRAFORM_DIR}/iam.tf" \
    "service_account_id = local.runtime_service_account_ids[each.key]" \
    "deployers are not mapped to their environment-specific runtime"
  require_fragment \
    "${TERRAFORM_DIR}/iam.tf" \
    "preview    = google_service_account.preview_runtime.name" \
    "preview deployer does not act as the preview runtime"
  require_fragment \
    "${TERRAFORM_DIR}/iam.tf" \
    "production = google_service_account.runtime.name" \
    "production deployer does not act as the production runtime"
  require_fragment \
    "${TERRAFORM_DIR}/iam.tf" \
    "projects/\${data.google_project.current.number}/locations/global/workloadIdentityPools/" \
    "WIF principal sets must derive the project number from the current GCP project"
  require_fragment \
    "${TERRAFORM_DIR}/iam.tf" \
    'resource "google_secret_manager_secret_iam_member" "preview_runtime_accessor"' \
    "preview secret accessor bindings are missing"
  require_fragment \
    "${TERRAFORM_DIR}/state.tf" \
    "force_destroy               = false" \
    "state bucket force_destroy must remain disabled"
  require_fragment \
    "${TERRAFORM_DIR}/state.tf" \
    'public_access_prevention    = "enforced"' \
    "state bucket public access prevention is missing"
  require_fragment \
    "${TERRAFORM_DIR}/state.tf" \
    "uniform_bucket_level_access = true" \
    "state bucket uniform access is missing"
  require_fragment \
    "${TERRAFORM_DIR}/state.tf" \
    "enabled = true" \
    "state bucket versioning is missing"
  require_fragment \
    "${TERRAFORM_DIR}/state.tf" \
    "prevent_destroy = true" \
    "state bucket lifecycle must prevent destroy"
  require_fragment \
    "${TERRAFORM_DIR}/backend.tf" \
    'bucket = "festive-ally-503605-v7-tfstate"' \
    "the hardened state backend is not configured"
  require_exact_trimmed_line_once \
    "${TERRAFORM_DIR}/versions.tf" \
    'required_version = "= 1.13.5"' \
    "Terraform must be pinned exactly to 1.13.5"
  require_fragment \
    "${TERRAFORM_DIR}/versions.tf" \
    'data "google_project" "current"' \
    "the project number must come from google_project.current"
  [[ "$(<"${TERRAFORM_DIR}/.terraform-version")" == "1.13.5" ]] ||
    fail "infra/gcp/.terraform-version must pin Terraform 1.13.5"

  forbid_terraform_pattern \
    'roles/run\.admin' \
    "foundation deployers must not receive project-wide roles/run.admin"
  forbid_terraform_pattern \
    'roles/artifactregistry\.writer' \
    "foundation deployers must not build or push images; add a separate builder later"
  forbid_terraform_pattern \
    'resource[[:space:]]+"google_service_account_key"' \
    "user-managed service-account keys are forbidden"
  forbid_terraform_pattern \
    'resource[[:space:]]+"google_secret_manager_secret_version"' \
    "Terraform must not manage secret payload versions"
  forbid_terraform_pattern \
    'private_key|private_key_data|service_account_key' \
    "credential material must not enter Terraform configuration"
  forbid_terraform_pattern \
    'variable[[:space:]]+"project_number"|var\.project_number' \
    "the project number must not be independently overridden"
  verify_exact_iam_resource_declarations

  printf 'OK: credential-free Terraform security contract verified.\n'
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
  assert_exact_role_member \
    "$policy_json" \
    "roles/secretmanager.secretAccessor" \
    "serviceAccount:${expected_runtime}" \
    "${secret_name} must have exactly one environment-specific runtime accessor"
  assert_policy_lacks_role \
    "$policy_json" \
    "roles/secretmanager.admin" \
    "${secret_name} must not grant direct Secret Manager admin"
  assert_policy_has_no_public_members \
    "$policy_json" \
    "${secret_name} must not grant any role to public principals"
}

verify_live_contract() {
  local enabled_apis
  local artifact_json
  local bucket_json
  local project_json
  local project_number
  local state_object_json
  local project_policy
  local repository_policy
  local production_runtime_policy
  local preview_runtime_policy
  local preview_deployer_policy
  local production_deployer_policy
  local preview_provider_json
  local production_provider_json
  local preview_reviewer_ids
  local production_reviewer_ids
  local production_branches
  local service_account
  local deployer
  local secret_name

  for command_name in gcloud gh jq; do
    require_command "$command_name"
  done

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
  jq -e '
    (.public_access_prevention // .iamConfiguration.publicAccessPrevention) == "enforced"
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
    fail "state bucket must enforce public-access prevention, uniform access, versioning, and 30-day soft delete"

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
  assert_policy_has_no_public_members \
    "$project_policy" \
    "project IAM policy must not grant roles to public principals"
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
  assert_policy_has_no_public_members \
    "$repository_policy" \
    "Artifact Registry policy must not grant roles to public principals"
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

  jq -e \
    --arg condition "$EXPECTED_PREVIEW_LIVE_CONDITION" \
    '
      .attributeCondition == $condition
      and .oidc.issuerUri == "https://token.actions.githubusercontent.com"
      and .attributeMapping == {
        "attribute.environment": "assertion.environment",
        "attribute.event_name": "assertion.event_name",
        "attribute.ref": "assertion.ref",
        "attribute.repository_id": "assertion.repository_id",
        "attribute.repository_owner_id": "assertion.repository_owner_id",
        "google.subject": "assertion.sub"
      }
    ' >/dev/null <<<"$preview_provider_json" ||
    fail "preview provider condition, issuer, or attribute mapping is not exact"
  jq -e \
    --arg condition "$EXPECTED_PRODUCTION_LIVE_CONDITION" \
    '
      .attributeCondition == $condition
      and .oidc.issuerUri == "https://token.actions.githubusercontent.com"
      and .attributeMapping == {
        "attribute.environment": "assertion.environment",
        "attribute.event_name": "assertion.event_name",
        "attribute.ref": "assertion.ref",
        "attribute.repository_id": "assertion.repository_id",
        "attribute.repository_owner_id": "assertion.repository_owner_id",
        "google.subject": "assertion.sub"
      }
    ' >/dev/null <<<"$production_provider_json" ||
    fail "production provider condition, issuer, or attribute mapping is not exact"

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

  preview_reviewer_ids="$(
    gh api "repos/${REPOSITORY}/environments/Preview" \
      --jq '[.protection_rules[]? | select(.type == "required_reviewers") | .reviewers[]? | .reviewer.id] | unique | sort | map(tostring) | join("\n")'
  )"
  production_reviewer_ids="$(
    gh api "repos/${REPOSITORY}/environments/Production" \
      --jq '[.protection_rules[]? | select(.type == "required_reviewers") | .reviewers[]? | .reviewer.id] | unique | sort | map(tostring) | join("\n")'
  )"
  [[ -z "$preview_reviewer_ids" ]] ||
    fail "Preview must not require the sole repository owner to self-approve PR deployments"
  [[ "$production_reviewer_ids" == "$REQUIRED_REVIEWER_ID" ]] ||
    fail "Production required reviewers do not exactly match the repository owner"

  production_branches="$(
    gh api "repos/${REPOSITORY}/environments/Production/deployment-branch-policies" \
      --jq '[.branch_policies[]?.name] | join("\n")'
  )"
  grep -Fxq main <<<"$production_branches" ||
    fail "Production does not restrict deployment to main"

  printf 'OK: live GCP/GitHub foundation metadata and keyless constraints verified for project %s (%s).\n' \
    "$PROJECT_ID" "$project_number"
}

usage() {
  printf 'Usage: %s [--static|--live]\n' "${0##*/}"
}

mode="${1:---live}"
case "$mode" in
  --static)
    verify_static_contract
    ;;
  --live)
    verify_static_contract
    verify_live_contract
    ;;
  -h | --help)
    usage
    ;;
  *)
    usage >&2
    fail "unknown mode: ${mode}"
    ;;
esac
