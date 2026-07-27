#!/usr/bin/env bash
set -eEuo pipefail

readonly MODE="${1:-}"
readonly REQUESTED_ROLLBACK_REVISION="${2:-}"
readonly EXPECTED_PROJECT_ID="festive-ally-503605-v7"
readonly EXPECTED_REGION="us-east4"

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

service_json() {
  gcloud run services describe "$CLOUD_RUN_SERVICE" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --format=json
}

revision_json() {
  local revision="$1"
  gcloud run revisions describe "$revision" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --format=json
}

serving_revision() {
  service_json |
    jq -er '
      [
        .status.traffic[]
        | select((.tag // "") == "" and (.percent // 0) == 100)
        | .revisionName
      ]
      | unique
      | if length == 1 then .[0] else error("expected exactly one 100% serving revision") end
    '
}

service_url() {
  service_json | jq -er '.status.url'
}

verify_service_contract() {
  local document
  document="$(service_json)"
  jq -e \
    --arg expected_service "$CLOUD_RUN_SERVICE" \
    '
      (.metadata.name == $expected_service)
      and (
        .spec.template.metadata.annotations["autoscaling.knative.dev/maxScale"] == "1"
        or .template.scaling.maxInstanceCount == 1
      )
      and (
        .spec.template.spec.containerConcurrency == 8
        or .template.maxInstanceRequestConcurrency == 8
      )
      and (
        .spec.template.spec.containers[0].command == ["uvicorn"]
        or .template.containers[0].command == ["uvicorn"]
      )
      and (
        .spec.template.spec.containers[0].args
        // .template.containers[0].args
      ) == [
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
          (
            .spec.template.spec.containers[0].env
            // .template.containers[0].env
            // []
          )[]
          | (
              .valueFrom.secretKeyRef.key
              // .valueSource.secretKeyRef.version
              // empty
            )
        ] as $secret_versions
        | ($secret_versions | length) == 5
          and all(
            $secret_versions[];
            type == "string" and test("^[1-9][0-9]*$")
          )
      )
    ' >/dev/null <<<"$document" || {
    printf 'Cloud Run service contract drifted from runtime or numeric secret pins.\n' >&2
    return 1
  }
}

verify_revision_digest() {
  local revision="$1"
  local document
  document="$(revision_json "$revision")"
  jq -e \
    --arg expected_image "$IMAGE_DIGEST" \
    '
      (
        .status.imageDigest
        // .spec.containers[0].image
        // .template.containers[0].image
      ) == $expected_image
    ' >/dev/null <<<"$document" || {
    printf 'Cloud Run revision does not run the selected immutable digest.\n' >&2
    return 1
  }
}

verify_revision_contract() {
  local revision="$1"
  local document
  local expected_image_prefix
  local expected_runtime_service_account
  local expected_secret_names

  case "$CLOUD_RUN_SERVICE" in
    agent-preview)
      expected_image_prefix="us-east4-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent@sha256:"
      expected_runtime_service_account="agent-preview-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
      expected_secret_names="$(
        jq -cn '[
          "agent-preview-anthropic-api-key",
          "agent-preview-auth-secret",
          "agent-preview-database-url",
          "agent-preview-langsmith-api-key",
          "agent-preview-openai-api-key"
        ]'
      )"
      ;;
    agent)
      expected_image_prefix="us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:"
      expected_runtime_service_account="agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
      expected_secret_names="$(
        jq -cn '[
          "agent-auth-secret",
          "agent-database-url",
          "anthropic-api-key",
          "langsmith-api-key",
          "openai-api-key"
        ]'
      )"
      ;;
  esac

  document="$(revision_json "$revision")"
  jq -e \
    --arg expected_image_prefix "$expected_image_prefix" \
    --arg expected_revision "$revision" \
    --arg expected_runtime_service_account "$expected_runtime_service_account" \
    --arg expected_service "$CLOUD_RUN_SERVICE" \
    --argjson expected_secret_names "$expected_secret_names" \
    '
      .metadata.name == $expected_revision
      and (
        .metadata.labels["serving.knative.dev/service"] == $expected_service
        or (
          (.service // "")
          | endswith("/services/" + $expected_service)
        )
      )
      and any(
        .status.conditions[]?;
        .type == "Ready"
        and (.status == "True" or .state == "CONDITION_SUCCEEDED")
      )
      and (
        .spec.serviceAccountName
        // .spec.serviceAccount
        // .serviceAccount
      ) == $expected_runtime_service_account
      and (
        .metadata.annotations["autoscaling.knative.dev/maxScale"] == "1"
        or .scaling.maxInstanceCount == 1
      )
      and (
        .spec.containerConcurrency == 8
        or .maxInstanceRequestConcurrency == 8
      )
      and .spec.containers[0].command == ["uvicorn"]
      and .spec.containers[0].args == [
        "aegra_api.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
        "--workers",
        "1"
      ]
      and (
        .spec.containers[0].image as $image
        | ($image | type) == "string"
          and ($image | startswith($expected_image_prefix))
          and (
            $image
            | ltrimstr($expected_image_prefix)
            | test("^[0-9a-f]{64}$")
          )
      )
      and (
        [
          .spec.containers[0].env[]?
          | (
              .valueFrom.secretKeyRef.name
              // .valueSource.secretKeyRef.secret
              // empty
            ) as $secret
          | (
              .valueFrom.secretKeyRef.key
              // .valueSource.secretKeyRef.version
              // empty
            ) as $version
          | {secret: $secret, version: $version}
        ] as $secrets
        | ($secrets | length) == 5
          and ([$secrets[].secret] | sort) == ($expected_secret_names | sort)
          and all(
            $secrets[].version;
            type == "string" and test("^[1-9][0-9]*$")
          )
      )
    ' >/dev/null <<<"$document" || {
    printf 'Cloud Run revision %s is not a ready, environment-matched immutable runtime contract.\n' \
      "$revision" >&2
    return 1
  }
}

health_smoke() {
  local base_url="$1"
  local live
  local ready
  local status
  local thread_id

  live="$(curl --fail --silent --show-error \
    --max-time 20 "${base_url%/}/live")"
  ready="$(curl --fail --silent --show-error \
    --max-time 20 "${base_url%/}/ready")"
  jq -e '. == {"status":"alive"}' >/dev/null <<<"$live"
  jq -e '. == {"status":"ready"}' >/dev/null <<<"$ready"

  thread_id="$(
    python3 -c 'import uuid; print(uuid.uuid4())'
  )"
  status="$(
    curl --silent --show-error \
      --output /dev/null \
      --write-out '%{http_code}' \
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
    uv run --no-project --with httpx==0.28.1 \
    python scripts/smoke.py \
      --base-url "$base_url" \
      --assistant-id agent \
      --profile aegra-0.9.24 \
      --token-env LIVE_SMOKE_TOKEN \
      --timeout 180
}

run_job_with_digest() {
  local job="$1"
  gcloud run jobs update "$job" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --image "$IMAGE_DIGEST" \
    --quiet
  gcloud run jobs execute "$job" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --wait \
    --quiet
}

set_revision_traffic() {
  local revision="$1"
  gcloud run services update-traffic "$CLOUD_RUN_SERVICE" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --to-revisions "${revision}=100" \
    --quiet
}

remove_smoke_tag() {
  local document
  document="$(service_json)"

  if jq -e 'any(.status.traffic[]?; .tag == "smoke")' \
    >/dev/null <<<"$document"; then
    gcloud run services update-traffic "$CLOUD_RUN_SERVICE" \
      --project "$GCP_PROJECT_ID" \
      --region "$GCP_REGION" \
      --remove-tags smoke \
      --quiet
  fi

  service_json |
    jq -e 'all(.status.traffic[]?; (.tag // "") != "smoke")' >/dev/null || {
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
  for command_name in curl gcloud jq python3 uv; do
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
}

validate_deploy_inputs() {
  for variable_name in \
    DELIVERY_RUN_ATTEMPT \
    DELIVERY_RUN_ID \
    GRANT_PROBE_JOB \
    IMAGE_DIGEST \
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
  [[ "$MIGRATION_JOB" =~ ^agent(-preview)?-migrate$ ]] || {
    printf 'unexpected migration job\n' >&2
    exit 1
  }
  [[ "$GRANT_PROBE_JOB" =~ ^agent(-preview)?-grants$ ]] || {
    printf 'unexpected grant-probe job\n' >&2
    exit 1
  }
  case "$CLOUD_RUN_SERVICE" in
    agent-preview)
      [[ "$IMAGE_DIGEST" =~ ^us-east4-docker\.pkg\.dev/festive-ally-503605-v7/agent-preview/agent@sha256:[0-9a-f]{64}$ ]] || {
        printf 'preview image digest is outside the isolated preview repository\n' >&2
        exit 1
      }
      if [[ "$MIGRATION_JOB" != "agent-preview-migrate" ]] ||
        [[ "$GRANT_PROBE_JOB" != "agent-preview-grants" ]]; then
        printf 'preview service must use only preview one-shot jobs\n' >&2
        exit 1
      fi
      ;;
    agent)
      [[ "$IMAGE_DIGEST" =~ ^us-east4-docker\.pkg\.dev/festive-ally-503605-v7/agent/agent@sha256:[0-9a-f]{64}$ ]] || {
        printf 'production image digest is outside the production repository\n' >&2
        exit 1
      }
      if [[ "$MIGRATION_JOB" != "agent-migrate" ]] ||
        [[ "$GRANT_PROBE_JOB" != "agent-grants" ]]; then
        printf 'production service must use only production one-shot jobs\n' >&2
        exit 1
      fi
      ;;
  esac
}

deploy() {
  local previous_revision
  local new_revision=""
  local smoke_url
  local promoted="false"

  validate_deploy_inputs
  verify_service_contract
  previous_revision="$(serving_revision)"
  revision_belongs_to_service "$previous_revision" || {
    printf 'current ready revision is outside the selected service.\n' >&2
    return 1
  }
  # A stale public smoke URL is removed before jobs or revision creation.
  remove_smoke_tag

  rollback_on_error() {
    local status=$?
    local cleanup_failed="false"
    local restore_failed="false"
    trap - ERR
    if ! remove_smoke_tag; then
      cleanup_failed="true"
    fi
    if [[ -n "$new_revision" || "$promoted" == "true" ]]; then
      printf 'Deployment failed; restoring traffic to %s.\n' \
        "$previous_revision" >&2
      if ! set_revision_traffic "$previous_revision"; then
        restore_failed="true"
      fi
    fi
    if [[ "$cleanup_failed" == "true" ]]; then
      printf 'Deployment failed and the public smoke tag could not be removed.\n' >&2
    fi
    if [[ "$restore_failed" == "true" ]]; then
      printf 'Deployment failed and previous revision traffic restoration also failed.\n' >&2
    fi
    exit "$status"
  }
  trap rollback_on_error ERR

  # Schema first, then the least-privileged real-Neon grant/denial probe.
  run_job_with_digest "$MIGRATION_JOB"
  run_job_with_digest "$GRANT_PROBE_JOB"

  gcloud run services update "$CLOUD_RUN_SERVICE" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --image "$IMAGE_DIGEST" \
    --revision-suffix "g${SOURCE_SHA:0:8}-r${DELIVERY_RUN_ID}-a${DELIVERY_RUN_ATTEMPT}" \
    --no-traffic \
    --quiet

  new_revision="$(
    service_json | jq -er '.status.latestCreatedRevisionName'
  )"
  [[ "$new_revision" == "${CLOUD_RUN_SERVICE}-g${SOURCE_SHA:0:8}-r${DELIVERY_RUN_ID}-a${DELIVERY_RUN_ATTEMPT}" ]] || {
    printf 'Cloud Run created an unexpected revision name.\n' >&2
    return 1
  }
  verify_revision_digest "$new_revision"
  verify_revision_contract "$new_revision"
  verify_service_contract

  gcloud run services update-traffic "$CLOUD_RUN_SERVICE" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --set-tags "smoke=${new_revision}" \
    --quiet
  smoke_url="$(
    service_json |
      jq -er '.status.traffic[] | select(.tag == "smoke") | .url'
  )"
  health_smoke "$smoke_url"

  set_revision_traffic "$new_revision"
  promoted="true"
  remove_smoke_tag

  # This is intentionally after traffic shift: failure invokes revision rollback.
  health_smoke "$(service_url)"
  protocol_smoke "$(service_url)"
  [[ "$(serving_revision)" == "$new_revision" ]]
  remove_smoke_tag

  trap - ERR
  printf 'Cloud Run deployment passed: service=%s revision=%s\n' \
    "$CLOUD_RUN_SERVICE" "$new_revision"
}

rollback() {
  local previous_revision

  [[ -n "$REQUESTED_ROLLBACK_REVISION" ]] || {
    printf 'rollback mode requires an exact revision name.\n' >&2
    exit 1
  }
  revision_belongs_to_service "$REQUESTED_ROLLBACK_REVISION" || {
    printf 'rollback revision is outside the selected service.\n' >&2
    exit 1
  }
  previous_revision="$(serving_revision)"
  verify_revision_contract "$REQUESTED_ROLLBACK_REVISION"
  # Manual rollback never retains or creates a public smoke tag.
  remove_smoke_tag

  rollback_on_error() {
    local status=$?
    local cleanup_failed="false"
    local restore_failed="false"
    trap - ERR
    if ! remove_smoke_tag; then
      cleanup_failed="true"
    fi
    printf 'Rollback smoke failed; restoring traffic to %s.\n' \
      "$previous_revision" >&2
    if ! set_revision_traffic "$previous_revision"; then
      restore_failed="true"
    fi
    if [[ "$cleanup_failed" == "true" ]]; then
      printf 'Rollback failed and the public smoke tag could not be removed.\n' >&2
    fi
    if [[ "$restore_failed" == "true" ]]; then
      printf 'Rollback failed and previous revision traffic restoration also failed.\n' >&2
    fi
    exit "$status"
  }
  trap rollback_on_error ERR

  set_revision_traffic "$REQUESTED_ROLLBACK_REVISION"
  health_smoke "$(service_url)"
  protocol_smoke "$(service_url)"
  remove_smoke_tag
  trap - ERR
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
