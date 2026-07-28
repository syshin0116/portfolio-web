#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ID="festive-ally-503605-v7"
readonly EXPECTED_PROJECT_NUMBER="72919926064"
readonly REGION="us-east4"
readonly STATE_BUCKET="${PROJECT_ID}-tfstate"
readonly STATE_OBJECT="syshin0116.dev/gcp/foundation/default.tfstate"
readonly PRODUCTION_RUNTIME_SA="agent-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PREVIEW_RUNTIME_SA="agent-preview-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PREVIEW_DEPLOYER_SA="agent-preview-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PRODUCTION_DEPLOYER_SA="agent-prod-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
readonly BUILDER_SA="agent-image-builder@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PREVIEW_BUILDER_SA="agent-preview-image-builder@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PREVIEW_MIGRATOR_SA="agent-preview-migrator@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PRODUCTION_MIGRATOR_SA="agent-prod-migrator@${PROJECT_ID}.iam.gserviceaccount.com"
readonly MAINTENANCE_SCHEDULER_SA="agent-maintenance-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"
readonly CLOUD_RUN_SERVICE_AGENT="service-${EXPECTED_PROJECT_NUMBER}@serverless-robot-prod.iam.gserviceaccount.com"
readonly CLOUD_SCHEDULER_SERVICE_AGENT="service-${EXPECTED_PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
readonly CLOUD_RUN_DELIVERY_ROLE="projects/${PROJECT_ID}/roles/cloudRunAgentDelivery"
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
readonly GOVERNANCE_MANIFEST="${REPO_ROOT}/.github/repository-governance.json"
readonly GOVERNANCE_VERIFIER="${REPO_ROOT}/scripts/verify_repository_governance.py"

readonly REQUIRED_APIS=(
  artifactregistry.googleapis.com
  cloudscheduler.googleapis.com
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
)

readonly PREVIEW_SECRET_NAMES=(
  agent-preview-anthropic-api-key
  agent-preview-auth-secret
  agent-preview-database-url
  agent-preview-langsmith-api-key
)

readonly PREVIEW_MIGRATION_SECRET="agent-preview-migration-database-url"
readonly PRODUCTION_MIGRATION_SECRET="agent-migration-database-url"

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

verify_artifact_repository_metadata() {
  local repository_json
  local repository_id="$1"
  local delete_policy_id="$2"
  local delete_after="$3"
  local keep_policy_id="$4"
  local keep_count="$5"

  require_command jq
  repository_json="$(cat)"
  jq -e \
    --arg expected_name "projects/${PROJECT_ID}/locations/${REGION}/repositories/${repository_id}" \
    --arg delete_policy_id "$delete_policy_id" \
    --arg delete_after "$delete_after" \
    --arg keep_policy_id "$keep_policy_id" \
    --argjson keep_count "$keep_count" \
    '
      .name == $expected_name
      and (.dockerConfig.immutableTags // false) == false
      and (.cleanupPolicyDryRun // false) == false
      and ((.cleanupPolicies // {}) | keys | sort) == ([$delete_policy_id, $keep_policy_id] | sort)
      and .cleanupPolicies[$delete_policy_id].action == "DELETE"
      and (.cleanupPolicies[$delete_policy_id].id // $delete_policy_id) == $delete_policy_id
      and (.cleanupPolicies[$delete_policy_id].condition.tagState // "ANY") == "ANY"
      and .cleanupPolicies[$delete_policy_id].condition.olderThan == $delete_after
      and (.cleanupPolicies[$delete_policy_id].condition.packageNamePrefixes // []) == []
      and (.cleanupPolicies[$delete_policy_id].condition.tagPrefixes // []) == []
      and (.cleanupPolicies[$delete_policy_id].condition.versionNamePrefixes // []) == []
      and (.cleanupPolicies[$delete_policy_id].condition | has("newerThan") | not)
      and .cleanupPolicies[$keep_policy_id].action == "KEEP"
      and (.cleanupPolicies[$keep_policy_id].id // $keep_policy_id) == $keep_policy_id
      and (.cleanupPolicies[$keep_policy_id].mostRecentVersions.keepCount | tonumber) == $keep_count
      and (.cleanupPolicies[$keep_policy_id].mostRecentVersions.packageNamePrefixes // []) == []
    ' >/dev/null <<<"$repository_json" ||
    fail "Artifact Registry ${repository_id} identity, mutable-tag setting, or active cleanup retention policy drifted"
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

assert_policy_binding_pairs_exactly() {
  local policy_json="$1"
  local expected_pairs_json="$2"
  local description="$3"

  jq -e \
    --argjson expected_pairs "$expected_pairs_json" \
    '
      ([.bindings[]? | select(has("condition"))] | length == 0)
      and (
        [
          .bindings[]?
          | .role as $role
          | .members[]?
          | {role: $role, member: .}
        ]
        | unique_by([.role, .member])
        | sort_by(.role, .member)
      ) == (
        $expected_pairs
        | unique_by([.role, .member])
        | sort_by(.role, .member)
      )
    ' >/dev/null <<<"$policy_json" || fail "$description"
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

assert_workload_accounts_have_no_direct_roles() {
  local policy_json="$1"
  local scope="$2"
  local ancestors_json="$3"
  local principal_sets
  local principal_set
  local service_account

  for service_account in "${WORKLOAD_SERVICE_ACCOUNTS[@]}"; do
    assert_member_has_no_direct_roles \
      "$policy_json" \
      "serviceAccount:${service_account}" \
      "${service_account} must not inherit a direct role from ${scope}"
  done

  principal_sets="$(
    jq -er \
      --arg project_number "$EXPECTED_PROJECT_NUMBER" \
      '
        [
          "principalSet://cloudresourcemanager.googleapis.com/projects/\($project_number)/type/ServiceAccount",
          (
            .[]
            | select(.type == "folder" or .type == "organization")
            | "principalSet://cloudresourcemanager.googleapis.com/\(
                if .type == "folder" then "folders" else "organizations" end
              )/\(.id | tostring)/type/ServiceAccount"
          )
        ]
        | unique[]
      ' <<<"$ancestors_json"
  )" || fail "validated ancestor inventory could not produce service-account principal sets"

  while IFS= read -r principal_set; do
    assert_member_has_no_direct_roles \
      "$policy_json" \
      "$principal_set" \
      "${principal_set} includes the workload service accounts and must not hold a direct role on ${scope}"
  done <<<"$principal_sets"
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

read_project_ancestors() {
  local ancestors_json

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

  printf '%s\n' "$ancestors_json"
}

verify_ancestor_policies() {
  local ancestors_json="$1"
  local ancestor_type
  local ancestor_id
  local policy_json

  while IFS=$'\t' read -r ancestor_type ancestor_id; do
    case "$ancestor_type" in
      project)
        continue
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
    assert_workload_accounts_have_no_direct_roles \
      "$policy_json" \
      "${ancestor_type}s/${ancestor_id}" \
      "$ancestors_json"
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
      uv run --frozen --package syshin0116-dev-agent \
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

verify_project_has_no_user_managed_service_account_keys() {
  local service_accounts_json
  local service_account

  service_accounts_json="$(
    gcloud iam service-accounts list \
      --project "$PROJECT_ID" \
      --format=json
  )"
  jq -e \
    '
      type == "array"
      and length > 0
      and all(.[];
        type == "object"
        and (.email | type == "string" and length > 0)
      )
      and ([.[].email] | length) == ([.[].email] | unique | length)
    ' >/dev/null <<<"$service_accounts_json" ||
    fail "project service-account inventory is empty, duplicate, or unreadable"

  for service_account in "${WORKLOAD_SERVICE_ACCOUNTS[@]}"; do
    jq -e \
      --arg expected_email "$service_account" \
      'any(.[]; .email == $expected_email)' \
      >/dev/null <<<"$service_accounts_json" ||
      fail "managed workload service account is absent from project inventory: ${service_account}"
  done

  while IFS= read -r service_account; do
    verify_service_account_has_no_user_keys "$service_account"
  done < <(jq -r '.[].email' <<<"$service_accounts_json")
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

verify_service_account_act_as_policy() {
  local service_account="$1"
  local expected_deployer="$2"
  local description="$3"
  local policy_json
  local expected_pairs

  policy_json="$(
    gcloud iam service-accounts get-iam-policy \
      "$service_account" \
      --project "$PROJECT_ID" \
      --format=json
  )"
  expected_pairs="$(
    jq -cn \
      --arg member "serviceAccount:${expected_deployer}" \
      '[{role: "roles/iam.serviceAccountUser", member: $member}]'
  )"
  assert_policy_binding_pairs_exactly \
    "$policy_json" \
    "$expected_pairs" \
    "$description"
  assert_policy_has_no_public_members \
    "$policy_json" \
    "${service_account} IAM must not trust public principals"
}

verify_cloud_run_service() {
  local service_name="$1"
  local runtime_service_account="$2"
  local deployer_service_account="$3"
  local service_json
  local policy_json
  local expected_pairs
  local expected_secret_names

  case "$service_name" in
    agent-preview)
      expected_secret_names="$(
        printf '%s\n' "${PREVIEW_SECRET_NAMES[@]}" | jq -R . | jq -s .
      )"
      ;;
    agent)
      expected_secret_names="$(
        printf '%s\n' "${PRODUCTION_SECRET_NAMES[@]}" | jq -R . | jq -s .
      )"
      ;;
    *)
      fail "unexpected Cloud Run service in live verifier: ${service_name}"
      ;;
  esac

  service_json="$(
    gcloud run services describe \
      "$service_name" \
      --project "$PROJECT_ID" \
      --region "$REGION" \
      --format=json
  )"
  jq -e \
    --arg service_name "$service_name" \
    --arg runtime_service_account "$runtime_service_account" \
    --argjson expected_secret_names "$expected_secret_names" \
    '
      def secret_name:
        .valueFrom.secretKeyRef.name
        // .valueSource.secretKeyRef.secret
        // empty;
      def secret_version:
        .valueFrom.secretKeyRef.key
        // .valueSource.secretKeyRef.version
        // empty;

      .metadata.name == $service_name
      and .spec.template.spec.serviceAccountName == $runtime_service_account
      and .spec.template.spec.containerConcurrency == 8
      and .spec.template.spec.timeoutSeconds == 300
      and .spec.template.metadata.annotations["autoscaling.knative.dev/maxScale"] == "1"
      and .spec.template.metadata.annotations["run.googleapis.com/execution-environment"] == "gen2"
      and (.spec.template.spec.containers | length) == 1
      and .spec.template.spec.containers[0].command == ["uvicorn"]
      and .spec.template.spec.containers[0].args == [
        "aegra_api.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
        "--workers",
        "1"
      ]
      and (
        [
          .spec.template.spec.containers[0].env[]?
          | select((secret_name | length) > 0)
          | {name: secret_name, version: secret_version}
        ] as $secret_refs
        | ($secret_refs | length) == 4
          and ([$secret_refs[].name] | sort) == ($expected_secret_names | sort)
          and all(
            $secret_refs[];
            .version | type == "string" and test("^[1-9][0-9]*$")
          )
      )
    ' >/dev/null <<<"$service_json" ||
    fail "Cloud Run service ${service_name} runtime, limits, or numeric secret pins drifted"

  policy_json="$(
    gcloud run services get-iam-policy \
      "$service_name" \
      --project "$PROJECT_ID" \
      --region "$REGION" \
      --format=json
  )"
  expected_pairs="$(
    jq -cn \
      --arg deployer "serviceAccount:${deployer_service_account}" \
      --arg delivery_role "$CLOUD_RUN_DELIVERY_ROLE" \
      '[
        {role: $delivery_role, member: $deployer},
        {role: "roles/run.invoker", member: "allUsers"}
      ]'
  )"
  assert_policy_binding_pairs_exactly \
    "$policy_json" \
    "$expected_pairs" \
    "Cloud Run service ${service_name} IAM must contain only its deployer and public invoker"
}

verify_cloud_run_job() {
  local job_name="$1"
  local service_account="$2"
  local deployer_service_account="$3"
  local container_name="$4"
  local module_name="$5"
  local expected_secret_name="$6"
  local scheduler_service_account="${7:-}"
  local job_json
  local policy_json
  local expected_pairs

  job_json="$(
    gcloud run jobs describe \
      "$job_name" \
      --project "$PROJECT_ID" \
      --region "$REGION" \
      --format=json
  )"
  jq -e \
    --arg job_name "$job_name" \
    --arg service_account "$service_account" \
    --arg container_name "$container_name" \
    --arg module_name "$module_name" \
    --arg expected_secret_name "$expected_secret_name" \
    '
      def secret_name:
        .valueFrom.secretKeyRef.name
        // .valueSource.secretKeyRef.secret
        // empty;
      def secret_version:
        .valueFrom.secretKeyRef.key
        // .valueSource.secretKeyRef.version
        // empty;

      .metadata.name == $job_name
      and .spec.template.spec.template.spec.serviceAccountName == $service_account
      and .spec.template.spec.template.spec.maxRetries == 0
      and (.spec.template.spec.template.spec.containers | length) == 1
      and .spec.template.spec.template.spec.containers[0].name == $container_name
      and .spec.template.spec.template.spec.containers[0].command == ["python"]
      and .spec.template.spec.template.spec.containers[0].args == [
        "-m",
        $module_name
      ]
      and (
        [
          .spec.template.spec.template.spec.containers[0].env[]?
          | select((secret_name | length) > 0)
          | {name: secret_name, version: secret_version}
        ] == [
          {
            name: $expected_secret_name,
            version: (
              [
                .spec.template.spec.template.spec.containers[0].env[]?
                | select((secret_name | length) > 0)
                | secret_version
              ][0]
            )
          }
        ]
      )
      and all(
        [
          .spec.template.spec.template.spec.containers[0].env[]?
          | select((secret_name | length) > 0)
          | secret_version
        ][];
        type == "string" and test("^[1-9][0-9]*$")
      )
    ' >/dev/null <<<"$job_json" ||
    fail "Cloud Run job ${job_name} identity, command, or numeric secret pin drifted"

  policy_json="$(
    gcloud run jobs get-iam-policy \
      "$job_name" \
      --project "$PROJECT_ID" \
      --region "$REGION" \
      --format=json
  )"
  expected_pairs="$(
    jq -cn \
      --arg deployer "serviceAccount:${deployer_service_account}" \
      --arg delivery_role "$CLOUD_RUN_DELIVERY_ROLE" \
      --arg scheduler_service_account "$scheduler_service_account" \
      '
        [{role: $delivery_role, member: $deployer}]
        + if ($scheduler_service_account | length) > 0 then
            [{
              role: "roles/run.invoker",
              member: ("serviceAccount:" + $scheduler_service_account)
            }]
          else
            []
          end
      '
  )"
  assert_policy_binding_pairs_exactly \
    "$policy_json" \
    "$expected_pairs" \
    "Cloud Run job ${job_name} IAM must contain only its reviewed invokers"
  assert_policy_has_no_public_members \
    "$policy_json" \
    "Cloud Run job ${job_name} must not be publicly invokable"
}

verify_guest_maintenance_schedule() {
  local job_json
  local scheduler_policy

  job_json="$(
    gcloud scheduler jobs describe \
      agent-guest-maintenance \
      --project "$PROJECT_ID" \
      --location "$REGION" \
      --format=json
  )"
  jq -e \
    --arg expected_name "projects/${PROJECT_ID}/locations/${REGION}/jobs/agent-guest-maintenance" \
    --arg expected_scheduler "$MAINTENANCE_SCHEDULER_SA" \
    --arg expected_uri "https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/agent-maintenance:run" \
    '
      .name == $expected_name
      and .schedule == "*/15 * * * *"
      and .timeZone == "Etc/UTC"
      and .attemptDeadline == "60s"
      and .state == "ENABLED"
      and (.retryConfig.retryCount // 0) == 0
      and .httpTarget.httpMethod == "POST"
      and .httpTarget.uri == $expected_uri
      and .httpTarget.body == "e30="
      and .httpTarget.headers["Content-Type"] == "application/json"
      and (
        [
          .httpTarget.headers
          | keys[]
          | select(. != "Content-Type" and . != "User-Agent")
        ] | length
      ) == 0
      and .httpTarget.oauthToken.serviceAccountEmail == $expected_scheduler
      and .httpTarget.oauthToken.scope == "https://www.googleapis.com/auth/cloud-platform"
      and (.httpTarget | has("oidcToken") | not)
    ' >/dev/null <<<"$job_json" ||
    fail "Cloud Scheduler guest maintenance trigger drifted from its exact OAuth contract"

  scheduler_policy="$(
    gcloud iam service-accounts get-iam-policy \
      "$MAINTENANCE_SCHEDULER_SA" \
      --project "$PROJECT_ID" \
      --format=json
  )"
  assert_policy_binding_pairs_exactly \
    "$scheduler_policy" \
    "[]" \
    "maintenance scheduler identity must not expose impersonation bindings"
  assert_policy_has_no_public_members \
    "$scheduler_policy" \
    "maintenance scheduler identity must not trust public principals"
}

verify_live_contract() {
  local enabled_apis
  local artifact_json
  local preview_artifact_json
  local bucket_json
  local bucket_policy
  local project_json
  local project_number
  local ancestors_json
  local state_object_json
  local project_policy
  local repository_policy
  local role_json
  local preview_repository_policy
  local preview_deployer_policy
  local production_deployer_policy
  local builder_policy
  local preview_builder_policy
  local expected_pairs
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
  role_json="$(
    gcloud iam roles describe cloudRunAgentDelivery \
      --project "$PROJECT_ID" \
      --format=json
  )"
  jq -e \
    --arg expected_name "$CLOUD_RUN_DELIVERY_ROLE" \
    '
      .name == $expected_name
      and (.deleted // false) == false
      and .stage == "GA"
      and (.includedPermissions | sort) == [
        "run.jobs.get",
        "run.jobs.run",
        "run.jobs.update",
        "run.operations.get",
        "run.revisions.get",
        "run.services.get",
        "run.services.update"
      ]
    ' >/dev/null <<<"$role_json" ||
    fail "Cloud Run delivery custom role is not the exact seven-permission allowlist"
  ancestors_json="$(read_project_ancestors)"

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
  verify_artifact_repository_metadata \
    agent \
    delete-after-90-days \
    7776000s \
    keep-last-30 \
    30 <<<"$artifact_json"
  preview_artifact_json="$(
    gcloud artifacts repositories describe agent-preview \
      --project "$PROJECT_ID" \
      --location "$REGION" \
      --format=json
  )"
  verify_artifact_repository_metadata \
    agent-preview \
    delete-after-14-days \
    1209600s \
    keep-last-20 \
    20 <<<"$preview_artifact_json"

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

  verify_project_has_no_user_managed_service_account_keys

  project_policy="$(
    gcloud projects get-iam-policy "$PROJECT_ID" --format=json
  )"
  audit_iam_policy \
    "$project_policy" \
    "projects/${PROJECT_ID}" \
    "OPS_FOUNDATION_REVIEWED_IAM_BINDINGS"
  assert_workload_accounts_have_no_direct_roles \
    "$project_policy" \
    "projects/${PROJECT_ID}" \
    "$ancestors_json"
  verify_ancestor_policies "$ancestors_json"
  assert_exact_role_member \
    "$project_policy" \
    "roles/cloudscheduler.serviceAgent" \
    "serviceAccount:${CLOUD_SCHEDULER_SERVICE_AGENT}" \
    "Cloud Scheduler service agent must keep its exact Google-managed role"
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
  expected_pairs="$(
    jq -cn \
      --arg builder "serviceAccount:${BUILDER_SA}" \
      --arg cloud_run "serviceAccount:${CLOUD_RUN_SERVICE_AGENT}" \
      --arg production_deployer "serviceAccount:${PRODUCTION_DEPLOYER_SA}" \
      '[
        {role: "roles/artifactregistry.reader", member: $cloud_run},
        {role: "roles/artifactregistry.reader", member: $production_deployer},
        {role: "roles/artifactregistry.writer", member: $builder}
      ]'
  )"
  assert_policy_binding_pairs_exactly \
    "$repository_policy" \
    "$expected_pairs" \
    "Production Artifact Registry IAM must contain only its builder, deployer, and Cloud Run reader"

  preview_repository_policy="$(
    gcloud artifacts repositories get-iam-policy agent-preview \
      --project "$PROJECT_ID" \
      --location "$REGION" \
      --format=json
  )"
  audit_iam_policy \
    "$preview_repository_policy" \
    "projects/${PROJECT_ID}/locations/${REGION}/repositories/agent-preview" \
    "OPS_FOUNDATION_REVIEWED_IAM_BINDINGS"
  expected_pairs="$(
    jq -cn \
      --arg builder "serviceAccount:${PREVIEW_BUILDER_SA}" \
      --arg cloud_run "serviceAccount:${CLOUD_RUN_SERVICE_AGENT}" \
      --arg preview_deployer "serviceAccount:${PREVIEW_DEPLOYER_SA}" \
      '[
        {role: "roles/artifactregistry.reader", member: $cloud_run},
        {role: "roles/artifactregistry.reader", member: $preview_deployer},
        {role: "roles/artifactregistry.writer", member: $builder}
      ]'
  )"
  assert_policy_binding_pairs_exactly \
    "$preview_repository_policy" \
    "$expected_pairs" \
    "Preview Artifact Registry IAM must contain only its isolated builder, deployer, and Cloud Run reader"
  for deployer in "$PREVIEW_DEPLOYER_SA" "$PRODUCTION_DEPLOYER_SA"; do
    assert_member_has_no_direct_roles \
      "$project_policy" \
      "serviceAccount:${deployer}" \
      "${deployer} must not hold any direct project-level role"
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
      "$preview_repository_policy" \
      "roles/artifactregistry.writer" \
      "serviceAccount:${deployer}" \
      "${deployer} still has preview-repository image-writer access"
    assert_policy_lacks_member \
      "$project_policy" \
      "roles/secretmanager.secretAccessor" \
      "serviceAccount:${deployer}" \
      "${deployer} must not read runtime secrets"
  done
  for service_account in \
    "$PRODUCTION_RUNTIME_SA" \
    "$PREVIEW_RUNTIME_SA" \
    "$PRODUCTION_MIGRATOR_SA" \
    "$PREVIEW_MIGRATOR_SA"; do
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
  for service_account in "$BUILDER_SA" "$PREVIEW_BUILDER_SA"; do
    assert_member_has_no_direct_roles \
      "$project_policy" \
      "serviceAccount:${service_account}" \
      "${service_account} must not hold any direct project-level role"
    assert_policy_lacks_member \
      "$project_policy" \
      "roles/secretmanager.secretAccessor" \
      "serviceAccount:${service_account}" \
      "${service_account} must not read runtime or migration secrets"
  done

  verify_service_account_act_as_policy \
    "$PRODUCTION_RUNTIME_SA" \
    "$PRODUCTION_DEPLOYER_SA" \
    "only the production deployer may act as the production runtime"
  verify_service_account_act_as_policy \
    "$PREVIEW_RUNTIME_SA" \
    "$PREVIEW_DEPLOYER_SA" \
    "only the preview deployer may act as the preview runtime"
  verify_service_account_act_as_policy \
    "$PRODUCTION_MIGRATOR_SA" \
    "$PRODUCTION_DEPLOYER_SA" \
    "only the production deployer may act as the production migrator"
  verify_service_account_act_as_policy \
    "$PREVIEW_MIGRATOR_SA" \
    "$PREVIEW_DEPLOYER_SA" \
    "only the preview deployer may act as the preview migrator"

  for secret_name in "${PRODUCTION_SECRET_NAMES[@]}"; do
    verify_runtime_secret_policy "$secret_name" "$PRODUCTION_RUNTIME_SA"
  done
  for secret_name in "${PREVIEW_SECRET_NAMES[@]}"; do
    verify_runtime_secret_policy "$secret_name" "$PREVIEW_RUNTIME_SA"
  done
  verify_runtime_secret_policy \
    "$PRODUCTION_MIGRATION_SECRET" \
    "$PRODUCTION_MIGRATOR_SA"
  verify_runtime_secret_policy \
    "$PREVIEW_MIGRATION_SECRET" \
    "$PREVIEW_MIGRATOR_SA"

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
  builder_policy="$(
    gcloud iam service-accounts get-iam-policy \
      "$BUILDER_SA" \
      --project "$PROJECT_ID" \
      --format=json
  )"
  preview_builder_policy="$(
    gcloud iam service-accounts get-iam-policy \
      "$PREVIEW_BUILDER_SA" \
      --project "$PROJECT_ID" \
      --format=json
  )"
  assert_exact_role_member \
    "$preview_deployer_policy" \
    "roles/iam.workloadIdentityUser" \
    "principalSet://iam.googleapis.com/projects/${project_number}/locations/global/workloadIdentityPools/github/attribute.delivery_role/preview-deployer" \
    "preview deployer must trust only the preview-deployer delivery role"
  assert_exact_role_member \
    "$production_deployer_policy" \
    "roles/iam.workloadIdentityUser" \
    "principalSet://iam.googleapis.com/projects/${project_number}/locations/global/workloadIdentityPools/github/attribute.delivery_role/production-deployer" \
    "production deployer must trust only the production-deployer delivery role"
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
  assert_exact_role_member \
    "$builder_policy" \
    "roles/iam.workloadIdentityUser" \
    "principalSet://iam.googleapis.com/projects/${project_number}/locations/global/workloadIdentityPools/github/attribute.delivery_role/production-builder" \
    "production image builder must trust only the production-builder delivery role"
  assert_exact_role_member \
    "$preview_builder_policy" \
    "roles/iam.workloadIdentityUser" \
    "principalSet://iam.googleapis.com/projects/${project_number}/locations/global/workloadIdentityPools/github/attribute.delivery_role/preview-builder" \
    "preview image builder must trust only the preview-builder delivery role"
  assert_policy_has_no_public_members \
    "$builder_policy" \
    "production image builder IAM must not trust public principals"
  assert_policy_has_no_public_members \
    "$preview_builder_policy" \
    "preview image builder IAM must not trust public principals"
  assert_policy_roles_exactly \
    "$builder_policy" \
    "roles/iam.workloadIdentityUser" \
    "production image builder must expose only its reviewed direct federation role"
  assert_policy_roles_exactly \
    "$preview_builder_policy" \
    "roles/iam.workloadIdentityUser" \
    "preview image builder must expose only its reviewed direct federation role"

  verify_cloud_run_service \
    "agent-preview" \
    "$PREVIEW_RUNTIME_SA" \
    "$PREVIEW_DEPLOYER_SA"
  verify_cloud_run_job \
    "agent-preview-migrate" \
    "$PREVIEW_MIGRATOR_SA" \
    "$PREVIEW_DEPLOYER_SA" \
    "migration" \
    "agent.migrate" \
    "$PREVIEW_MIGRATION_SECRET"
  verify_cloud_run_job \
    "agent-preview-grants" \
    "$PREVIEW_RUNTIME_SA" \
    "$PREVIEW_DEPLOYER_SA" \
    "grant-probe" \
    "agent.neon_grant_probe" \
    "agent-preview-database-url"
  verify_cloud_run_job \
    "agent-preview-maintenance" \
    "$PREVIEW_RUNTIME_SA" \
    "$PREVIEW_DEPLOYER_SA" \
    "maintenance" \
    "agent.maintenance" \
    "agent-preview-database-url"
  verify_cloud_run_service \
    "agent" \
    "$PRODUCTION_RUNTIME_SA" \
    "$PRODUCTION_DEPLOYER_SA"
  verify_cloud_run_job \
    "agent-migrate" \
    "$PRODUCTION_MIGRATOR_SA" \
    "$PRODUCTION_DEPLOYER_SA" \
    "migration" \
    "agent.migrate" \
    "$PRODUCTION_MIGRATION_SECRET"
  verify_cloud_run_job \
    "agent-grants" \
    "$PRODUCTION_RUNTIME_SA" \
    "$PRODUCTION_DEPLOYER_SA" \
    "grant-probe" \
    "agent.neon_grant_probe" \
    "agent-database-url"
  verify_cloud_run_job \
    "agent-maintenance" \
    "$PRODUCTION_RUNTIME_SA" \
    "$PRODUCTION_DEPLOYER_SA" \
    "maintenance" \
    "agent.maintenance" \
    "agent-database-url" \
    "$MAINTENANCE_SCHEDULER_SA"
  verify_guest_maintenance_schedule

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
