#!/usr/bin/env bash
set -eEuo pipefail

readonly MODE="${1:-}"
readonly REQUESTED_ROLLBACK_REVISION="${2:-}"
readonly EXPECTED_PROJECT_ID="festive-ally-503605-v7"
readonly EXPECTED_PROJECT_NUMBER="72919926064"
readonly EXPECTED_REGION="asia-southeast1"
readonly CLOUD_RUN_API_ORIGIN="https://run.googleapis.com"
readonly CLOUD_RUN_API_MAX_BYTES="1048576"

require_command() {
  command -v "$1" >/dev/null || {
    printf 'missing required command: %s\n' "$1" >&2
    exit 1
  }
}

require_value() {
  local name="$1"
  [[ -n "${!name:-}" ]] || {
    printf 'missing required environment variable: %s\n' "$name" >&2
    exit 1
  }
}

cloud_run_api_request() (
  set -euo pipefail
  local auth_config
  local body
  local content_type
  local -a curl_arguments
  local method="$1"
  local metadata
  local request
  local request_document="${3:-}"
  local redirects
  local resource_path="$2"
  local size
  local status
  local temp_root="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
  local token

  if [[ "$method" == "GET" ]]; then
    [[ "$resource_path" =~ ^(services/agent(-preview)?|services/agent(-preview)?/revisions/agent(-preview)?-[a-z0-9-]+|jobs/(agent-(migrate|grants|maintenance|scheduled-maintenance)|agent-preview-(migrate|grants|maintenance))|operations/[A-Za-z0-9._~-]+)$ ]]
  elif [[ "$method" == "POST" ]]; then
    [[ "$resource_path" =~ ^jobs/(agent-(migrate|grants|maintenance)|agent-preview-(migrate|grants|maintenance)):run$ ]]
  else
    false
  fi || {
    printf 'refusing non-canonical Cloud Run REST resource path\n' >&2
    exit 1
  }
  if [[ "$method" == "GET" ]]; then
    [[ -z "$request_document" ]] || {
      printf 'Cloud Run REST GET must not carry a request body\n' >&2
      exit 1
    }
  else
    if [[ -z "$request_document" || "${#request_document}" -gt 4096 ]] ||
      ! jq -e 'type == "object"' >/dev/null <<<"$request_document"; then
      printf 'Cloud Run REST POST requires a bounded JSON object\n' >&2
      exit 1
    fi
  fi
  [[ -d "$temp_root" && ! -L "$temp_root" ]] || {
    printf 'Cloud Run REST temporary directory is not a real directory\n' >&2
    exit 1
  }

  auth_config="$(mktemp "${temp_root%/}/cloud-run-auth.XXXXXX")"
  body="$(mktemp "${temp_root%/}/cloud-run-body.XXXXXX")"
  request="$(mktemp "${temp_root%/}/cloud-run-request.XXXXXX")"
  chmod 600 "$auth_config" "$body" "$request"
  CLOUD_RUN_API_CLEANUP_AUTH_CONFIG="$auth_config"
  CLOUD_RUN_API_CLEANUP_BODY="$body"
  CLOUD_RUN_API_CLEANUP_REQUEST="$request"
  trap 'rm -f -- \
    "$CLOUD_RUN_API_CLEANUP_AUTH_CONFIG" \
    "$CLOUD_RUN_API_CLEANUP_BODY" \
    "$CLOUD_RUN_API_CLEANUP_REQUEST"' EXIT

  token="$(gcloud auth print-access-token --quiet)"
  if [[ "${#token}" -lt 20 || "${#token}" -gt 4096 ]] ||
    [[ ! "$token" =~ ^[A-Za-z0-9._~-]+$ ]]; then
    printf 'gcloud returned an invalid access token shape\n' >&2
    exit 1
  fi
  printf 'header = "Authorization: Bearer %s"\n' "$token" >"$auth_config"
  unset token

  curl_arguments=(
    --config "$auth_config"
    --silent
    --show-error
    --fail-with-body
    --request "$method"
    --header "Accept: application/json"
    --proto "=https"
    --proto-redir "=https"
    --max-redirs 0
    --max-time 20
    --max-filesize "$CLOUD_RUN_API_MAX_BYTES"
    --output "$body"
    --write-out $'%{http_code}\n%{content_type}\n%{size_download}\n%{num_redirects}'
  )
  if [[ "$method" == "POST" ]]; then
    printf '%s' "$request_document" >"$request"
    curl_arguments+=(
      --header "Content-Type: application/json"
      --data-binary "@${request}"
    )
  fi

  metadata="$(
    curl "${curl_arguments[@]}" \
      "${CLOUD_RUN_API_ORIGIN}/v2/projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/${resource_path}"
  )"
  status="$(sed -n '1p' <<<"$metadata")"
  content_type="$(sed -n '2p' <<<"$metadata")"
  size="$(sed -n '3p' <<<"$metadata")"
  redirects="$(sed -n '4p' <<<"$metadata")"

  [[ "$status" == "200" ]] || {
    printf 'Cloud Run REST %s returned HTTP %s\n' "$method" "$status" >&2
    exit 1
  }
  [[ "$content_type" =~ ^application/json([[:space:]]*";"[[:space:]]*charset=[Uu][Tt][Ff]-8)?$ ]] || {
    printf 'Cloud Run REST %s returned a non-JSON content type\n' "$method" >&2
    exit 1
  }
  [[ "$size" =~ ^[0-9]+$ && "$size" -gt 0 && "$size" -le "$CLOUD_RUN_API_MAX_BYTES" ]] || {
    printf 'Cloud Run REST %s returned an invalid response size\n' "$method" >&2
    exit 1
  }
  [[ "$redirects" == "0" ]] || {
    printf 'Cloud Run REST %s attempted a redirect\n' "$method" >&2
    exit 1
  }
  jq -e 'type == "object"' "$body" >/dev/null || {
    printf 'Cloud Run REST %s returned an invalid JSON object\n' "$method" >&2
    exit 1
  }
  cat "$body"
)

cloud_run_api_get() {
  cloud_run_api_request "GET" "$1"
}

cloud_run_api_run_job() {
  local etag="$2"
  local request_document

  request_document="$(jq -cn --arg etag "$etag" '{etag:$etag}')"
  cloud_run_api_request "POST" "jobs/${1}:run" "$request_document"
}

service_json() {
  cloud_run_api_get "services/${CLOUD_RUN_SERVICE}"
}

revision_json() {
  local revision="$1"
  cloud_run_api_get "services/${CLOUD_RUN_SERVICE}/revisions/${revision}"
}

revision_image_digest() {
  local revision="$1"

  revision_json "$revision" |
    jq -er \
      --arg expected_image_prefix "$EXPECTED_IMAGE_PREFIX" \
      '
        .containers
        | select(type == "array" and length == 1)
        | .[0].image
        | select(type == "string" and startswith($expected_image_prefix))
        | select(
            (ltrimstr($expected_image_prefix) | test("^[0-9a-f]{64}$"))
          )
      '
}

job_json() {
  local job="$1"
  cloud_run_api_get "jobs/${job}"
}

operation_json() {
  local operation_id="$1"
  cloud_run_api_get "operations/${operation_id}"
}

serving_revision() {
  service_json |
    jq -er \
      --arg expected_service "projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/services/${CLOUD_RUN_SERVICE}" \
      --arg expected_service_short "$CLOUD_RUN_SERVICE" \
      '
      def canonical_revision_id($value):
        ($value | type) == "string"
        and ($value | test("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"))
        and ($value | startswith($expected_service_short + "-"))
        and (
          $expected_service_short != "agent"
          or ($value | startswith("agent-preview-") | not)
        );
      def full_revision_id($value):
        if (
          ($value | type) == "string"
          and ($value | startswith($expected_service + "/revisions/"))
          and (
            $value
            | ltrimstr($expected_service + "/revisions/")
            | canonical_revision_id(.)
          )
        )
        then ($value | ltrimstr($expected_service + "/revisions/"))
        else error("revision is outside the selected service")
        end;
      def explicit_revision_id($value):
        if canonical_revision_id($value)
        then $value
        else full_revision_id($value)
        end;
      def absent_or_empty_string($value):
        $value == null
        or (($value | type) == "string" and $value == "");
      def explicit_revision_type($value):
        $value == null
        or (
          ($value | type) == "string"
          and (
            $value == "TRAFFIC_TARGET_ALLOCATION_TYPE_UNSPECIFIED"
            or $value == "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION"
          )
        );
      def resolved_revision($target):
        if (
          $target.type
            == "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
          and absent_or_empty_string($target.revision)
        )
        then full_revision_id(.latestReadyRevision)
        elif (
          explicit_revision_type($target.type)
        )
        then explicit_revision_id($target.revision)
        else error("serving target does not resolve to a canonical revision")
        end;
      def observed_traffic:
        if .trafficStatuses == null
        then .traffic
        else .trafficStatuses
        end;

      observed_traffic as $traffic
      | if (
          ($traffic | type) == "array"
          and ($traffic | length) == 1
          and absent_or_empty_string($traffic[0].tag)
          and ($traffic[0].percent == 100)
        )
        then resolved_revision($traffic[0])
        else error("expected exactly one untagged 100% serving revision")
        end
      '
}

service_url() {
  local document
  document="$(service_json)"

  jq -e \
    --arg expected_service "$CLOUD_RUN_SERVICE" \
    '
      .uri
      | type == "string"
      and test("^https://[a-z0-9-]+(\\.[a-z0-9-]+)*\\.run\\.app$")
      and startswith("https://" + $expected_service + "-")
      and (
        $expected_service != "agent"
        or (startswith("https://agent-preview-") | not)
      )
    ' >/dev/null <<<"$document"
  printf 'https://%s-%s.%s.run.app\n' \
    "$CLOUD_RUN_SERVICE" "$EXPECTED_PROJECT_NUMBER" "$GCP_REGION"
}

runtime_expectations() {
  case "$CLOUD_RUN_SERVICE" in
    agent-preview)
      readonly EXPECTED_IMAGE_PREFIX="asia-southeast1-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent@sha256:"
      readonly EXPECTED_RUNTIME_SERVICE_ACCOUNT="agent-preview-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
      readonly EXPECTED_RUNTIME_SECRETS='[
        {"name":"AGENT_AUTH_SECRET","secret":"agent-preview-auth-secret"},
        {"name":"ANTHROPIC_API_KEY","secret":"agent-preview-anthropic-api-key"},
        {"name":"DATABASE_URL","secret":"agent-preview-database-url"},
        {"name":"LANGCHAIN_API_KEY","secret":"agent-preview-langsmith-api-key"}
      ]'
      readonly EXPECTED_MIGRATOR_SERVICE_ACCOUNT="agent-preview-migrator@festive-ally-503605-v7.iam.gserviceaccount.com"
      readonly EXPECTED_MIGRATION_SECRET="agent-preview-migration-database-url"
      readonly EXPECTED_MIGRATION_JOB="agent-preview-migrate"
      readonly EXPECTED_GRANT_JOB="agent-preview-grants"
      readonly EXPECTED_MAINTENANCE_JOB="agent-preview-maintenance"
      readonly EXPECTED_SCHEDULED_MAINTENANCE_JOB=""
      readonly EXPECTED_ANONYMOUS_ACCESS_ENABLED="false"
      readonly EXPECTED_GUEST_DAILY_BUDGET_MICRO_USD=""
      readonly EXPECTED_GUEST_MODEL=""
      readonly EXPECTED_GUEST_RUN_RESERVATION_MICRO_USD=""
      ;;
    agent)
      readonly EXPECTED_IMAGE_PREFIX="asia-southeast1-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:"
      readonly EXPECTED_RUNTIME_SERVICE_ACCOUNT="agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
      readonly EXPECTED_RUNTIME_SECRETS='[
        {"name":"AGENT_AUTH_SECRET","secret":"agent-auth-secret"},
        {"name":"DATABASE_URL","secret":"agent-database-url"},
        {"name":"OPENAI_API_KEY","secret":"openai-api-key"}
      ]'
      readonly EXPECTED_MIGRATOR_SERVICE_ACCOUNT="agent-prod-migrator@festive-ally-503605-v7.iam.gserviceaccount.com"
      readonly EXPECTED_MIGRATION_SECRET="agent-migration-database-url"
      readonly EXPECTED_MIGRATION_JOB="agent-migrate"
      readonly EXPECTED_GRANT_JOB="agent-grants"
      readonly EXPECTED_MAINTENANCE_JOB="agent-maintenance"
      readonly EXPECTED_SCHEDULED_MAINTENANCE_JOB="agent-scheduled-maintenance"
      readonly EXPECTED_ANONYMOUS_ACCESS_ENABLED="true"
      readonly EXPECTED_GUEST_DAILY_BUDGET_MICRO_USD="500000"
      readonly EXPECTED_GUEST_MODEL="openai:gpt-5.6-luna"
      readonly EXPECTED_GUEST_RUN_RESERVATION_MICRO_USD="18892"
      ;;
  esac
  EXPECTED_PLAIN_ENV="$(
    jq -cn \
      --arg anonymous_access "$EXPECTED_ANONYMOUS_ACCESS_ENABLED" \
      --arg guest_daily_budget "$EXPECTED_GUEST_DAILY_BUDGET_MICRO_USD" \
      --arg guest_model "$EXPECTED_GUEST_MODEL" \
      --arg guest_run_reservation "$EXPECTED_GUEST_RUN_RESERVATION_MICRO_USD" \
      '{
        AEGRA_CONFIG:"/app/aegra.json",
        AGENT_ANONYMOUS_ACCESS_ENABLED:$anonymous_access,
        BG_JOB_MAX_RETRIES:"0",
        ENV_MODE:"PRODUCTION",
        FF_V2_EVENT_STREAMING:"true",
        GUEST_DAILY_BUDGET_MICRO_USD:$guest_daily_budget,
        GUEST_MODEL:$guest_model,
        GUEST_RUN_RESERVATION_MICRO_USD:$guest_run_reservation,
        HOST:"0.0.0.0",
        LANGGRAPH_MAX_POOL_SIZE:"4",
        LANGGRAPH_MIN_POOL_SIZE:"1",
        MODEL:"openai:gpt-5.6-luna",
        REDIS_BROKER_ENABLED:"false",
        RUN_MIGRATIONS_ON_STARTUP:"false",
        SQLALCHEMY_MAX_OVERFLOW:"0",
        SQLALCHEMY_POOL_SIZE:"2"
      }'
  )"
  readonly EXPECTED_PLAIN_ENV
}

verify_runtime_template() {
  local document="$1"
  local expected_image="${2:-}"
  local selector="$3"
  local template

  template="$(jq -ce "$selector | select(type == \"object\")" <<<"$document")"
  jq -e \
    --arg expected_image "$expected_image" \
    --arg expected_image_prefix "$EXPECTED_IMAGE_PREFIX" \
    --arg expected_runtime_service_account "$EXPECTED_RUNTIME_SERVICE_ACCOUNT" \
    --argjson expected_plain_env "$EXPECTED_PLAIN_ENV" \
    --argjson expected_runtime_secrets "$EXPECTED_RUNTIME_SECRETS" \
    '
      def numeric_secret_version:
        type == "string" and test("^[1-9][0-9]*$");
      def absent_or_empty_array:
        . == null or . == [];
      def absent_or_empty_object:
        . == null or . == {};
      def absent_or_empty_string:
        . == null or . == "";
      def absent_or_false:
        . == null or . == false;
      def expected_digest($image):
        ($image | type) == "string"
        and (
          if $expected_image == ""
          then ($image | startswith($expected_image_prefix))
            and (($image | ltrimstr($expected_image_prefix)) | test("^[0-9a-f]{64}$"))
          else $image == $expected_image
          end
        );

      .serviceAccount == $expected_runtime_service_account
      and .timeout == "300s"
      and .executionEnvironment == "EXECUTION_ENVIRONMENT_GEN2"
      and .maxInstanceRequestConcurrency == 8
      and (.scaling.minInstanceCount // 0) == 0
      and .scaling.maxInstanceCount == 1
      and (.volumes | absent_or_empty_array)
      and (.encryptionKey | absent_or_empty_string)
      and (.encryptionKeyShutdownDuration | absent_or_empty_string)
      and (
        .encryptionKeyRevocationAction == null
        or .encryptionKeyRevocationAction
          == "ENCRYPTION_KEY_REVOCATION_ACTION_UNSPECIFIED"
      )
      and (.nodeSelector | absent_or_empty_object)
      and (.serviceMesh | absent_or_empty_object)
      and (.vpcAccess | absent_or_empty_object)
      and (.healthCheckDisabled | absent_or_false)
      and (.gpuZonalRedundancyDisabled | absent_or_false)
      and (.sessionAffinity | absent_or_false)
      and (.containers | type == "array" and length == 1)
      and .containers[0].name == "agent"
      and expected_digest(.containers[0].image)
      and .containers[0].command == ["uvicorn"]
      and .containers[0].args == [
        "aegra_api.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
        "--workers",
        "1"
      ]
      and .containers[0].ports == [{"name":"http1","containerPort":8080}]
      and .containers[0].resources.limits == {"cpu":"1","memory":"1Gi"}
      and .containers[0].resources.cpuIdle == true
      and .containers[0].resources.startupCpuBoost == true
      and (
        (.containers[0].resources | keys | sort)
        == ["cpuIdle","limits","startupCpuBoost"]
      )
      and (.containers[0].sourceCode | absent_or_empty_object)
      and (.containers[0].volumeMounts | absent_or_empty_array)
      and (.containers[0].workingDir | absent_or_empty_string)
      and (.containers[0].readinessProbe | absent_or_empty_object)
      and (.containers[0].dependsOn | absent_or_empty_array)
      and (.containers[0].baseImageUri | absent_or_empty_string)
      and (.containers[0].sandboxLauncher | absent_or_false)
      and (
        .containers[0].startupProbe as $probe
        | ($probe.initialDelaySeconds // 0) == 0
          and $probe.timeoutSeconds == 5
          and $probe.periodSeconds == 5
          and $probe.failureThreshold == 24
          and ($probe.successThreshold // 1) == 1
          and $probe.httpGet.path == "/ready"
          and $probe.httpGet.port == 8080
          and ($probe.httpGet.httpHeaders // []) == []
          and ((
            $probe | keys
              - [
                  "failureThreshold",
                  "httpGet",
                  "initialDelaySeconds",
                  "periodSeconds",
                  "successThreshold",
                  "timeoutSeconds"
                ]
          ) == [])
          and ((
            $probe.httpGet | keys
              - ["httpHeaders","path","port"]
          ) == [])
      )
      and (
        .containers[0].livenessProbe as $probe
        | ($probe.initialDelaySeconds // 0) == 0
          and $probe.timeoutSeconds == 5
          and $probe.periodSeconds == 30
          and $probe.failureThreshold == 3
          and ($probe.successThreshold // 1) == 1
          and $probe.httpGet.path == "/live"
          and $probe.httpGet.port == 8080
          and ($probe.httpGet.httpHeaders // []) == []
          and ((
            $probe | keys
              - [
                  "failureThreshold",
                  "httpGet",
                  "initialDelaySeconds",
                  "periodSeconds",
                  "successThreshold",
                  "timeoutSeconds"
                ]
          ) == [])
          and ((
            $probe.httpGet | keys
              - ["httpHeaders","path","port"]
          ) == [])
      )
      and (
        (.containers[0].env // []) as $env
        | ($env | length)
          == (($expected_plain_env | length) + ($expected_runtime_secrets | length))
          and ([$env[].name] | length) == ([$env[].name] | unique | length)
          and (
            # Cloud Run proto JSON may omit EnvVar.value for its empty default.
            [
              $env[]
              | select(has("valueSource") | not)
              | select((has("value") | not) or (.value | type == "string"))
              | {key:.name, value:(.value // "")}
            ] | from_entries
          ) == $expected_plain_env
          and (
            [
              $env[]
              | select(has("valueSource") and (has("value") | not))
              | {
                  name:.name,
                  secret:.valueSource.secretKeyRef.secret
                }
            ] | sort_by(.name)
          ) == ($expected_runtime_secrets | sort_by(.name))
          and all(
            $env[]
            | select(has("valueSource"));
            (.valueSource | keys) == ["secretKeyRef"]
            and (.valueSource.secretKeyRef | keys | sort) == ["secret","version"]
            and (.valueSource.secretKeyRef.version | numeric_secret_version)
          )
      )
    ' >/dev/null <<<"$template" || {
    printf 'Cloud Run runtime contract drifted from the exact Terraform template.\n' >&2
    return 1
  }
}

verify_service_contract() {
  local document
  local expected_image="${1:-}"
  document="$(service_json)"

  jq -e \
    --arg expected_name "projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/services/${CLOUD_RUN_SERVICE}" \
    --arg expected_service_short "$CLOUD_RUN_SERVICE" \
    '
      def absent_or_empty_array:
        . == null or . == [];
      def absent_or_empty_object:
        . == null or . == {};
      def absent_or_false:
        . == null or . == false;
      def canonical_revision_name:
        type == "string"
        and startswith($expected_name + "/revisions/")
        and (
          ltrimstr($expected_name + "/revisions/")
          | test("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
            and startswith($expected_service_short + "-")
            and (
              $expected_service_short != "agent"
              or (startswith("agent-preview-") | not)
            )
        );
      def canonical_service_scaling:
        . == null
        or . == {}
        or (
          type == "object"
          and (keys == ["maxInstanceCount"])
          and .maxInstanceCount == 20
        );
      def canonical_cloud_run_uri:
        type == "string"
        and test("^https://[a-z0-9-]+(\\.[a-z0-9-]+)*\\.run\\.app$")
        and startswith("https://" + $expected_service_short + "-")
        and (
          $expected_service_short != "agent"
          or (startswith("https://agent-preview-") | not)
        );
      def observed_traffic:
        if .trafficStatuses == null
        then .traffic
        else .trafficStatuses
        end;

      .name == $expected_name
      and .ingress == "INGRESS_TRAFFIC_ALL"
      and (.binaryAuthorization | absent_or_empty_object)
      and (.scaling | canonical_service_scaling)
      and (.invokerIamDisabled | absent_or_false)
      and (.defaultUriDisabled | absent_or_false)
      and (.iapEnabled | absent_or_false)
      and (.multiRegionSettings | absent_or_empty_object)
      and (.customAudiences | absent_or_empty_array)
      and (.buildConfig | absent_or_empty_object)
      and (.reconciling | absent_or_false)
      and .terminalCondition.state == "CONDITION_SUCCEEDED"
      and (.generation | type) == "string"
      and (.generation | test("^[1-9][0-9]*$"))
      and .observedGeneration == .generation
      and (.latestReadyRevision | canonical_revision_name)
      and (.latestCreatedRevision | canonical_revision_name)
      and ((observed_traffic) | type) == "array"
      and (.uri | canonical_cloud_run_uri)
    ' >/dev/null <<<"$document" || {
    printf 'Cloud Run service is not a reconciled canonical REST v2 resource.\n' >&2
    return 1
  }
  verify_runtime_template "$document" "$expected_image" ".template"
}

verify_revision_contract() {
  local revision="$1"
  local expected_image="${2:-}"
  local document
  document="$(revision_json "$revision")"

  jq -e \
    --arg expected_name "projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/services/${CLOUD_RUN_SERVICE}/revisions/${revision}" \
    --arg expected_service "projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/services/${CLOUD_RUN_SERVICE}" \
    --arg expected_service_short "$CLOUD_RUN_SERVICE" \
    '
      def absent_or_false:
        . == null or . == false;

      .name == $expected_name
      and (.service == $expected_service or .service == $expected_service_short)
      and (.reconciling | absent_or_false)
      and any(
        .conditions[]?;
        .type == "Ready" and .state == "CONDITION_SUCCEEDED"
      )
    ' >/dev/null <<<"$document" || {
    printf 'Cloud Run revision %s is not a ready canonical REST v2 resource.\n' \
      "$revision" >&2
    return 1
  }
  verify_runtime_template "$document" "$expected_image" "."
}

verify_job_contract() {
  local document="${2:-}"
  local expected_args
  local expected_container_name
  local expected_image="${3:-${IMAGE_DIGEST:-}}"
  local expected_job="$1"
  local expected_secret
  local expected_service_account
  local expected_timeout

  case "$expected_job" in
    "$EXPECTED_MIGRATION_JOB")
      expected_args='["-m","agent.migrate"]'
      expected_container_name="migration"
      expected_secret="$EXPECTED_MIGRATION_SECRET"
      expected_service_account="$EXPECTED_MIGRATOR_SERVICE_ACCOUNT"
      expected_timeout="900s"
      ;;
    "$EXPECTED_GRANT_JOB")
      expected_args='["-m","agent.neon_grant_probe"]'
      expected_container_name="grant-probe"
      expected_secret="$(
        jq -r '.[] | select(.name == "DATABASE_URL") | .secret' \
          <<<"$EXPECTED_RUNTIME_SECRETS"
      )"
      expected_service_account="$EXPECTED_RUNTIME_SERVICE_ACCOUNT"
      expected_timeout="600s"
      ;;
    "$EXPECTED_MAINTENANCE_JOB" | "$EXPECTED_SCHEDULED_MAINTENANCE_JOB")
      expected_args='["-m","agent.maintenance"]'
      expected_container_name="maintenance"
      expected_secret="$(
        jq -r '.[] | select(.name == "DATABASE_URL") | .secret' \
          <<<"$EXPECTED_RUNTIME_SECRETS"
      )"
      expected_service_account="$EXPECTED_RUNTIME_SERVICE_ACCOUNT"
      expected_timeout="600s"
      ;;
    *)
      printf 'unexpected job contract selector\n' >&2
      return 1
      ;;
  esac

  if [[ -z "$document" ]]; then
    document="$(job_json "$expected_job")"
  fi
  if [[ "$expected_image" != "${EXPECTED_IMAGE_PREFIX}"* ]] ||
    [[ ! "${expected_image#"$EXPECTED_IMAGE_PREFIX"}" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'Cloud Run job verification requires an exact selected image digest.\n' \
      >&2
    return 1
  fi
  jq -e \
    --arg expected_container_name "$expected_container_name" \
    --arg expected_image "$expected_image" \
    --arg expected_name "projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/jobs/${expected_job}" \
    --arg expected_secret "$expected_secret" \
    --arg expected_service_account "$expected_service_account" \
    --arg expected_timeout "$expected_timeout" \
    --argjson expected_args "$expected_args" \
    '
      def numeric_secret_version:
        type == "string" and test("^[1-9][0-9]*$");
      def absent_or_empty_array:
        . == null or . == [];
      def absent_or_empty_object:
        . == null or . == {};
      def absent_or_empty_string:
        . == null or . == "";
      def absent_or_false:
        . == null or . == false;
      def absent_or_one:
        . == null or (type == "number" and . == 1);

      .name == $expected_name
      and (.reconciling | absent_or_false)
      and .terminalCondition.state == "CONDITION_SUCCEEDED"
      and (.generation | type) == "string"
      and (.generation | test("^[1-9][0-9]*$"))
      and .observedGeneration == .generation
      and (.etag | type) == "string"
      and (.etag | length) >= 1
      and (.etag | length) <= 1024
      and (.binaryAuthorization | absent_or_empty_object)
      and (.template.taskCount | absent_or_one)
      and (.template.parallelism | absent_or_one)
      and .template.template.serviceAccount == $expected_service_account
      and .template.template.timeout == $expected_timeout
      and .template.template.executionEnvironment == "EXECUTION_ENVIRONMENT_GEN2"
      and .template.template.maxRetries == 0
      and (.template.template.volumes | absent_or_empty_array)
      and (.template.template.encryptionKey | absent_or_empty_string)
      and (.template.template.vpcAccess | absent_or_empty_object)
      and (.template.template.nodeSelector | absent_or_empty_object)
      and (.template.template.gpuZonalRedundancyDisabled | absent_or_false)
      and (.template.template.containers | type == "array" and length == 1)
      and .template.template.containers[0].name == $expected_container_name
      and .template.template.containers[0].image == $expected_image
      and .template.template.containers[0].command == ["python"]
      and .template.template.containers[0].args == $expected_args
      and .template.template.containers[0].resources.limits == {
        "cpu":"1",
        "memory":"1Gi"
      }
      and (
        (
          .template.template.containers[0].resources
          | keys
          - ["cpuIdle","limits","startupCpuBoost"]
        ) == []
      )
      and (
        .template.template.containers[0].resources.cpuIdle
        | absent_or_false
      )
      and (
        .template.template.containers[0].resources.startupCpuBoost
        | absent_or_false
      )
      and (
        .template.template.containers[0].sourceCode
        | absent_or_empty_object
      )
      and (
        .template.template.containers[0].ports
        | absent_or_empty_array
      )
      and (
        .template.template.containers[0].volumeMounts
        | absent_or_empty_array
      )
      and (
        .template.template.containers[0].workingDir
        | absent_or_empty_string
      )
      and (
        .template.template.containers[0].livenessProbe
        | absent_or_empty_object
      )
      and (
        .template.template.containers[0].startupProbe
        | absent_or_empty_object
      )
      and (
        .template.template.containers[0].readinessProbe
        | absent_or_empty_object
      )
      and (
        .template.template.containers[0].dependsOn
        | absent_or_empty_array
      )
      and (
        .template.template.containers[0].baseImageUri
        | absent_or_empty_string
      )
      and (
        .template.template.containers[0].sandboxLauncher
        | absent_or_false
      )
      and (
        (.template.template.containers[0].env // []) as $env
        | ($env | length) == 3
          and ([$env[].name] | sort) == [
            "DATABASE_URL",
            "ENV_MODE",
            "RUN_MIGRATIONS_ON_STARTUP"
          ]
          and (
            [
              $env[]
              | select(has("value") and (has("valueSource") | not))
              | {key:.name, value:.value}
            ] | from_entries
          ) == {
            "ENV_MODE":"PRODUCTION",
            "RUN_MIGRATIONS_ON_STARTUP":"false"
          }
          and (
            [
              $env[]
              | select(has("valueSource") and (has("value") | not))
            ] | length
          ) == 1
          and (
            $env[]
            | select(.name == "DATABASE_URL")
            | .valueSource
          ) as $source
          | ($source | keys) == ["secretKeyRef"]
            and ($source.secretKeyRef | keys | sort) == ["secret","version"]
            and $source.secretKeyRef.secret == $expected_secret
            and ($source.secretKeyRef.version | numeric_secret_version)
      )
    ' >/dev/null <<<"$document" || {
    printf 'Cloud Run job %s drifted from the exact executable contract.\n' \
      "$expected_job" >&2
    return 1
  }
  jq -er '.etag' <<<"$document"
}

wait_for_job_operation() {
  local attempt
  local document="$1"
  local execution_document
  local expected_job="$2"
  local expected_job_name="projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/jobs/${expected_job}"
  local max_attempts
  local operation_id
  local operation_name
  local operation_prefix="projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/operations/"

  case "$expected_job" in
    "$EXPECTED_MIGRATION_JOB")
      max_attempts=204
      ;;
    "$EXPECTED_GRANT_JOB" | "$EXPECTED_MAINTENANCE_JOB")
      max_attempts=144
      ;;
    *)
      printf 'unexpected job operation selector\n' >&2
      return 1
      ;;
  esac

  operation_name="$(
    jq -er \
      --arg prefix "$operation_prefix" \
      '
        .name
        | select(type == "string" and startswith($prefix))
        | ltrimstr($prefix)
        | select(test("^[A-Za-z0-9._~-]+$"))
      ' <<<"$document"
  )" || {
    printf 'Cloud Run jobs.run returned a non-canonical operation name.\n' >&2
    return 1
  }
  operation_id="$operation_name"
  operation_name="${operation_prefix}${operation_id}"

  for ((attempt = 1; attempt <= max_attempts; attempt += 1)); do
    jq -e \
      --arg expected_name "$operation_name" \
      '.name == $expected_name and (.done // false) == true' \
      >/dev/null <<<"$document" && break
    if ((attempt == max_attempts)); then
      printf 'Cloud Run job operation did not complete within its contract timeout.\n' \
        >&2
      return 1
    fi
    sleep 5
    document="$(operation_json "$operation_id")"
  done

  jq -e \
    --arg expected_job "$expected_job_name" \
    --arg expected_job_short "$expected_job" \
    --arg expected_name "$operation_name" \
    '
      def absent_or_false:
        . == null or . == false;
      def absent_or_zero:
        . == null or (type == "number" and . == 0);

      .name == $expected_name
      and .done == true
      and (has("error") | not)
      and (.response | type) == "object"
      and .response["@type"]
        == "type.googleapis.com/google.cloud.run.v2.Execution"
      and (
        .response.job == $expected_job
        or .response.job == $expected_job_short
      )
      and (
        .response.name
        | type == "string"
          and startswith($expected_job + "/executions/")
          and (ltrimstr($expected_job + "/executions/")
            | test("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"))
      )
      and (.response.reconciling | absent_or_false)
      and (.response.generation | type) == "string"
      and (.response.generation | test("^[1-9][0-9]*$"))
      and .response.observedGeneration == .response.generation
      and (.response.completionTime | type) == "string"
      and (.response.completionTime | length) > 0
      and .response.taskCount == 1
      and .response.parallelism == 1
      and .response.succeededCount == 1
      and (.response.failedCount | absent_or_zero)
      and (.response.cancelledCount | absent_or_zero)
      and (.response.runningCount | absent_or_zero)
      and (.response.retriedCount | absent_or_zero)
      and any(
        .response.conditions[]?;
        .type == "Completed" and .state == "CONDITION_SUCCEEDED"
      )
    ' >/dev/null <<<"$document" || {
    printf 'Cloud Run job operation did not return one successful immutable execution.\n' \
      >&2
    return 1
  }

  execution_document="$(
    jq -ce \
      --arg expected_job "$expected_job_name" \
      '
      .response
      | {
          name:$expected_job,
          reconciling:.reconciling,
          terminalCondition:{state:"CONDITION_SUCCEEDED"},
          generation:.generation,
          observedGeneration:.observedGeneration,
          etag:.etag,
          template:{
            taskCount:.taskCount,
            parallelism:.parallelism,
            template:.template
          }
        }
      ' <<<"$document"
  )"
  verify_job_contract "$expected_job" "$execution_document" >/dev/null || {
    printf 'Cloud Run immutable execution drifted from the verified job template.\n' \
      >&2
    return 1
  }
}

health_smoke() {
  local base_url="$1"
  local live
  local ready
  local status
  local thread_id

  live="$(curl --fail --silent --show-error --max-redirs 0 \
    --max-time 20 "${base_url%/}/live")"
  ready="$(curl --fail --silent --show-error --max-redirs 0 \
    --max-time 20 "${base_url%/}/ready")"
  jq -e '. == {"status":"alive"}' >/dev/null <<<"$live"
  jq -e '. == {"status":"ready"}' >/dev/null <<<"$ready"

  thread_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
  status="$(
    curl --silent --show-error \
      --output /dev/null \
      --write-out '%{http_code}' \
      --max-redirs 0 \
      --max-time 20 \
      --header 'Content-Type: application/json' \
      --request POST \
      --data '{"id":1,"method":"run.start","params":{"assistant_id":"agent","input":{"messages":[]}}}' \
      "${base_url%/}/threads/${thread_id}/commands"
  )"
  [[ "$status" == "401" ]] || {
    printf 'unauthenticated APv2 mutation returned HTTP %s, expected 401.\n' \
      "$status" >&2
    return 1
  }
}

protocol_smoke() {
  local base_url="$1"
  LIVE_SMOKE_TOKEN="$SMOKE_BEARER_TOKEN" \
    uv run --frozen --package syshin0116-dev-agent \
    python scripts/smoke.py \
      --base-url "$base_url" \
      --assistant-id agent \
      --profile aegra-0.9.25 \
      --token-env LIVE_SMOKE_TOKEN \
      --timeout 180
}

run_job_with_digest() {
  local job="$1"
  local job_etag
  local operation

  update_job_image "$job" "$IMAGE_DIGEST"
  job_etag="$(verify_job_contract "$job" "" "$IMAGE_DIGEST")"
  operation="$(cloud_run_api_run_job "$job" "$job_etag")"
  wait_for_job_operation "$operation" "$job"
}

update_job_image() {
  local image_digest="$2"
  local job="$1"

  if [[ "$image_digest" != "${EXPECTED_IMAGE_PREFIX}"* ]] ||
    [[ ! "${image_digest#"$EXPECTED_IMAGE_PREFIX"}" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'refusing to update a job to an unselected image digest.\n' >&2
    return 1
  fi
  gcloud run jobs update "$job" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --image "$image_digest" \
    --quiet
  verify_job_contract "$job" "" "$image_digest" >/dev/null
}

sync_jobs_to_digest() {
  local image_digest="$1"

  update_job_image "$EXPECTED_MIGRATION_JOB" "$image_digest"
  update_job_image "$EXPECTED_GRANT_JOB" "$image_digest"
  update_job_image "$EXPECTED_MAINTENANCE_JOB" "$image_digest"
}

restore_jobs_to_digest() {
  local failed="false"
  local image_digest="$1"
  local job

  for job in \
    "$EXPECTED_MIGRATION_JOB" \
    "$EXPECTED_GRANT_JOB" \
    "$EXPECTED_MAINTENANCE_JOB"; do
    if ! update_job_image "$job" "$image_digest"; then
      failed="true"
    fi
  done
  [[ "$failed" == "false" ]]
}

verify_scheduled_maintenance_digest() {
  local image_digest="$1"

  [[ -n "$EXPECTED_SCHEDULED_MAINTENANCE_JOB" ]] || return 0
  verify_job_contract \
    "$EXPECTED_SCHEDULED_MAINTENANCE_JOB" \
    "" \
    "$image_digest" >/dev/null
}

update_scheduled_maintenance_digest() {
  local image_digest="$1"

  [[ -n "$EXPECTED_SCHEDULED_MAINTENANCE_JOB" ]] || return 0
  update_job_image "$EXPECTED_SCHEDULED_MAINTENANCE_JOB" "$image_digest"
}

set_revision_traffic() {
  local revision="$1"
  gcloud run services update-traffic "$CLOUD_RUN_SERVICE" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --to-revisions "${revision}=100" \
    --quiet
}

require_serving_revision() {
  local expected_revision="$1"
  local actual_revision

  actual_revision="$(serving_revision)"
  [[ "$actual_revision" == "$expected_revision" ]] || {
    printf 'Cloud Run traffic resolved to %s instead of %s.\n' \
      "$actual_revision" "$expected_revision" >&2
    return 1
  }
}

verified_smoke_url() {
  local document
  local expected_serving_revision="$1"
  local expected_smoke_revision="$2"
  document="$(service_json)"

  jq -er \
    --arg expected_service "projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/services/${CLOUD_RUN_SERVICE}" \
    --arg expected_service_short "$CLOUD_RUN_SERVICE" \
    --arg expected_serving_revision "$expected_serving_revision" \
    --arg expected_smoke_revision "$expected_smoke_revision" \
    --arg expected_smoke_url "https://smoke---${CLOUD_RUN_SERVICE}-${EXPECTED_PROJECT_NUMBER}.${GCP_REGION}.run.app" \
    '
      def canonical_revision_id($value):
        ($value | type) == "string"
        and ($value | test("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"))
        and ($value | startswith($expected_service_short + "-"))
        and (
          $expected_service_short != "agent"
          or ($value | startswith("agent-preview-") | not)
        );
      def full_revision_id($value):
        if (
          ($value | type) == "string"
          and ($value | startswith($expected_service + "/revisions/"))
          and (
            $value
            | ltrimstr($expected_service + "/revisions/")
            | canonical_revision_id(.)
          )
        )
        then ($value | ltrimstr($expected_service + "/revisions/"))
        else error("revision is outside the selected service")
        end;
      def explicit_revision_id($value):
        if canonical_revision_id($value)
        then $value
        else full_revision_id($value)
        end;
      def absent_or_empty_string($value):
        $value == null
        or (($value | type) == "string" and $value == "");
      def absent_or_zero($value):
        $value == null
        or (($value | type) == "number" and $value == 0);
      def explicit_revision_type($value):
        $value == null
        or (
          ($value | type) == "string"
          and (
            $value == "TRAFFIC_TARGET_ALLOCATION_TYPE_UNSPECIFIED"
            or $value == "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION"
          )
        );
      def resolved_revision($target):
        if (
          $target.type
            == "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
          and absent_or_empty_string($target.revision)
        )
        then full_revision_id(.latestReadyRevision)
        elif (
          explicit_revision_type($target.type)
        )
        then explicit_revision_id($target.revision)
        else error("traffic target does not resolve to a canonical revision")
        end;
      def canonical_service_uri:
        type == "string"
        and test("^https://[a-z0-9-]+(\\.[a-z0-9-]+)*\\.run\\.app$")
        and startswith("https://" + $expected_service_short + "-")
        and (
          $expected_service_short != "agent"
          or (startswith("https://agent-preview-") | not)
        );
      def observed_traffic:
        if .trafficStatuses == null
        then .traffic
        else .trafficStatuses
        end;

      observed_traffic as $traffic
      | [
        $traffic[]
        | select(absent_or_empty_string(.tag))
      ] as $serving
      | [
        $traffic[]
        | select(.tag == "smoke")
      ] as $smoke
      | if (
          ($traffic | type) == "array"
          and ($traffic | length) == 2
          and ($serving | length) == 1
          and (resolved_revision($serving[0]) == $expected_serving_revision)
          and ($serving[0].percent == 100)
          and ($smoke | length) == 1
          and explicit_revision_type($smoke[0].type)
          and (explicit_revision_id($smoke[0].revision) == $expected_smoke_revision)
          and absent_or_zero($smoke[0].percent)
          and (.uri | canonical_service_uri)
          and ($smoke[0].uri == ("https://smoke---" + (.uri | ltrimstr("https://"))))
        )
        then $expected_smoke_url
        else error("traffic does not match the exact smoke-stage shape")
        end
    ' <<<"$document" || {
    printf 'Cloud Run smoke tag did not bind exactly to revision %s.\n' \
      "$expected_smoke_revision" >&2
    return 1
  }
}

remove_smoke_tag() {
  local document
  document="$(service_json)"

  if jq -e '
    def observed_traffic:
      if .trafficStatuses == null
      then .traffic
      else .trafficStatuses
      end;
    observed_traffic as $traffic
    | ($traffic | type) == "array"
      and any($traffic[]; .tag == "smoke")
  ' \
    >/dev/null <<<"$document"; then
    gcloud run services update-traffic "$CLOUD_RUN_SERVICE" \
      --project "$GCP_PROJECT_ID" \
      --region "$GCP_REGION" \
      --remove-tags smoke \
      --quiet
  fi

  service_json |
    jq -e '
      def observed_traffic:
        if .trafficStatuses == null
        then .traffic
        else .trafficStatuses
        end;
      observed_traffic as $traffic
      | ($traffic | type) == "array"
        and all($traffic[]; .tag != "smoke")
    ' \
      >/dev/null || {
    printf 'Cloud Run smoke tag cleanup did not reach verified absence.\n' >&2
    return 1
  }
}

revision_belongs_to_service() {
  local revision="$1"

  case "$CLOUD_RUN_SERVICE" in
    agent-preview)
      [[ "$revision" == agent-preview-* ]]
      ;;
    agent)
      [[ "$revision" == agent-* && "$revision" != agent-preview-* ]]
      ;;
    *)
      return 1
      ;;
  esac
}

validate_inputs() {
  for command_name in curl gcloud jq python3 sed uv; do
    require_command "$command_name"
  done
  for variable_name in \
    CLOUD_RUN_SERVICE \
    GCP_PROJECT_ID \
    GCP_REGION \
    SMOKE_BEARER_TOKEN; do
    require_value "$variable_name"
  done
  [[ "$GCP_PROJECT_ID" == "$EXPECTED_PROJECT_ID" ]] || {
    printf 'unexpected GCP project\n' >&2
    exit 1
  }
  [[ "$GCP_REGION" == "$EXPECTED_REGION" ]] || {
    printf 'unexpected GCP region\n' >&2
    exit 1
  }
  [[ "$CLOUD_RUN_SERVICE" =~ ^agent(-preview)?$ ]] || {
    printf 'unexpected Cloud Run service\n' >&2
    exit 1
  }
  runtime_expectations
}

validate_deploy_inputs() {
  for variable_name in \
    DELIVERY_RUN_ATTEMPT \
    DELIVERY_RUN_ID \
    GRANT_PROBE_JOB \
    IMAGE_DIGEST \
    MAINTENANCE_JOB \
    MIGRATION_JOB \
    SOURCE_SHA; do
    require_value "$variable_name"
  done
  [[ "$DELIVERY_RUN_ID" =~ ^[1-9][0-9]{0,19}$ ]] || {
    printf 'DELIVERY_RUN_ID must be a positive numeric GitHub run ID.\n' >&2
    exit 1
  }
  [[ "$DELIVERY_RUN_ATTEMPT" =~ ^[1-9][0-9]{0,15}$ ]] || {
    printf 'DELIVERY_RUN_ATTEMPT must be a positive numeric GitHub run attempt.\n' >&2
    exit 1
  }
  [[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'SOURCE_SHA must be a full lowercase commit SHA.\n' >&2
    exit 1
  }
  [[ "$MIGRATION_JOB" == "$EXPECTED_MIGRATION_JOB" ]] || {
    printf '%s service must use only its exact migration job\n' \
      "$CLOUD_RUN_SERVICE" >&2
    exit 1
  }
  [[ "$GRANT_PROBE_JOB" == "$EXPECTED_GRANT_JOB" ]] || {
    printf '%s service must use only its exact grant-probe job\n' \
      "$CLOUD_RUN_SERVICE" >&2
    exit 1
  }
  [[ "$MAINTENANCE_JOB" == "$EXPECTED_MAINTENANCE_JOB" ]] || {
    printf '%s service must use only its exact maintenance job\n' \
      "$CLOUD_RUN_SERVICE" >&2
    exit 1
  }
  if [[ "$IMAGE_DIGEST" != "${EXPECTED_IMAGE_PREFIX}"* ]] ||
    [[ ! "${IMAGE_DIGEST#"$EXPECTED_IMAGE_PREFIX"}" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'image digest is outside the selected isolated repository\n' >&2
    exit 1
  fi
}

deploy() {
  local jobs_restore_failed="false"
  local previous_revision
  local previous_image_digest
  local new_revision=""
  local smoke_url
  local jobs_mutation_attempted="false"
  local scheduled_job_mutation_attempted="false"
  local scheduled_job_restore_failed="false"
  local traffic_shift_attempted="false"

  validate_deploy_inputs
  verify_service_contract
  remove_smoke_tag
  previous_revision="$(serving_revision)"
  revision_belongs_to_service "$previous_revision" || {
    printf 'current ready revision is outside the selected service.\n' >&2
    return 1
  }
  verify_revision_contract "$previous_revision"
  previous_image_digest="$(revision_image_digest "$previous_revision")"
  verify_scheduled_maintenance_digest "$previous_image_digest"

  rollback_on_error() {
    local status="$1"
    local cleanup_failed="false"
    local restore_failed="false"
    trap - ERR INT TERM
    if ! remove_smoke_tag; then
      cleanup_failed="true"
    fi
    if [[ "$traffic_shift_attempted" == "true" ]]; then
      printf 'Deployment failed; restoring traffic to %s.\n' \
        "$previous_revision" >&2
      if ! set_revision_traffic "$previous_revision" ||
        ! require_serving_revision "$previous_revision"; then
        restore_failed="true"
      fi
    fi
    if [[ "$jobs_mutation_attempted" == "true" ]] &&
      ! restore_jobs_to_digest "$previous_image_digest"; then
      jobs_restore_failed="true"
    fi
    if [[ "$scheduled_job_mutation_attempted" == "true" ]] &&
      ! update_scheduled_maintenance_digest "$previous_image_digest"; then
      scheduled_job_restore_failed="true"
    fi
    if [[ "$cleanup_failed" == "true" ]]; then
      printf 'Deployment failed and the public smoke tag could not be removed.\n' >&2
    fi
    if [[ "$restore_failed" == "true" ]]; then
      printf 'Deployment failed and previous revision traffic restoration also failed.\n' >&2
    fi
    if [[ "$jobs_restore_failed" == "true" ]]; then
      printf 'Deployment failed and previous revision job-image restoration also failed.\n' >&2
    fi
    if [[ "$scheduled_job_restore_failed" == "true" ]]; then
      printf 'Deployment failed and scheduled maintenance image restoration also failed.\n' >&2
    fi
    exit "$status"
  }
  trap 'rollback_on_error $?' ERR
  trap 'rollback_on_error 130' INT
  trap 'rollback_on_error 143' TERM

  jobs_mutation_attempted="true"
  run_job_with_digest "$MIGRATION_JOB"
  run_job_with_digest "$GRANT_PROBE_JOB"
  run_job_with_digest "$MAINTENANCE_JOB"

  gcloud run services update "$CLOUD_RUN_SERVICE" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --image "$IMAGE_DIGEST" \
    --revision-suffix "g${SOURCE_SHA:0:8}-r${DELIVERY_RUN_ID}-a${DELIVERY_RUN_ATTEMPT}" \
    --no-traffic \
    --quiet

  new_revision="$(
    service_json |
      jq -er '
        .latestCreatedRevision
        | select(type == "string" and length > 0)
        | split("/")[-1]
      '
  )"
  [[ "$new_revision" == "${CLOUD_RUN_SERVICE}-g${SOURCE_SHA:0:8}-r${DELIVERY_RUN_ID}-a${DELIVERY_RUN_ATTEMPT}" ]] || {
    printf 'Cloud Run created an unexpected revision name.\n' >&2
    return 1
  }
  verify_revision_contract "$new_revision" "$IMAGE_DIGEST"
  verify_service_contract "$IMAGE_DIGEST"

  gcloud run services update-traffic "$CLOUD_RUN_SERVICE" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --set-tags "smoke=${new_revision}" \
    --quiet
  smoke_url="$(verified_smoke_url "$previous_revision" "$new_revision")"
  health_smoke "$smoke_url"
  protocol_smoke "$smoke_url"

  traffic_shift_attempted="true"
  set_revision_traffic "$new_revision"
  remove_smoke_tag
  require_serving_revision "$new_revision"

  health_smoke "$(service_url)"
  require_serving_revision "$new_revision"
  remove_smoke_tag
  scheduled_job_mutation_attempted="true"
  update_scheduled_maintenance_digest "$IMAGE_DIGEST"

  trap - ERR INT TERM
  printf 'Cloud Run deployment passed: service=%s revision=%s\n' \
    "$CLOUD_RUN_SERVICE" "$new_revision"
}

rollback() {
  local jobs_restore_failed="false"
  local previous_revision
  local previous_image_digest
  local rollback_image_digest
  local jobs_mutation_attempted="false"
  local scheduled_job_mutation_attempted="false"
  local scheduled_job_restore_failed="false"
  local traffic_shift_attempted="false"

  [[ -n "$REQUESTED_ROLLBACK_REVISION" ]] || {
    printf 'rollback mode requires an exact revision name.\n' >&2
    exit 1
  }
  revision_belongs_to_service "$REQUESTED_ROLLBACK_REVISION" || {
    printf 'rollback revision is outside the selected service.\n' >&2
    exit 1
  }
  remove_smoke_tag
  previous_revision="$(serving_revision)"
  revision_belongs_to_service "$previous_revision" || {
    printf 'current serving revision is outside the selected service.\n' >&2
    exit 1
  }
  verify_revision_contract "$REQUESTED_ROLLBACK_REVISION"
  rollback_image_digest="$(revision_image_digest "$REQUESTED_ROLLBACK_REVISION")"
  verify_revision_contract "$previous_revision"
  previous_image_digest="$(revision_image_digest "$previous_revision")"
  verify_scheduled_maintenance_digest "$previous_image_digest"

  rollback_on_error() {
    local status="$1"
    local cleanup_failed="false"
    local restore_failed="false"
    trap - ERR INT TERM
    if ! remove_smoke_tag; then
      cleanup_failed="true"
    fi
    if [[ "$traffic_shift_attempted" == "true" ]]; then
      printf 'Rollback smoke failed; restoring traffic to %s.\n' \
        "$previous_revision" >&2
      if ! set_revision_traffic "$previous_revision" ||
        ! require_serving_revision "$previous_revision"; then
        restore_failed="true"
      fi
    fi
    if [[ "$jobs_mutation_attempted" == "true" ]] &&
      ! restore_jobs_to_digest "$previous_image_digest"; then
      jobs_restore_failed="true"
    fi
    if [[ "$scheduled_job_mutation_attempted" == "true" ]] &&
      ! update_scheduled_maintenance_digest "$previous_image_digest"; then
      scheduled_job_restore_failed="true"
    fi
    if [[ "$cleanup_failed" == "true" ]]; then
      printf 'Rollback failed and the public smoke tag could not be removed.\n' >&2
    fi
    if [[ "$restore_failed" == "true" ]]; then
      printf 'Rollback failed and previous revision traffic restoration also failed.\n' >&2
    fi
    if [[ "$jobs_restore_failed" == "true" ]]; then
      printf 'Rollback failed and previous revision job-image restoration also failed.\n' >&2
    fi
    if [[ "$scheduled_job_restore_failed" == "true" ]]; then
      printf 'Rollback failed and scheduled maintenance image restoration also failed.\n' >&2
    fi
    exit "$status"
  }
  trap 'rollback_on_error $?' ERR
  trap 'rollback_on_error 130' INT
  trap 'rollback_on_error 143' TERM

  traffic_shift_attempted="true"
  set_revision_traffic "$REQUESTED_ROLLBACK_REVISION"
  require_serving_revision "$REQUESTED_ROLLBACK_REVISION"
  health_smoke "$(service_url)"
  protocol_smoke "$(service_url)"
  jobs_mutation_attempted="true"
  sync_jobs_to_digest "$rollback_image_digest"
  remove_smoke_tag
  require_serving_revision "$REQUESTED_ROLLBACK_REVISION"
  scheduled_job_mutation_attempted="true"
  update_scheduled_maintenance_digest "$rollback_image_digest"
  trap - ERR INT TERM
  printf 'Cloud Run rollback passed: service=%s revision=%s\n' \
    "$CLOUD_RUN_SERVICE" "$REQUESTED_ROLLBACK_REVISION"
}

validate_inputs
case "$MODE" in
  deploy)
    deploy
    ;;
  rollback)
    rollback
    ;;
  *)
    printf 'usage: %s deploy | %s rollback REVISION\n' "$0" "$0" >&2
    exit 2
    ;;
esac
