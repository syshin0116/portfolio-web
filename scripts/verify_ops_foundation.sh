#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ID="festive-ally-503605-v7"
readonly PROJECT_NUMBER="72919926064"
readonly REGION="us-east4"
readonly REPOSITORY="syshin0116/syshin0116.dev"
readonly RUNTIME_SA="agent-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PREVIEW_SA="agent-preview-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
readonly PRODUCTION_SA="agent-prod-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

readonly REQUIRED_APIS=(
  artifactregistry.googleapis.com
  cloudresourcemanager.googleapis.com
  iam.googleapis.com
  iamcredentials.googleapis.com
  run.googleapis.com
  secretmanager.googleapis.com
  sts.googleapis.com
)

readonly SECRET_NAMES=(
  agent-auth-secret
  agent-database-url
  anthropic-api-key
  langsmith-api-key
  openai-api-key
)

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

for command_name in gcloud gh jq; do
  command -v "$command_name" >/dev/null || fail "missing command: ${command_name}"
done

enabled_apis="$(gcloud services list --enabled --project "$PROJECT_ID" --format='value(config.name)')"
for api in "${REQUIRED_APIS[@]}"; do
  grep -Fxq "$api" <<<"$enabled_apis" || fail "API is not enabled: ${api}"
done

artifact_name="$(
  gcloud artifacts repositories describe agent \
    --project "$PROJECT_ID" \
    --location "$REGION" \
    --format='value(name)' 2>/dev/null
)"
[[ "$artifact_name" == "projects/${PROJECT_ID}/locations/${REGION}/repositories/agent" ]] ||
  fail "Artifact Registry region or name mismatch"

for service_account in "$RUNTIME_SA" "$PREVIEW_SA" "$PRODUCTION_SA"; do
  gcloud iam service-accounts describe "$service_account" --project "$PROJECT_ID" >/dev/null
  user_key_count="$(
    gcloud iam service-accounts keys list \
      --iam-account "$service_account" \
      --managed-by=user \
      --format='value(name)' | wc -l | tr -d ' '
  )"
  [[ "$user_key_count" == "0" ]] || fail "user-managed key exists for ${service_account}"
done

for secret_name in "${SECRET_NAMES[@]}"; do
  gcloud secrets describe "$secret_name" --project "$PROJECT_ID" >/dev/null
done

preview_condition="$(
  gcloud iam workload-identity-pools providers describe github-preview \
    --project "$PROJECT_ID" \
    --location global \
    --workload-identity-pool github \
    --format='value(attributeCondition)'
)"
production_condition="$(
  gcloud iam workload-identity-pools providers describe github-production \
    --project "$PROJECT_ID" \
    --location global \
    --workload-identity-pool github \
    --format='value(attributeCondition)'
)"

grep -Fq "assertion.repository_id == '1102380057'" <<<"$preview_condition" ||
  fail "preview provider lacks repository numeric-ID condition"
grep -Fq "assertion.repository_owner_id == '99532836'" <<<"$preview_condition" ||
  fail "preview provider lacks owner numeric-ID condition"
grep -Fq "assertion.environment == 'Preview'" <<<"$preview_condition" ||
  fail "preview provider lacks Preview environment condition"
grep -Fq "assertion.ref == 'refs/heads/main'" <<<"$production_condition" ||
  fail "production provider lacks main-branch condition"
grep -Fq "assertion.environment == 'Production'" <<<"$production_condition" ||
  fail "production provider lacks Production environment condition"

preview_reviewers="$(
  gh api "repos/${REPOSITORY}/environments/Preview" \
    --jq '[.protection_rules[]? | select(.type == "required_reviewers") | .reviewers[]? | .reviewer.id] | length'
)"
production_reviewers="$(
  gh api "repos/${REPOSITORY}/environments/Production" \
    --jq '[.protection_rules[]? | select(.type == "required_reviewers") | .reviewers[]? | .reviewer.id] | length'
)"
[[ "$preview_reviewers" -ge 1 ]] || fail "Preview has no required reviewer"
[[ "$production_reviewers" -ge 1 ]] || fail "Production has no required reviewer"

production_branches="$(
  gh api "repos/${REPOSITORY}/environments/Production/deployment-branch-policies" \
    --jq '[.branch_policies[]?.name] | join("\n")'
)"
grep -Fxq main <<<"$production_branches" || fail "Production does not restrict deployment to main"

printf 'OK: GCP/GitHub foundation metadata and keyless constraints verified for project %s (%s).\n' \
  "$PROJECT_ID" "$PROJECT_NUMBER"
