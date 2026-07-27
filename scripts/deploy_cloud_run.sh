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
    ' >/dev/null <<<"$document" || {
    printf 'Cloud Run service contract drifted from one instance/one worker.\n' >&2
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
  gcloud run services update-traffic "$CLOUD_RUN_SERVICE" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --remove-tags smoke \
    --quiet >/dev/null 2>&1 || true
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
  for variable_name in GRANT_PROBE_JOB IMAGE_DIGEST MIGRATION_JOB SOURCE_SHA; do
    require_value "$variable_name"
  done
  [[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'SOURCE_SHA must be a full lowercase commit SHA.\n' >&2
    exit 1
  }
  [[ "$IMAGE_DIGEST" =~ ^us-east4-docker\.pkg\.dev/festive-ally-503605-v7/agent/agent@sha256:[0-9a-f]{64}$ ]] || {
    printf 'IMAGE_DIGEST is outside the reviewed immutable repository.\n' >&2
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
      [[ "$MIGRATION_JOB" == "agent-preview-migrate" ]] &&
        [[ "$GRANT_PROBE_JOB" == "agent-preview-grants" ]] || {
        printf 'preview service must use only preview one-shot jobs\n' >&2
        exit 1
      }
      ;;
    agent)
      [[ "$MIGRATION_JOB" == "agent-migrate" ]] &&
        [[ "$GRANT_PROBE_JOB" == "agent-grants" ]] || {
        printf 'production service must use only production one-shot jobs\n' >&2
        exit 1
      }
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

  rollback_on_error() {
    local status=$?
    trap - ERR
    remove_smoke_tag
    if [[ -n "$new_revision" || "$promoted" == "true" ]]; then
      printf 'Deployment failed; restoring traffic to %s.\n' \
        "$previous_revision" >&2
      set_revision_traffic "$previous_revision" || true
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
    --revision-suffix "g${SOURCE_SHA:0:10}" \
    --no-traffic \
    --quiet

  new_revision="$(
    service_json | jq -er '.status.latestCreatedRevisionName'
  )"
  [[ "$new_revision" == "${CLOUD_RUN_SERVICE}-g${SOURCE_SHA:0:10}" ]] || {
    printf 'Cloud Run created an unexpected revision name.\n' >&2
    return 1
  }
  verify_revision_digest "$new_revision"
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
  revision_json "$REQUESTED_ROLLBACK_REVISION" >/dev/null

  rollback_on_error() {
    local status=$?
    trap - ERR
    printf 'Rollback smoke failed; restoring traffic to %s.\n' \
      "$previous_revision" >&2
    set_revision_traffic "$previous_revision" || true
    exit "$status"
  }
  trap rollback_on_error ERR

  set_revision_traffic "$REQUESTED_ROLLBACK_REVISION"
  health_smoke "$(service_url)"
  protocol_smoke "$(service_url)"
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
