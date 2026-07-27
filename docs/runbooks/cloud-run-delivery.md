---
title: "Native Aegra Cloud Run delivery runbook"
description: >
  Bootstrap, deploy, smoke, and roll back the digest-pinned native Aegra image through
  GitHub OIDC, environment-scoped identities, and Cloud Run revision traffic.
when_to_read: >
  Before applying the Cloud Run Terraform, enabling agent delivery, changing its
  workflows or image, rotating agent database credentials, or rolling back a revision.
tags: [operations, gcp, cloud-run, aegra, github-actions, neon, rollback]
status: stable
updated: "2026-07-28"
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

| Environment | Service | Migration job | Runtime-grant job | Runtime identity | Migration identity |
|---|---|---|---|---|---|
| Agent Preview | `agent-preview` | `agent-preview-migrate` | `agent-preview-grants` | `agent-preview-runtime` | `agent-preview-migrator` |
| Agent Production | `agent` | `agent-migrate` | `agent-grants` | `agent-runtime` | `agent-prod-migrator` |

| Environment | Repository | Builder | Retention floor |
|---|---|---|---|
| Agent Preview | `agent-preview` | `agent-preview-image-builder` | 14 days and the most recent 20 versions |
| Agent Production | `agent` | `agent-image-builder` | 90 days and the most recent 30 versions |

Each builder has repository-scoped `roles/artifactregistry.writer` only on its matching
repository. Each deployer and the Google-managed Cloud Run service agent have
`roles/artifactregistry.reader` only on the matching repository; Cloud Run requires the
deploying principal to read selected image metadata, while only the service agent pulls
it at runtime. Each deployer has `roles/run.developer` only on its own service and two
jobs, plus `actAs` only on that environment's runtime and migration identities. No
deployer can read Secret Manager payloads or write images, and preview code cannot write
or select a production image.

The services intentionally allow unauthenticated Cloud Run invocation because browsers at
the Vercel site must reach them. Aegra's outer bearer-token middleware remains the
application authorization boundary: the delivery gate proves `/live` and `/ready` are
public while an unauthenticated APv2 `run.start` returns 401.

Both services are fixed to one instance and one Uvicorn worker. This is a correctness
constraint, not a cost optimization: Aegra 0.9.24's same-thread mutation guard is
process-local.

## GitHub configuration

Create two GitHub deployment environments in addition to the existing Vercel `Preview`
and `Production` environments:

| Environment | Branch policy | Reviewer |
|---|---|---|
| `Agent Preview` | no branch restriction | none |
| `Agent Production` | branch `main` only | `syshin0116`, self-review allowed |

Normal production delivery deliberately pauses twice. The first approval releases the
builder job; after it succeeds, inspect the exact candidate digest and build evidence.
The second approval releases the separate deployer job to run migrations, smoke, and
traffic promotion. GitHub applies environment protection rules to each job that
references an environment, so these are two independent approvals, not one approval
shared by the run. This keeps the registry-writer credential on a different runner from
the deployer credential and smoke token. Production manual rollback has only the rollback
job and therefore one approval; preview has no required reviewer. Do not collapse the two
production jobs merely to remove a click without a new review of credential co-residency:
[GitHub deployment environments](https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments).

Set these environment variables with the exact Terraform outputs:

```text
GCP_WORKLOAD_IDENTITY_PROVIDER
GCP_BUILDER_SERVICE_ACCOUNT
GCP_DEPLOYER_SERVICE_ACCOUNT
```

All three values are environment-specific. The reusable workflow validates the exact
reviewed provider, builder, deployer, and repository mapping immediately before each OIDC
authentication. A preview workflow therefore cannot substitute a production identity or
repository even if an in-repository pull request changes workflow code.

Set this GitHub **Environment secret** (not a repository or organization secret) in both
`Agent Preview` and `Agent Production`:

```text
AGENT_SMOKE_BEARER_TOKEN
```

It must be a short-lived owner bearer token accepted by `agent.auth`; it is never printed.
Rotate or replace it before expiry. Do not store `AGENT_AUTH_SECRET`, a database URL, or a
service-account JSON key in GitHub.

The WIF providers require the exact caller workflow (`preview-agent.yml` or
`deploy-agent.yml`) and the exact called reusable workflow (`agent-delivery.yml`) at the
same ref. Preview additionally accepts only the `pull_request` event. Production accepts
only `push` or explicitly approved `workflow_dispatch` at `refs/heads/main`.

## Secret Manager payloads

The foundation's five runtime secrets per environment remain unchanged. Add one separate
migration URL secret per environment:

```text
agent-preview-migration-database-url
agent-migration-database-url
```

Runtime services and the grant-probe jobs receive only the least-privileged direct Neon
runtime URL. Migration jobs receive only their elevated direct migration URL. Neither URL
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
   twelve empty secret resources, with **zero** Cloud Run services or jobs. For the
   existing production registry, complete the cleanup-policy dry run below before
   approving its metadata change. Reject every persistent replacement/destroy and apply
   only the saved, owner-reviewed plan.

2. **Payloads and images.** Add all twelve first secret versions out of band without
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

3. **Jobs.** Put the twelve non-secret version IDs in a mode-`0600` variable file outside
   the repository as `agent_secret_versions = { ... }`. Plan and apply with both reviewed
   digests:

   ```sh
   terraform -chdir=infra/gcp plan \
     -var 'agent_delivery_stage=jobs' \
     -var 'agent_bootstrap_image=us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:REPLACE' \
     -var 'agent_preview_bootstrap_image=us-east4-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent@sha256:REPLACE' \
     -var-file=/absolute/private/path/agent-secret-versions.tfvars
   ```

   This plan must add exactly the two migration jobs, two grant-probe jobs, and their
   resource IAM; it must still contain zero services. Apply the saved reviewed plan, then
   execute each environment's migration followed by its grant probe with `--wait`.
   Require each pair of jobs to use its environment's reviewed digest and pinned numeric
   secret versions.

4. **Services.** Re-plan with `agent_delivery_stage=services`, the same two digests, and
   the same external version file. The only delivery-surface additions are the two
   services and their resource IAM. Apply only after both environments' migration and
   grant probe passed. Run `scripts/verify_ops_foundation.sh --live`, configure and verify
   both GitHub environments, then set `AGENT_CLOUD_RUN_ENABLED=true` and immediately run
   the first reviewed preview and production deliveries. If either fails, set the
   variable back to `false` while investigating.

After bootstrap, every Terraform plan must explicitly retain `stage=services`, both
current exact digests, and the complete twelve-key numeric version map. Omitting them
proposes protected resource removal and fails closed. Never “simplify” an apply with
`-target`; each stage is a complete, repeatable root-module plan.

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

`preview-agent.yml` deploys in-repository, non-Dependabot pull requests to
`agent-preview`. Fork pull requests never receive the deployment job. `deploy-agent.yml`
deploys reviewed `main` pushes to `agent`.

The reusable workflow:

1. validates and authenticates the environment's dedicated builder through WIF;
2. builds and pushes a fresh run/attempt-scoped tag with provenance and SBOM attestations,
   rejecting tag reuse as a delivery path;
3. passes only the registry-resolved digest to the deployer;
4. updates and executes the same-digest migration job;
5. updates and executes the same-digest real-Neon grant/denial job;
6. creates a uniquely named no-traffic service revision from the commit SHA, GitHub run
   ID, and run attempt, then checks the exact digest, one-instance, one-worker, and
   numeric-secret contract;
7. health-checks the tagged no-traffic revision and proves APv2 rejects missing auth;
8. moves 100% traffic to that revision;
9. runs the two-turn APv2 protocol smoke against the service URL.

Any failure after revision creation restores 100% traffic to the previously ready
revision. The workflow never rebuilds to roll back. The temporary `smoke` revision tag is
removed before every deploy or rollback, removed again after checks, and verified absent.
A tag-cleanup failure is itself a failed delivery; traffic restoration is still attempted
and cleanup errors are not swallowed.

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
   migration then grant probe, creates a unique no-traffic revision, smokes it, and only
   then promotes it.
6. Verify the new revision and live foundation contract. Retain the previous secret
   version through the rollback window; disabling it is a separate approved action.

The GitHub run ID and run attempt in the revision suffix make repeated same-commit
rotations and workflow re-runs collision-free. Rollback restores an exact old revision,
whose numeric secret references remain unchanged.

## Manual rollback

Dispatch **Deploy agent** on `main`, select `rollback`, and provide an exact existing
`agent-...` revision name. The `Agent Production` environment approval is still required.
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
- GitHub `Agent Preview` / `Agent Production` environments, their variables, reviewer
  policy, and smoke tokens still need external configuration.
- The first provider-backed Korean two-turn APv2 smoke is still a live deployment gate.
