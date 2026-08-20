---
title: "Native Aegra Cloud Run delivery runbook"
description: >
  Bootstrap and deploy the digest-pinned native Aegra image through phase-scoped GitHub
  OIDC identities and Cloud Run revision traffic.
when_to_read: >
  Before applying the Cloud Run Terraform, enabling agent delivery, changing its
  workflows or image, rotating agent database credentials, or rolling back a revision.
tags: [operations, gcp, cloud-run, aegra, github-actions, neon, rollback]
status: stable
updated: "2026-08-15"
owners: ["@syshin0116"]
refs:
  - ../../infra/gcp/README.md
  - gcp-neon-foundation.md
  - ../ui-verification/reports/2026-08-14-public-subagents-model-selector.md
  - ../adr/0004-adopt-aegra.md
  - ../adr/0007-postgres-on-neon-split-projects.md
  - ../plans/rag-restack.md
template: spec
---

# Native Aegra Cloud Run delivery runbook

The web application remains on Vercel. This delivery surface owns the Production Aegra
service and four Production jobs. Preview registry, identities, and secret containers are
retained, but Preview has no Cloud Run service or job.

No delivery workflow creates a Neon project, adds a Secret Manager payload, changes a
GitHub environment, applies Terraform, or executes a Cloud Run job. Those are explicit
operator actions. Production is live as of 2026-08-15; the
[dated verification report](../ui-verification/reports/2026-08-14-public-subagents-model-selector.md)
records the exact source and Cloud Run revision observed that day.
The repository variable `AGENT_CLOUD_RUN_ENABLED` gates future GitHub delivery attempts
only. It does not pause Scheduler, remove a Cloud Run invoker, stop an existing service,
or otherwise act as a spend kill switch.

## Reviewed topology

| Service | Migration job | Runtime-grant job | Manual maintenance | Scheduled maintenance | Runtime identity | Migration identity |
|---|---|---|---|---|---|---|
| `agent` | `agent-migrate` | `agent-grants` | `agent-maintenance` | `agent-scheduled-maintenance` | `agent-runtime` | `agent-prod-migrator` |

| Environment | Repository | Builder | Retention floor |
|---|---|---|---|
| Agent Preview | `agent-preview` | `agent-preview-image-builder` | 14 days and the most recent 20 versions |
| Agent Production | `agent` | `agent-image-builder` | 90 days and the most recent 30 versions |

Terraform retains four physical repository resources: `agent` and `agent-preview` in the
active `asia-southeast1` region, plus the same two legacy names in `us-east4`. Only the
active regional pair is a delivery target; cleanup and direct IAM remain reviewed on all
four resources.

Each builder has `roles/artifactregistry.writer` only on its environment's active and
legacy repositories. Each deployer and the Google-managed Cloud Run service agent have
`roles/artifactregistry.reader` only on the same environment's two repositories; Cloud Run requires the
deploying principal to read selected image metadata, while only the service agent pulls
it at runtime. The Production deployer receives the project custom role
`cloudRunAgentDelivery` only on the service and the migration, grant-probe, and manual
maintenance jobs. That role contains exactly
`run.services.get`, `run.services.update`, `run.revisions.get`, `run.jobs.get`,
`run.jobs.update`, `run.jobs.run`, and `run.operations.get`. It intentionally excludes
create, delete, IAM-policy mutation, and `run.jobs.runWithOverrides`. A separate role lets
the Production deployer use only `run.jobs.get`, `run.jobs.update`, and
`run.operations.get` on the scheduled-maintenance job, without execution permission.
Preview delivery identities remain dormant. No deployer can read Secret Manager payloads
or write images, and preview code cannot write or select a production image.

The dedicated `agent-maintenance-scheduler` identity has no database secret and no
project-wide role. It receives `roles/run.invoker` only on
`agent-scheduled-maintenance`. The
production-only `agent-guest-maintenance` Cloud Scheduler job uses OAuth to call the
Cloud Run Jobs v2 `:run` API on a 15-minute schedule. Terraform creates the schedule only
at the `launch` stage; the normal delivery workflow does not update or execute it.
Production public access is live, but the first bounded Scheduler execution still needs
recorded operational evidence. The Google-managed Cloud Scheduler service agent must
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

The Production service intentionally allows unauthenticated Cloud Run invocation because
browsers at the Vercel site must reach it. Aegra's outer bearer-token middleware remains the
application authorization boundary: the delivery gate proves `/live` and `/ready` are
public while an unauthenticated APv2 `run.start` returns 401.

The Production service uses 1 GiB memory, `cpu_idle=true`, `startup_cpu_boost=true`, a 300-second
request timeout, `max_instances=1`, concurrency 8, and one Uvicorn worker. The instance
and worker limits are correctness constraints, not cost optimizations: Aegra 0.9.25's
same-thread mutation guard is process-local.

Each Production revision has exactly 16 reviewed plain values and three numeric-version
secret references for 19 total entries. The plain set includes
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
and receives no deployer identity. The approved Production release updates only the
Production service, although the scoped deployer role also covers the migration,
grant-probe, and manual-maintenance jobs. Preview has no service or job to update. The
deployer cannot write an image. This keeps the writer and deployer credentials on
different runners without falsely claiming that one GitHub environment can require two
independent approvals:
[GitHub deployment environments](https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments).

Both environments contain **zero GitHub environment variables and zero GitHub environment
secrets**. Identity and resource selection is repository-owned: immediately before OIDC
authentication,
`scripts/validate_agent_delivery_identity.sh` derives the canonical provider, exact
service account, repository, service, and jobs from the fixed `target` plus the
builder/deployer phase. A preview workflow therefore cannot substitute a production
identity or repository even if an in-repository pull request changes workflow code.
Do not store `AGENT_AUTH_SECRET`, a database URL, a bearer token, or a service-account JSON
key in GitHub. The current release smoke is intentionally unauthenticated and proves only
that APv2 rejects a missing credential with 401.

The canonical active WIF provider requires the exact caller workflow
(`preview-agent.yml` or `deploy-agent.yml`) and the exact called reusable workflow
(`agent-image-build.yml` for builders or `agent-release.yml` for deployers) at the same
reviewed ref. Preview additionally accepts only the `pull_request` event. Production
accepts only `push` or `workflow_dispatch` at `refs/heads/main`. Only deployer claims
carry and must match `Agent Preview` or `Agent Production`; a builder claim with an
environment is rejected.

## Secret Manager payloads

The foundation retains four dormant Preview runtime secret containers and five Production
runtime secret containers. Active delivery selects exactly four numeric Production
versions: auth, runtime database, migration database, and OpenAI. Only Production uses the exact
`openai:gpt-5.6-luna / 500000 / 53837` guest tuple and adds the numeric-version-pinned
`openai-api-key`. The run reservation combines the 21,837 µUSD worst generation
allocation from 8 calls at 768 output tokens per call and a 64,000-token generation
ceiling with the separate 128,000-token aggregate count-risk ledger priced at Luna's
highest input bucket (32,000 µUSD). This is not a documented count-endpoint price,
hidden-token bound, or provider hard cap, so billing and the account-level spend stop
remain open operational evidence. Preview owns no OpenAI credential and its Cloud Run
secret versions remain unset. The foundation retains these migration secret containers:

```text
agent-preview-migration-database-url
agent-migration-database-url
```

The Production service, grant-probe job, and maintenance jobs receive only the
least-privileged direct Neon runtime URL. The migration job receives only its elevated
direct migration URL. Neither URL
may contain a Neon `-pooler` hostname. Add values out of band as described in the
[foundation runbook](gcp-neon-foundation.md). Terraform never owns payloads or creates
versions, but it does own the reviewed **numeric version ID** selected by every service
and job. `latest`, `0`, and aliases are rejected. Cloud Run resolves a secret-backed
environment variable when an instance starts, so a mutable alias could silently change
after scale-to-zero without a new reviewed revision, smoke test, or reliable rollback.

Before a new environment or schema change, prove on real Neon that the runtime role can
perform Aegra's idempotent
checkpointer/store setup and DML but cannot create another schema, create a role, or hold
`rolsuper`, `rolcreaterole`, `rolcreatedb`, or `rolreplication`. The
`agent.neon_grant_probe` Cloud Run job makes that proof executable on every deployment.

## One-time bootstrap

This sequence is the Production bootstrap or full-rebuild procedure. Production has
already completed its initial launch. Preview Cloud Run resources are not part of this
sequence and require a separate reviewed restoration before Preview delivery can be enabled.

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

   The plan must create/import all four active/legacy registry resources, identities, WIF,
   IAM, state bucket, and eleven empty secret resources, with **zero** Cloud Run services
   or jobs. For the
   existing production registry, complete the cleanup-policy dry run below before
   approving its metadata change. Reject every persistent replacement/destroy and apply
   only the saved, owner-reviewed plan.

2. **Payloads and image.** Add only the four active Production secret versions out of
   band without printing payloads: agent auth, runtime database, migration database, and
   OpenAI. Record each positive numeric enabled version ID. Keep dormant Preview secret
   containers versionless. Build the reviewed commit for Linux amd64 into the Production
   repository and record the registry-resolved value:

   ```text
   asia-southeast1-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:<64 lowercase hex>
   ```

   A tag is not accepted.

3. **Jobs.** Put the five non-secret Production version IDs in a mode-`0600` variable
   file outside the repository as `agent_secret_versions = { ... }`. Plan and apply with
   the reviewed Production digest and a null Preview image:

   ```sh
   terraform -chdir=infra/gcp plan \
     -var 'agent_delivery_stage=jobs' \
     -var 'agent_bootstrap_image=asia-southeast1-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:REPLACE' \
     -var 'agent_preview_bootstrap_image=null' \
     -var-file=/absolute/private/path/agent-secret-versions.tfvars
   ```

   This plan must add exactly four Production jobs: `agent-migrate`, `agent-grants`,
   `agent-maintenance`, and `agent-scheduled-maintenance`. It must contain zero services
   and zero Scheduler resources. Apply the saved reviewed plan, then run only the first
   three jobs with `--wait`. Do not run `agent-scheduled-maintenance` manually.

4. **Services.** Re-plan with `agent_delivery_stage=services`, the same Production digest,
   null Preview image, and the same external four-key version file. The only additions are
   the Production service and its resource IAM. The plan must still contain no Scheduler
   or Scheduler invoker. Apply only after the three manual jobs pass, then release the
   reviewed digest through the native no-traffic smoke and 100% promotion flow.

5. **Launch.** After the serving release is green, re-plan with
   `agent_delivery_stage=launch` and the same image and version inputs. The delta from
   `services` must be exactly the `agent-guest-maintenance` Scheduler and its job-scoped
   invoker binding on `agent-scheduled-maintenance`. Apply the saved plan, then select the
   reviewed local account and require the exact-project direct-state plus canonical
   GitHub governance gate to pass:

   ```sh
   export OPS_FOUNDATION_GCLOUD_ACCOUNT='<reviewed local account>'
   scripts/verify_ops_foundation.sh --live
   ```

   The gate permits only fixed reads against `festive-ally-503605-v7`; it does not read
   secret payloads or Terraform state contents, execute workloads, mutate resources,
   follow or query organization/folder/ancestor/project-parent scopes, or query another
   project. It ignores any parent field returned by the exact project describe. The
   optional unsigned v1 structure check is not a prerequisite and never authenticates
   company-admin origin or inherited-policy completeness. See
   [the foundation runbook](gcp-neon-foundation.md#evidence-and-target-state).

   Require the first bounded scheduled execution to succeed. A pass does not settle Luna
   input-count billing, prove a pre-provider upper bound, or prove bounded or zero spend.
   Production is already public, so a failed recheck is an incident signal and should
   follow the emergency-close procedure.
   A missing API or permission denial is a hard stop and does not authorize an IAM grant,
   API enablement, billing attachment, project-setting change, or job execution.

After bootstrap, every Terraform plan must explicitly retain `stage=launch`, the current
Production digest, a null Preview image, and the complete four-key Production numeric
version map. A `services` plan after launch proposes removal of the protected Scheduler
and fails closed. Never use `-target`; each stage is a complete, repeatable root-module
plan.

Only the retired Preview OpenAI Secret Manager object remains removed from Terraform
state with `destroy = false`. Production restores `openai-api-key` through the existing
import set. This repository does not delete the Preview object's external payloads or
versions; delete it only as a separately approved GCP cleanup after confirming no
consumer remains.

Terraform ignores subsequent image and traffic drift because the delivery workflow owns
those revision fields. Every other service/job field—including the selected numeric
secret versions—remains Terraform-owned and drift-visible.

## Registry cleanup and rollback support

Artifact Registry cannot delete tagged versions while immutable tags are enabled, so all
four repository resources intentionally set `immutable_tags = false`. This does not make a mutable tag
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

Before the first apply that changes any existing repository resource, test the exact
Production and Preview policies as dry runs in both regions:

1. Enable Artifact Registry `DATA_WRITE` audit logs, inventory every current and
   zero-traffic Production revision plus any explicitly retained Preview or legacy
   digest, and save that non-secret inventory with the plan review.
2. Put the exact Production `delete-after-90-days`/`keep-last-30` policy and Preview
   `delete-after-14-days`/`keep-last-20` policy in separate mode-`0600` files outside the
   repository. Apply each as a dry run to its matching active and legacy repository:

   ```sh
   for registry_region in asia-southeast1 us-east4; do
     gcloud artifacts repositories set-cleanup-policies agent \
       --project=festive-ally-503605-v7 \
       --location="$registry_region" \
       --policy=/absolute/private/path/agent-cleanup.json \
       --dry-run
     gcloud artifacts repositories set-cleanup-policies agent-preview \
       --project=festive-ally-503605-v7 \
       --location="$registry_region" \
       --policy=/absolute/private/path/agent-preview-cleanup.json \
       --dry-run
   done
   ```

3. Wait at least one day, inspect every dry-run `BatchDeleteVersions` candidate from all
   four repositories in the Artifact Registry Data Access logs, and stop if the current
   revision, the immediately previous ready revision, any explicitly retained digest, or
   the Production bootstrap digest appears.
4. Confirm the Terraform plan has exactly those policies, mutable tags, and
   `cleanup_policy_dry_run=false` on all four repository resources. Only then apply the
   saved plan.
5. Require `--live` to confirm the exact repository policy, cleanup scope/age/count,
   direct IAM, and cross-write state after apply. That metadata check does not inspect
   dry-run deletion candidates or make deletion recoverable, so it never replaces steps
   1–4 and cannot by itself authorize cleanup activation or public delivery.

Artifact Registry cleanup runs periodically and policy changes take about a day. Deletion
is irreversible, while a keep policy takes precedence over deletion:
[Artifact Registry cleanup policies](https://cloud.google.com/artifact-registry/docs/repositories/cleanup-policy).
Changing either age or count is a separate reviewed infrastructure change. Before
reducing a boundary, inventory revision digests again and first repeat the dry run.

## Cost guard and incident containment

Jobs-stage bootstrap creates no Scheduler, so unattended maintenance cannot begin during
that stage. The owner-approved launch-stage contract creates the Production Scheduler
active. Review the exact project-scoped plan before apply, then verify its first bounded
execution. Production public access is already live, but that does not prove Scheduler
execution or cost containment. The schedule does not make the stack free: Cloud Run jobs,
requests, Artifact Registry, Secret Manager, logging,
Terraform state storage, Neon, and model calls can still incur usage or charges. Confirm
billing and resource telemetry in the exact dedicated project rather than inferring zero
cost from low traffic or free-trial credit. Do not introduce a runtime flag or
console-only toggle that can drift from Terraform and silently change recurrence.

For a spend or exposure incident, preserve this exact order:

1. Set `AGENT_CLOUD_RUN_ENABLED=false` to prevent new automated deliveries. Treat this
   only as delivery containment, not as a kill switch, and freeze every ordinary
   Terraform apply until the incident configuration change below is reviewed and applied.
2. Close guest issuance and anonymous agent access with the
   [public-chat emergency-close procedure](public-anonymous-chat.md#emergency-close).
   For active spend or exposure, use the separately approved incident action scoped to
   the exact project and service to remove the public `allUsers` invoker and stop the
   affected Cloud Run service immediately; do not wait for Scheduler containment first.
3. Pause `agent-guest-maintenance` and verify the paused state in
   `festive-ally-503605-v7`; if live state had been activated, reconcile the
   repository-owned Terraform state in the separately reviewed incident change.
4. Land and apply the same reviewed repository/configuration change that makes the
   emergency public-IAM and service state the Terraform desired state. Keep ordinary
   applies and delivery disabled until that exact change is active; otherwise the next
   `launch` apply can recreate `allUsers` exposure or restart the service. Do not reuse
   the company account's current default project as the target.

Record the exact service, scheduler, project, and observed in-flight work before and after
each action. Existing executions and non-compute resources can outlive these controls, so
verify termination and billing telemetry; never report zero cost solely because this
sequence completed.

## Normal delivery

When the repository variable `AGENT_CLOUD_RUN_ENABLED=true`, `deploy-agent.yml` handles
matching `main` pushes and manual dispatches for Production.

`preview-agent.yml` is dormant. It requires both `AGENT_CLOUD_RUN_ENABLED=true` and
`AGENT_CLOUD_RUN_PREVIEW_ENABLED=true`, but Terraform currently creates no Preview Cloud
Run service or job and requires `agent_preview_bootstrap_image=null`. Do not enable the
Preview flag until those resources and their delivery contract are restored in a reviewed
change. The current Preview release path does not recheck the pull-request head or
required CI after environment approval, so that gap must be closed as part of restoration.
Production and Preview callers have separate global concurrency groups, with
`cancel-in-progress=false`; the reusable workflows have no nested concurrency group.

`agent-image-build.yml` authenticates the target's dedicated builder through WIF, builds
the exact source SHA for Linux amd64, and pushes a fresh run-attempt tag with
`--provenance=false` and `--sbom=false`. It resolves that push to an immutable digest and
passes only the digest to the release workflow.

After owner approval on `Agent Production`, `agent-release.yml` starts the Production
release job. It first requires the source SHA to remain the current `main` commit
and requires the exact `ci/check`, `protocol/compat`, and `wiki/verify` check runs to pass.
It then authenticates the dedicated deployer through WIF and:

1. deploys the digest to a no-traffic revision with the temporary `smoke` tag;
2. verifies the deployed revision uses the requested digest;
3. requires `/live` and `/ready` to pass and an unauthenticated APv2 command to return 401;
4. removes the smoke tag and sends 100% traffic to the new revision.

The release does not update or execute migration, grant-probe, or maintenance jobs. It
does not run an authenticated or provider-backed two-turn smoke, generate SBOM or
provenance attestations, or automate rollback. Before promotion, its exit trap attempts to
remove the smoke tag and leaves existing production traffic unchanged. After traffic
promotion starts, repository automation does not restore the previous revision.

CI separately builds the Linux amd64 delivery image, runs the migration against its
PostgreSQL 17 service, starts the container, checks `/live` and `/ready`, and requires an
unauthenticated APv2 command to return 401. That check makes no provider request and does
not prove the deployed Neon, model, Scheduler, or signed-in path.

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

The normal resolution is automatic: after the owner task is terminal, the surviving
monitor cancels and awaits any pending database operation, commits `drained_at` through a
fresh bounded connection, and only then releases its fence. On an abnormal monitor path,
it first cancels and awaits both owner and pending operation, then commits the same proof
before releasing a surviving fence. If the process hard-crashed before that proof, leave
the quarantine in place unless an operator can establish an equivalent external drain
proof:

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
3. Make a fresh `stage=launch` plan with the current exact Production image, a null Preview
   image, the complete four-key Production version map, and only the intended numeric ID
   changed. Reject any secret payload, alias,
   unrelated service/job change, persistent replacement, or destroy.
4. Apply the saved plan. Immediately verify that the previously recorded revision still
   receives 100% traffic; if it does not, restore that exact revision before continuing.
5. Re-enable delivery and run the Production workflow. It builds the exact
   source, creates a no-traffic revision, runs the unauthenticated smoke, and then promotes
   it. Run migration, grant-probe, or maintenance jobs separately when the rotated payload
   requires them; the delivery workflow does not execute those jobs.
6. Verify the new revision and live foundation contract. Retain the previous secret
   version through the rollback window; disabling it is a separate approved action.

Rollback restores an exact old revision whose numeric secret references remain unchanged.

## Manual rollback

There is no rollback input or automated rollback path in the current GitHub workflows.
Rollback is a separately approved operator action:

1. Identify the exact previously Ready revision and confirm its image digest, runtime
   identity, numeric secret versions, and guest tuple belong to the Production service.
2. Record the currently serving revision, obtain separate owner approval, and reassign
   100% traffic to the reviewed target revision with a project-scoped Cloud Run command.
3. Verify `/live`, `/ready`, the unauthenticated APv2 401 boundary, and the required
   signed-in or provider behavior manually.
4. If verification fails, reassign traffic to the recorded original revision and close
   public guest issuance if safe restoration cannot be proved.

Repository automation does not validate the rollback target, run its smoke, or restore
traffic after a failed manual change. Do not describe a manual traffic reassignment as a
GitHub release result.

Database migrations must remain compatible with one previous application revision.
Rollback changes traffic only; it does not reverse a Neon migration or secret version.
Restore a prior secret version only as a separately reviewed operation.

## Production status and remaining evidence

Production is live at `agent-00030-jex` from `main`
`2a5c8ef0629670dc792b6baf2b928f1d0894a7c7`. The native release path proves the image
digest, `/live`, `/ready`, the unauthenticated APv2 401 boundary, and promotion to 100%
traffic. Both Agent GitHub environments have zero variables and zero secrets.

The following evidence remains outside the current release workflow:

- authenticated and provider-backed Korean two-turn APv2 behavior;
- real-Neon migration and least-privileged grant and denial results;
- migration, grant-probe, and maintenance job execution for the deployed digest;
- the first bounded production Scheduler execution and ongoing retention evidence;
- billing telemetry, a hard provider spend stop, and Luna input-count behavior for
  accepted, rejected, and oversized requests;
- a reviewed manual rollback rehearsal and recovery proof.

Public anonymous access is live in Production and closed in Preview. That observed access
does not satisfy the remaining cost, Scheduler, retention, or recovery evidence.
