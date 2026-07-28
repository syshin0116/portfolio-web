---
title: "Native Aegra Cloud Run delivery runbook"
description: >
  Bootstrap, deploy, smoke, and roll back the digest-pinned native Aegra image through
  phase-scoped GitHub OIDC identities and Cloud Run revision traffic.
when_to_read: >
  Before applying the Cloud Run Terraform, enabling agent delivery, changing its
  workflows or image, rotating agent database credentials, or rolling back a revision.
tags: [operations, gcp, cloud-run, aegra, github-actions, neon, rollback]
status: stable
updated: "2026-07-29"
owners: ["@syshin0116"]
refs:
  - ../../infra/gcp/README.md
  - gcp-neon-foundation.md
  - ../adr/0004-adopt-aegra.md
  - ../adr/0007-postgres-on-neon-split-projects.md
  - ../plans/rag-restack.md
template: spec
---

# Native Aegra Cloud Run delivery runbook

The web application remains on Vercel. This delivery surface owns only the native Aegra
agent, its two Cloud Run services, and their one-shot jobs.

No checked-in file creates a Neon project, adds a Secret Manager payload, changes a GitHub
environment, or applies Terraform. Those are explicit external gates. Keep the repository
variable `AGENT_CLOUD_RUN_ENABLED` absent or set to `false` until every bootstrap check
below passes; both trigger workflows then report a deliberate skip instead of attempting a
half-configured deployment.

## Reviewed topology

| Environment | Service | Migration job | Runtime-grant job | Maintenance job | Runtime identity | Migration identity |
|---|---|---|---|---|---|---|
| Agent Preview | `agent-preview` | `agent-preview-migrate` | `agent-preview-grants` | `agent-preview-maintenance` | `agent-preview-runtime` | `agent-preview-migrator` |
| Agent Production | `agent` | `agent-migrate` | `agent-grants` | `agent-maintenance` | `agent-runtime` | `agent-prod-migrator` |

| Environment | Repository | Builder | Retention floor |
|---|---|---|---|
| Agent Preview | `agent-preview` | `agent-preview-image-builder` | 14 days and the most recent 20 versions |
| Agent Production | `agent` | `agent-image-builder` | 90 days and the most recent 30 versions |

Each builder has repository-scoped `roles/artifactregistry.writer` only on its matching
repository. Each deployer and the Google-managed Cloud Run service agent have
`roles/artifactregistry.reader` only on the matching repository; Cloud Run requires the
deploying principal to read selected image metadata, while only the service agent pulls
it at runtime. Each deployer receives the project custom role
`cloudRunAgentDelivery` only on its own service and three jobs. That role contains exactly
`run.services.get`, `run.services.update`, `run.revisions.get`, `run.jobs.get`,
`run.jobs.update`, `run.jobs.run`, and `run.operations.get`. It intentionally excludes
create, delete, IAM-policy mutation, and `run.jobs.runWithOverrides`. Each deployer also
has `actAs` only on that environment's runtime and migration identities. No deployer can
read Secret Manager payloads or write images, and preview code cannot write or select a
production image.

The dedicated `agent-maintenance-scheduler` identity has no database secret and no
project-wide role. It receives `roles/run.invoker` only on `agent-maintenance`. The
production-only `agent-guest-maintenance` Cloud Scheduler job uses OAuth to call the
Cloud Run Jobs v2 `:run` API every 15 minutes; preview maintenance runs only as part
of a reviewed preview release. The Google-managed Cloud Scheduler service agent must
retain `roles/cloudscheduler.serviceAgent` or authenticated schedules fail with 403.

The `github` workload-identity pool has one canonical active provider,
`github-production`. It explicitly maps the immutable numeric repository and owner claims,
then maps exact caller/reusable-workflow claims onto four disjoint values of
`attribute.delivery_role`: `preview-builder`, `preview-deployer`, `production-builder`,
and `production-deployer`. Its provider condition references only those mapped attributes,
so every condition field satisfies the Google WIF provider contract. Each service account
accepts only its matching value. The old `github-preview` provider remains
Terraform-managed with `disabled=true`, an inert condition over its mapped repository ID,
no usable delivery-role mapping, and `prevent_destroy`; it is retained only to make
retirement explicit and non-destructive.

The services intentionally allow unauthenticated Cloud Run invocation because browsers at
the Vercel site must reach them. Aegra's outer bearer-token middleware remains the
application authorization boundary: the delivery gate proves `/live` and `/ready` are
public while an unauthenticated APv2 `run.start` returns 401.

Both services use 1 GiB memory, `cpu_idle=true`, `startup_cpu_boost=true`, a 300-second
request timeout, `max_instances=1`, concurrency 8, and one Uvicorn worker. The instance
and worker limits are correctness constraints, not cost optimizations: Aegra 0.9.24's
same-thread mutation guard is process-local.

Each service revision has exactly 17 environment entries: 13 reviewed plain values and
four numeric-version secret references. The plain set includes
`REDIS_BROKER_ENABLED=false` and `BG_JOB_MAX_RETRIES=0`, reserving the runtime boundary
required by the bounded background-work preflight. The one-shot modules
`agent.migrate`, `agent.neon_grant_probe`, and `agent.maintenance` load through the side-effect-free
`agent` package and do not import `agent.graph` or its runtime preflight, so their
separate three-entry environment contract does not carry these service-only values.

## GitHub configuration

Create two GitHub deployment environments in addition to the existing Vercel `Preview`
and `Production` environments:

| Environment | Branch policy | Reviewer |
|---|---|---|
| `Agent Preview` | no branch restriction | `syshin0116`, self-review allowed |
| `Agent Production` | branch `main` only | `syshin0116`, self-review allowed |

Disable admin bypass on both environments. Each delivery has one approval boundary: the
builder runs first without a GitHub environment, then the separate release job references
the exact target environment once. The builder can write only to its isolated registry
and receives neither a deployer identity nor a smoke token. The approved release job can
read that registry and update only its service and jobs, but cannot write an image. This
keeps the writer and deployer credentials on different runners without falsely claiming
that one GitHub environment can require two independent approvals. Manual rollback also
uses only the release job and therefore one approval:
[GitHub deployment environments](https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments).

Both environments must contain **zero GitHub environment variables**. Identity and
resource selection is repository-owned: immediately before OIDC authentication,
`scripts/validate_agent_delivery_identity.sh` derives the canonical provider, exact
service account, repository, service, and jobs from the fixed `target` plus the
builder/deployer phase. A preview workflow therefore cannot substitute a production
identity or repository even if an in-repository pull request changes workflow code.

Set this GitHub **Environment secret** (not a repository or organization secret) in both
`Agent Preview` and `Agent Production`:

```text
AGENT_SMOKE_BEARER_TOKEN
```

It must be an owner HS256 bearer token accepted by `agent.auth`; it is never printed.
The token requires `sub`, `iss=syshin0116.dev`, `aud=agent-api`, `iat`, and `exp`.
Long-lived static JWTs are forbidden. Immediately before approving each release, replace
the target environment secret with a newly minted token whose total lifetime is at most
two hours and whose remaining lifetime is at least 65 minutes. The approved release
rechecks those public claims after approval and before GCP authentication; the live APv2
smoke remains the signature and authorization proof.

There is currently no repository-owned per-release token mint. That is an honest
automation gap: an operator must rotate the environment secret immediately before every
approved preview, production deploy, or rollback. If the pre-auth check or live smoke
reports expiry, do not reuse or lengthen the token. Mint a new bounded token, replace only
the matching environment secret, and rerun the workflow. A deploy fails before promotion;
a rollback smoke failure restores the prior serving revision. Do not store
`AGENT_AUTH_SECRET`, a database URL, a long-lived JWT, or a service-account JSON key in
GitHub. A later public-auth change may replace this prerequisite with a narrowly scoped
per-release mint.

The canonical active WIF provider requires the exact caller workflow
(`preview-agent.yml` or `deploy-agent.yml`) and the exact called reusable workflow
(`agent-image-build.yml` for builders or `agent-release.yml` for deployers) at the same
reviewed ref. Preview additionally accepts only the `pull_request` event. Production
accepts only `push` or `workflow_dispatch` at `refs/heads/main`. Only deployer claims
carry and must match `Agent Preview` or `Agent Production`; a builder claim with an
environment is rejected.

## Secret Manager payloads

The foundation owns four runtime secrets per environment. The deployed model is fixed to
Anthropic, so no OpenAI credential is managed, version-pinned, or injected. Add one separate
migration URL secret per environment:

```text
agent-preview-migration-database-url
agent-migration-database-url
```

Runtime services, grant-probe jobs, and maintenance jobs receive only the
least-privileged direct Neon runtime URL. Migration jobs receive only their elevated
direct migration URL. Neither URL
may contain a Neon `-pooler` hostname. Add values out of band as described in the
[foundation runbook](gcp-neon-foundation.md). Terraform never owns payloads or creates
versions, but it does own the reviewed **numeric version ID** selected by every service
and job. `latest`, `0`, and aliases are rejected. Cloud Run resolves a secret-backed
environment variable when an instance starts, so a mutable alias could silently change
after scale-to-zero without a new reviewed revision, smoke test, or reliable rollback.

Before rollout, prove on real Neon that the runtime role can perform Aegra's idempotent
checkpointer/store setup and DML but cannot create another schema, create a role, or hold
`rolsuper`, `rolcreaterole`, `rolcreatedb`, or `rolreplication`. The
`agent.neon_grant_probe` Cloud Run job makes that proof executable on every deployment.

## One-time bootstrap

Cloud Run cannot start before its secrets and schema exist, while the registry and
Secret Manager resources do not exist before the first apply. Resolve that dependency
without `-target`, temporary configuration, or a placeholder public service. Keep one
remote state and advance the explicit `agent_delivery_stage` in order:

1. **Foundation.** Confirm the split Neon projects/branches, keep
   `AGENT_CLOUD_RUN_ENABLED=false`, run every credential-free verifier, and plan with the
   defaults (`stage=foundation`, both image inputs and the version map null):

   ```sh
   scripts/verify_ops_foundation.sh --static
   scripts/verify_ops_foundation.sh --terraform-fmt
   scripts/verify_ops_foundation.sh --terraform-init
   scripts/verify_ops_foundation.sh --terraform-validate
   scripts/verify_ops_foundation.sh --terraform-test
   terraform -chdir=infra/gcp plan
   ```

   The plan must create/import both registries, identities, WIF, IAM, state bucket, and
   ten empty secret resources, with **zero** Cloud Run services or jobs. For the
   existing production registry, complete the cleanup-policy dry run below before
   approving its metadata change. Reject every persistent replacement/destroy and apply
   only the saved, owner-reviewed plan.

2. **Payloads and images.** Add all ten first secret versions out of band without
   printing payloads. Record only each positive numeric enabled version ID. Build the
   reviewed commit for Linux x86-64 with the checked-in Dockerfile once into each
   environment's isolated repository. Record and independently inspect both
   registry-resolved values:

   ```text
   us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:<64 lowercase hex>
   us-east4-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent@sha256:<64 lowercase hex>
   ```

   A tag is not accepted. The two digests may happen to contain identical image bytes,
   but bootstrap must still prove each path exists and is readable by only the matching
   delivery identities.

3. **Jobs.** Put the ten non-secret version IDs in a mode-`0600` variable file outside
   the repository as `agent_secret_versions = { ... }`. Plan and apply with both reviewed
   digests:

   ```sh
   terraform -chdir=infra/gcp plan \
     -var 'agent_delivery_stage=jobs' \
     -var 'agent_bootstrap_image=us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:REPLACE' \
     -var 'agent_preview_bootstrap_image=us-east4-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent@sha256:REPLACE' \
     -var-file=/absolute/private/path/agent-secret-versions.tfvars
   ```

   This plan must add exactly the two migration jobs, two grant-probe jobs, two
   maintenance jobs, and their resource IAM; it must still contain zero services or
   schedules. Apply the saved reviewed plan, then execute each environment's migration,
   grant probe, and maintenance job with `--wait`. Require all six jobs to use their
   environment's reviewed digest and pinned numeric secret versions.

4. **Services.** Re-plan with `agent_delivery_stage=services`, the same two digests, and
   the same external version file. The only delivery-surface additions are the two
   services, their resource IAM, and the production-only maintenance schedule. Apply only
   after both environments' migration, grant probe, and maintenance job passed. Run
   `scripts/verify_ops_foundation.sh --live`, configure and verify
   both GitHub environments, then set `AGENT_CLOUD_RUN_ENABLED=true` and immediately run
   the first reviewed preview and production deliveries. If either fails, set the
   variable back to `false` while investigating.

After bootstrap, every Terraform plan must explicitly retain `stage=services`, both
current exact digests, and the complete ten-key numeric version map. Omitting them
proposes protected resource removal and fails closed. Never “simplify” an apply with
`-target`; each stage is a complete, repeatable root-module plan.

The two retired OpenAI Secret Manager objects are removed from Terraform state with
`destroy = false`. This repository does not delete their external payloads or versions.
Delete them only as a separately approved GCP cleanup after confirming no consumer remains.

Terraform ignores subsequent image and traffic drift because the delivery workflow owns
those revision fields. Every other service/job field—including the selected numeric
secret versions—remains Terraform-owned and drift-visible.

## Registry cleanup and rollback support

Artifact Registry cannot delete tagged versions while immutable tags are enabled, so both
repositories intentionally set `immutable_tags = false`. This does not make a mutable tag
part of the trust boundary. Every delivery attempt writes a new
`git-<SHA>-run-<run ID>-attempt-<attempt>` tag, never looks up or reuses an existing tag,
resolves the pushed digest in that same builder job, and passes only that digest across
the builder/deployer boundary. Preview and production also have different repositories,
writers, and WIF identities.

The production delete policy matches any version older than 90 days and a keep policy
retains the most recent 30 versions. Preview uses 14 days and 20 versions. A keep match
wins over a delete match, so the supported registry-backed rollback window is **at least
90 days or 30 production versions**, and **at least 14 days or 20 preview versions**,
whichever retains more. Manual rollback outside that boundary is unsupported until the
operator proves the digest still exists. Google documents that Cloud Run imports an image
and does not pull it again for new instances of a serving revision, but it only promises
to retain that copy while the image is used by a serving revision. Do not rely on a
zero-traffic revision's imported copy as the sole recovery artifact:
[Cloud Run image behavior](https://cloud.google.com/run/docs/deploying#images).

Before the first apply that changes the existing `agent` repository, test the exact two
production policies as a dry run:

1. Enable Artifact Registry `DATA_WRITE` audit logs, inventory every current and
   zero-traffic production revision plus its digest, and save that non-secret inventory
   with the plan review.
2. Put the exact `delete-after-90-days` (`tagState=any`, `olderThan=90d`) and
   `keep-last-30` (`keepCount=30`) policy JSON in a mode-`0600` file outside the
   repository. Apply it with:

   ```sh
   gcloud artifacts repositories set-cleanup-policies agent \
     --project=festive-ally-503605-v7 \
     --location=us-east4 \
     --policy=/absolute/private/path/agent-cleanup.json \
     --dry-run
   ```

3. Wait at least one day, inspect every dry-run `BatchDeleteVersions` candidate in the
   Artifact Registry Data Access logs, and stop if the current revision, the immediately
   previous ready revision, any explicitly retained rollback revision, or the production
   bootstrap digest appears.
4. Confirm the Terraform plan has exactly those policies, mutable tags, and
   `cleanup_policy_dry_run=false`. Only then apply the saved plan. The new empty preview
   repository can start with its active 14-day/20-version policy, but it must pass the
   same candidate review before any later retention change.
5. After apply, run `scripts/verify_ops_foundation.sh --live`; it fails if cleanup is in
   dry-run mode, policy names/scope/age/count drift, or either repository becomes
   cross-writable.

Artifact Registry cleanup runs periodically and policy changes take about a day. Deletion
is irreversible, while a keep policy takes precedence over deletion:
[Artifact Registry cleanup policies](https://cloud.google.com/artifact-registry/docs/repositories/cleanup-policy).
Changing either age or count is a separate reviewed infrastructure change. Before
reducing a boundary, inventory revision digests again and first repeat the dry run.

## Normal delivery

When the repository variable `AGENT_CLOUD_RUN_ENABLED=true`, `preview-agent.yml` handles
`opened`, `reopened`, and `synchronize` events from same-repository, non-Dependabot pull
requests and deploys to the fixed shared `agent-preview` service. Fork pull requests never
receive the deployment job. The secretless builder resolves the exact PR head before the
owner-approved release; there is no label trigger, per-PR service, PR URL comment, or
expiry automation. `deploy-agent.yml` deploys reviewed `main` pushes to `agent`.

The preview caller owns one global concurrency group for its shared service, with
`cancel-in-progress=false`; callers own the only delivery concurrency groups and the
reusable workflows declare no nested concurrency group.
After environment approval and before any GCP authentication, the release gate binds the
exact target/environment/mode tuple, source SHA, isolated-registry digest or rollback
revision, and fresh bounded smoke token. Preview requires the still-open same-repository
pull request to have the exact built head SHA. Production deploy requires `main` to equal
the checked-out SHA both before and after the exact `ci/check`, `protocol/compat`, and
`wiki/verify` GitHub Actions check-runs complete successfully. Duplicate names, another
GitHub App, pending/failure, a different check SHA, or a moved `main` fails closed.
Emergency rollback is deliberately different: it requires `workflow_dispatch`,
`refs/heads/main`, the current checked-out `main` SHA, environment approval, and an exact
production revision name, but it does not require green candidate checks. This keeps a
reviewed rollback usable when current `main` CI is red.

The caller composes two reusable workflows. `agent-image-build.yml`:

1. validates and authenticates the target's dedicated builder through WIF;
2. builds and pushes a fresh run/attempt-scoped tag with provenance and SBOM attestations,
   rejecting tag reuse as a delivery path;
3. emits only the registry-resolved digest.

It uses the root frozen uv workspace and the Dockerfile-specific context allowlist.
`ci/agent` also builds and inspects the real Linux amd64 delivery image, runs
`python -m agent.migrate` inside that exact image against the job's PostgreSQL 17 service,
boots the image against the same database with startup migration, Redis dispatch, and
background retries disabled, waits for `/live` and `/ready`, and requires an
unauthenticated AP v2 command to return 401. Cleanup always logs and removes the
container. This bounded PR smoke makes no provider or model request, so a lock,
workspace-member, context, corpus, architecture, migration, startup, or fail-closed
routing error fails before release without pretending to prove the deployed environment.

After owner approval, `agent-release.yml` passes that digest to
`scripts/deploy_cloud_run.sh`, which:

1. updates the same-digest migration job;
2. reads the exact Cloud Run v2 Job resource back, verifies its full runtime contract and
   `etag`, and only then calls REST v2 `jobs.run` with that same `etag`;
3. repeats update → v2 read-back verification → execution for the real-Neon grant/denial
   job and then the bounded guest-retention maintenance job;
4. polls each returned operation and accepts only one immutable successful Execution
   whose exact template matches the verified digest/job and whose failed, cancelled,
   running, and retried counts are zero;
5. creates a uniquely named no-traffic service revision from the commit SHA, GitHub run
   ID, and run attempt, then checks the exact digest, one-instance, one-worker, and
   numeric-secret contract through the Cloud Run v2 Service and Revision resources;
6. requires exactly one untagged 100% old revision plus one 0%-traffic `smoke` tag bound to
   the new revision, then runs health, unauthenticated-401, and the full owner-auth
   two-turn APv2 protocol smoke against that tagged URL;
7. only after every protocol gate passes, moves 100% traffic to the new revision, removes
   the tag, revalidates the exact serving revision, and performs health plus a cheap
   unauthenticated APv2 routing check without a second paid full smoke.

All metadata reads use `https://run.googleapis.com/v2/...` with a short-lived access token
kept out of arguments and logs. Redirects, non-JSON responses, unexpected status,
oversized bodies, v1-shaped or hybrid resources, incomplete reconciliation, and any
contract mismatch fail before job execution or traffic change.

A failure before a traffic-shift attempt removes the temporary tag and leaves the existing
100% target untouched. Once a shift has been attempted, every error, `TERM`, or `INT`
restores and verifies the previously serving revision. The workflow never rebuilds to
roll back. The temporary `smoke` revision tag is removed before every deploy or rollback,
removed again after checks, and verified absent. A tag-cleanup failure is itself a failed
delivery; required traffic restoration is still attempted and cleanup errors are not
swallowed.

## Guest execution quarantine

The maintenance job may recover a stale Redis-off guest run after its PostgreSQL fence
session disappears. That recovery creates an unresolved durable quarantine; neither the
15-minute scheduler interval nor the age of the row clears it. While unresolved:

- guest `run.start` on that exact owner/thread returns 409 before capacity, spend, or
  downstream scheduling;
- retention GC excludes the row from both its initial bounded candidate set and exact
  locked recheck;
- `input.respond` remains governed by its existing interrupt-state boundary, since a
  recovered thread is no longer interrupted.

Inspect counts first, without placing guest identities in logs:

```sql
SELECT
    count(*) AS unresolved_count,
    min(recovered_at) AS oldest_recovery,
    max(recovered_at) AS newest_recovery
FROM agent_guest_execution_quarantine
WHERE recovered_at IS NOT NULL AND drained_at IS NULL;
```

For an interactive investigation, select the exact `run_id`, `thread_id`, `identity`, and
timestamps only in an access-controlled console. A row with `drained_at` already present
is resolved even when the drain proof was written before recovery. Never delete the row,
set `drained_at`, or infer safety from `recovered_at` age alone.

The normal resolution is automatic: the surviving owner monitor cancels and awaits its
owner plus any pending database operation, then writes `drained_at` through a fresh
bounded connection. If the process hard-crashed before that proof, leave the quarantine
in place unless an operator can establish an equivalent external drain proof:

1. Disable anonymous traffic and replace or stop every Cloud Run revision that could have
   owned the execution. Confirm the old revision has zero active instances and requests.
2. Confirm no executor or finalizer from that revision remains and no matching checkpoint
   writer or database operation can still commit. If any part is uncertain, stop and
   retain the quarantine.
3. In one reviewed, audited transaction, update only the fully inspected exact key:

   ```sql
   UPDATE agent_guest_execution_quarantine
   SET drained_at = clock_timestamp()
   WHERE
       run_id = :exact_run_id
       AND thread_id = :exact_thread_id
       AND identity = :exact_identity
       AND recovered_at IS NOT NULL
       AND drained_at IS NULL
   RETURNING run_id, thread_id, recovered_at, drained_at;
   ```

4. Re-enable traffic only after the exact row is resolved. Let the ordinary maintenance
   job perform checkpoint-first deletion if the thread is also expired.

Do not mass-update quarantines. A hard-crash row that cannot be externally proven drained
is intentionally retained indefinitely; replacement identity issuance is safer than
guessing that an old writer is gone.

## Secret rotation

Rotate payloads without mutating a serving revision in place:

1. Set `AGENT_CLOUD_RUN_ENABLED=false` and record the exact untagged revision currently
   receiving 100% traffic. Stop unless exactly one such revision exists.
2. Add the new payload out of band and record its new positive numeric version ID. Do not
   disable or destroy the previous version yet.
3. Make a fresh `stage=services` plan with the current exact image, the complete version
   map, and only the intended numeric ID changed. Reject any secret payload, alias,
   unrelated service/job change, persistent replacement, or destroy.
4. Apply the saved plan. Immediately verify that the previously recorded revision still
   receives 100% traffic; if it does not, restore that exact revision before continuing.
5. Re-enable delivery and run the matching environment workflow. It updates and executes
   migration, grant probe, and maintenance in order, creates a unique no-traffic
   revision, smokes it, and only then promotes it.
6. Verify the new revision and live foundation contract. Retain the previous secret
   version through the rollback window; disabling it is a separate approved action.

The GitHub run ID and run attempt in the revision suffix make repeated same-commit
rotations and workflow re-runs collision-free. Rollback restores an exact old revision,
whose numeric secret references remain unchanged.

## Manual rollback

Dispatch **Deploy agent** on `main`, select `rollback`, and provide an exact existing
`agent-...` revision name. The `Agent Production` environment approval is still required.
The gate requires a manual `workflow_dispatch`, the checked-out SHA to remain current
`main`, and the exact revision input, but intentionally permits rollback while the three
deployment candidate checks are red.
Before shifting traffic, the workflow requires the target revision itself—not merely the
service's latest template—to be Ready and owned by `agent`, and to retain the exact
production runtime service account, production-repository digest,
max-instance/concurrency settings, one-worker command, and all five positive numeric
secret references. A revision from the wrong repository or service, an alias such as
`latest`, a different service account, or a non-ready revision fails before traffic
changes. The workflow then runs health/auth and the two-turn APv2 smoke, and restores the
previous revision automatically if that smoke fails.

Database migrations must remain compatible with one previous application revision.
Rollback changes traffic only; it does not reverse a Neon migration or secret version.
Restore a prior secret version only as a separately reviewed operation.

## External gates that remain

- Terraform has not been applied by this repository change.
- No GCP or Neon resource/payload has been created or changed.
- The real Neon runtime and migration credentials still need grant/denial acceptance.
- GitHub `Agent Preview` / `Agent Production` environments, their reviewer policy, zero
  variable inventory, and sole `AGENT_SMOKE_BEARER_TOKEN` secret still need external
  configuration and read-only live verification.
- The first provider-backed Korean two-turn APv2 smoke is still a live deployment gate.
- The real-Neon grant/denial result, provider-backed smoke, browser journey, and
  capability-policy evidence remain P2/P3 operational gates; the PostgreSQL 17 PR
  container smoke does not satisfy them.
- Anonymous visitor access remains a later reviewed production release after ADR-0006's
  isolation, concurrency, retention, and spend gates. An unreviewed preview build never
  becomes the public guest path.
