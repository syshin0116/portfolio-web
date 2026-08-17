#!/usr/bin/env bash
# Run the locally-runnable half of Application CI before a push.
#
# CI is the authority; this only catches the failures that do not need Postgres,
# Docker, or a GitHub runner, so that a red build is not the first time anyone
# finds out. It reuses the same change detection CI uses, so a push that touches
# nothing testable stays fast.
#
# Usage: scripts/preflight.sh [remote-ref]
set -uo pipefail

cd "$(git rev-parse --show-toplevel)" || exit 1

log() { printf '\n\033[1m== %s\033[0m\n' "$1" >&2; }
fail() { printf '\033[31mpreflight: %s\033[0m\n' "$1" >&2; exit 1; }

# The browser suite binds a fixed fixture port, so two concurrent runs - a manual
# one and the pre-push hook, typically - would fail each other on the port rather
# than on the code.
# A killed run must not lock every later push out, so the holder's PID decides
# whether the lock is live or leftover.
lock="${TMPDIR:-/tmp}/syshin0116-preflight.lock"
if ! mkdir "$lock" 2>/dev/null; then
  holder="$(cat "$lock/pid" 2>/dev/null || true)"
  if [[ -n "$holder" ]] && kill -0 "$holder" 2>/dev/null; then
    fail "another preflight run is in progress (pid $holder)"
  fi
  rm -rf "$lock"
  mkdir "$lock" 2>/dev/null || fail "cannot acquire the preflight lock ($lock)"
fi
echo "$$" >"$lock/pid"
trap 'rm -rf "$lock"' EXIT

# What is about to be pushed. An unpushed branch is compared against main.
head="$(git rev-parse HEAD)"
if base="$(git rev-parse --verify --quiet "@{upstream}")"; then
  :
elif base="$(git rev-parse --verify --quiet origin/main)"; then
  :
else
  fail "cannot resolve a base commit to diff against"
fi
merge_base="$(git merge-base "$base" "$head")" || fail "cannot resolve a merge base"
if [[ "$merge_base" == "$head" ]]; then
  echo "preflight: nothing to push" >&2
  exit 0
fi

changed="$(git diff --no-renames --name-only "$merge_base" "$head")"
touches() { grep -qE "$1" <<<"$changed"; }

web=false
agent=false
touches '^web/' && web=true
touches '^(agent/|eval/|scripts/|Dockerfile|aegra\.json|pyproject\.toml|uv\.lock)' && agent=true

if [[ "$web" == false && "$agent" == false ]]; then
  echo "preflight: no web or agent paths changed" >&2
  exit 0
fi

if [[ "$web" == true ]]; then
  log "web: unit tests, lint, types, browser journey"
  ( cd web && bun run test ) || fail "web unit tests failed"
  ( cd web && bun run lint ) || fail "web lint failed"
  ( cd web && bunx tsc --noEmit --incremental false ) || fail "web type check failed"
  ( cd web && bun run test:browser ) || fail "web browser tests failed"
fi

if [[ "$agent" == true ]]; then
  log "agent: format, lint, tests"
  ruff_targets=(agent/src agent/tests scripts/build_index.py scripts/ci_changed_components.py
    scripts/upstream_version_audit.py scripts/verify_repository_governance.py
    scripts/verify_vercel_production.py scripts/tests)
  uv run --frozen --package syshin0116-dev-agent ruff check "${ruff_targets[@]}" \
    || fail "ruff check failed"
  uv run --frozen --package syshin0116-dev-agent ruff format --check "${ruff_targets[@]}" \
    || fail "ruff format check failed"

  pytest_log="$(mktemp)"
  trap 'rm -rf "$lock"; rm -f "$pytest_log"' EXIT
  uv run --frozen --package syshin0116-dev-agent --all-extras \
    pytest -q agent/tests/unit_tests 2>&1 | tee "$pytest_log"
  status="${PIPESTATUS[0]}"
  if [[ "$status" -ne 0 ]]; then
    # content/ is an Obsidian vault here, so .obsidian/ and .DS_Store make the
    # corpus builder's exact filesystem-tree check disagree with the committed
    # tree. That is a local-checkout artifact; CI runs on a clean tree. Let it
    # through only when every failure is that one, so real breakage still blocks.
    drift_errors="$(grep -cE '^(ERROR|FAILED) ' "$pytest_log")"
    drift_only="$(grep -c 'content filesystem bytes/modes differ' "$pytest_log")"
    if [[ "$drift_errors" -gt 0 && "$drift_only" -gt 0 && "$drift_errors" -le "$drift_only" ]]; then
      printf '\033[33mpreflight: ignoring %s corpus-tree error(s) caused by untracked files under content/\033[0m\n' \
        "$drift_errors" >&2
    else
      fail "agent tests failed"
    fi
  fi
fi

log "preflight passed"
