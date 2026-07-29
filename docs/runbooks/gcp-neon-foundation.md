---
title: "GCP and Neon foundation runbook"
description: >
  Inventory, state recovery, secret injection, cutover, verification, and rollback
  procedures for the keyless GCP deployment foundation and split Neon projects.
when_to_read: >
  Before changing GCP IAM or Workload Identity Federation, recovering Terraform state,
  injecting runtime secrets, connecting Vercel or Cloud Run to Neon, or deleting the
  Singapore database.
tags: [operations, gcp, neon, workload-identity, cloud-run, secrets, terraform]
status: stable
updated: "2026-07-29"
owners: ["@syshin0116"]
refs:
  - ../../infra/gcp/README.md
  - cloud-run-delivery.md
  - ../adr/0006-public-anonymous-chat-access.md
  - ../adr/0007-postgres-on-neon-split-projects.md
  - ../plans/rag-restack.md
template: spec
---

# GCP and Neon foundation runbook

## Evidence and target state

### GCP snapshot verified on 2026-07-27

- project: `festive-ally-503605-v7` (`syshin0116-prod`);
- project number: `72919926064`;
- region: `us-east4`;
- Artifact Registry repository: `agent`;
- service accounts: production runtime `agent-runtime`, preview deployer
  `agent-preview-deployer`, and production deployer `agent-prod-deployer`;
- Workload Identity pool: `github`, with `github-preview` and `github-production`
  providers;
- Cloud Run services: **zero**;
- secret resources: the five production names below, each with zero enabled versions.

That snapshot also found mutable Artifact Registry tags and both deployers holding
project-wide `roles/run.admin`, repository writer, and access to the same production
runtime. Those are the pre-hardening facts, not the accepted target.

After this foundation is reviewed and applied, the target is:

- isolated `agent` and `agent-preview` repositories with never-reused delivery tags,
  digest-only deployment, and bounded cleanup retention;
- distinct preview/production builder, runtime, migrator, and deployer identities;
- the managed direct act-as role on each runtime containing only its matching deployer,
  with known project- and resource-level bypasses rejected by the live verifier;
- no project-wide Cloud Run role and no image-writer role on either deployer;
- five disjoint empty Secret Manager resources per environment, each with one managed
  direct `secretAccessor` member for the matching runtime;
- a separate migration-only database secret per environment, readable only by its
  migrator;
- one canonical active `github-production` federation provider that explicitly maps the
  numeric repository and owner IDs, restricts its condition to those mapped IDs and an
  allowed mapped delivery role, and maps exact caller/reusable-workflow claims onto the
  disjoint `preview-builder`, `preview-deployer`, `production-builder`, and
  `production-deployer` roles;
- preview federation accepts only `pull_request` and the exact preview caller; its builder
  has no environment claim, while its deployer must carry `Agent Preview`;
- production federation accepts only `push` or `workflow_dispatch` at
  `refs/heads/main` and the exact production caller; its builder has no environment
  claim, while its deployer must carry `Agent Production`;
- the legacy `github-preview` provider retained Terraform-managed but disabled, inert,
  unable to map a delivery role, and protected from destruction during staged retirement;
- evaluation publication isolated in a separate `Evaluation Publication` environment
  that the active provider condition excludes, while the disabled legacy provider accepts
  no caller at all, and that carries no GCP or deployment secrets;
- each Artifact Registry repository writable only by its matching builder and readable
  only by its matching deployer plus the Google-managed Cloud Run service agent;
- the exact seven-permission `cloudRunAgentDelivery` custom role bound only to each
  matching deployer's Service and Jobs, with no delete, create, IAM-policy mutation, or
  job-override permission;
- a dedicated keyless scheduler identity with `roles/run.invoker` only on production
  maintenance, and no database-secret access or project-wide role;
- no user-managed service-account keys.

Live acceptance is intentionally unavailable. `--live` first validates an unsigned v1
structure file and then exits nonzero with
`BLOCKED: trusted company-admin attestation is not configured`. The verifier contains no
GCP CLI helper, command catalogue, account digest, or Google request path. Unsigned v1 is
never deployment approval, company-admin evidence, or proof of the project's parent. A
separately reviewed signed v2 format and a repository-pinned company-admin public key
must land before live acceptance or any live read can exist.

Invoke this verifier only through its executable path, for example
`scripts/verify_ops_foundation.sh --static`. Its `/bin/bash -p` process ignores
`BASH_ENV` and imported shell functions. Sourcing it or running
`bash scripts/verify_ops_foundation.sh ...` is unsupported and refused; sourcing has no
test or environment override. Future signed-v2 work must introduce its trust and
exact-project read contract from scratch in a separate review; there is no dormant
execution path to enable.

`OPS_FOUNDATION_ADMIN_EVIDENCE_FILE` names only an unsigned structure input. Its absolute
path must remain outside every repository/worktree and point to a regular non-symlink
file owned by the current user, readable only by that owner (`0400` or `0600`; no
execute, group, or other bits). The file is valid for at most 24 hours, permits no future
timestamp or duplicate JSON key, and binds the schema version plus exact target project
ID and number. V1 accepts exactly one declared organization record; it does not assert or
verify a folder chain or project-parent linkage.

The structure validator requires every binding in that declared organization record to
have an exact reviewed `scope` + `role` + `member` record and a declared per-role
permission array whose role keys exactly match the policy. It rejects public, group,
domain, federated `principal`/`principalSet`, deleted, direct
workload-service-account, dangerous or unclassified permission-verb, and
project-custom-role bindings even if listed as reviewed. These checks detect unsafe or
internally inconsistent input; they do not authenticate who produced it or prove that
it is complete company policy.

Terraform uses additive IAM member resources so an unreviewed apply cannot erase unrelated
or Google-managed members. Static verification proves the repository-owned Terraform
shape, not live or inherited IAM. Direct roles on the nine workload identities,
encompassing Resource Manager principal sets, project-wide impersonation or secret
access, extra managed-resource members, user-managed keys, and repository cross-write
remain live acceptance risks until signed-v2 verification is implemented.

Unsigned v1 is a structure-only precursor, not a waiver of inherited-IAM risk. This
repository must not collect policy by traversing the company hierarchy. Until a trusted
company-admin signature authenticates complete project-bound inherited-IAM input,
deployment verification remains blocked.

The agent delivery workflows bind both the caller `workflow_ref` and reusable
`job_workflow_ref` inside the mapped `delivery_role`; the provider condition itself
references only mapped attributes. Image builders use `agent-image-build.yml` without a
GitHub environment; deployers use `agent-release.yml` with the exact `Agent Preview` or
`Agent Production` environment. Evaluation publication uses `Evaluation Publication`,
and Vercel retains `Preview` and `Production`. Reviewers, self-review settings, and
deployment branches for all five, plus exact secret/variable inventories for Evaluation
Publication and the two agent environments, are governed only by
`.github/repository-governance.json` and
`scripts/verify_repository_governance.py`; this foundation does not duplicate that policy.
Repository governance can be verified separately with
`scripts/verify_ops_foundation.sh --governance-live`; blocked foundation `--live` does
not reach that delegation. The
canonical `Agent Production`, `Evaluation Publication`, and Vercel `Production`
deployment-branch set is `{main}`. `Evaluation Publication` must use `syshin0116` as its
required reviewer, allow the solo owner to review, forbid admin bypass, and contain no
environment secrets or variables. It must never be added to the GCP WIF provider
conditions.

Both agent environments require reviewer `syshin0116`, allow the solo owner to review,
forbid admin bypass, and contain exactly one environment secret,
`AGENT_SMOKE_BEARER_TOKEN`, plus zero environment variables. The unreviewed build phase
can write only to its target's isolated registry; migrations, runtime secrets, smoke, and
traffic remain behind the one release approval.
Immediately before each approval, replace that secret with a newly minted owner JWT whose
total lifetime is at most two hours and whose remaining lifetime is at least 65 minutes.
The release gate checks those public claims before GCP authentication; the authenticated
APv2 smoke proves the signature. Automatic per-release minting is not implemented, so
this rotation is a required external gate and a long-lived static token is forbidden.

As of 2026-07-28, the live repository has the `Evaluation Publication` environment with
required reviewer `syshin0116`, `prevent_self_review=false`, admin bypass disabled, and one
custom deployment branch policy for `main`. The frozen live verifier below passes,
including its fail-closed zero-count checks for environment secrets and variables; an
independent direct GitHub API check also confirmed both inventories are empty. The manual
publication workflow has not been dispatched, and no evaluation result is claimed as
published gold.
Delegation requires both `uv` and `gh` and runs the verifier exactly as:

```sh
uv run --frozen --package syshin0116-dev-agent \
  python scripts/verify_repository_governance.py --live
```

### Neon: verified repository state versus target

No Neon API credential was available during the 2026-07-27 audit. Project existence,
branch names, regions, quotas, and endpoint values therefore remain unverified external
state and must not be presented as live inventory.

What is verified in this repository is the authentication architecture:

- `web/` uses Auth.js v5 (`next-auth` v5 beta);
- `@auth/pg-adapter` stores Auth.js tables in Postgres through `DATABASE_URL`;
- GitHub and Google remain the OAuth providers;
- Neon supplies Postgres only. **Neon Auth is not being adopted.**

The accepted target from
[ADR-0007](../adr/0007-postgres-on-neon-split-projects.md) is:

| Purpose | Target project | Target region | Target branch | Status |
|---|---|---|---|---|
| Auth.js production | `syshin0116-web-prod` | `aws-us-east-1` | `production` | Unverified; create or confirm before cutover |
| Auth.js preview | `syshin0116-web-prod` | `aws-us-east-1` | isolated preview branch | Unverified; create with separate credentials |
| Aegra production | `syshin0116-agent-prod` | `aws-us-east-1` | `production` | Unverified; create or confirm before cutover |
| Aegra preview | `syshin0116-agent-prod` | `aws-us-east-1` | isolated preview branch | Unverified; create with separate credentials |
| Rollback source | `syshin0116-dev` | `aws-ap-southeast-1` | `main` | Last recorded in ADR-0007; re-verify before relying on it |

Web and agent use different projects, credentials, and failure domains. Application
runtimes use branch-scoped, least-privileged Neon direct endpoints. Schema or migration
commands use separately held elevated direct credentials; never expose a migration
credential to Vercel or Cloud Run runtime configuration. Transaction-mode `-pooler`
endpoints remain prohibited by ADR-0007 until a separately reviewed compatibility change
amends that decision.

## Terraform state

The foundation state lives at:

```text
gs://festive-ally-503605-v7-tfstate/syshin0116.dev/gcp/foundation/default.tfstate
```

The bucket enforces uniform access and public-access prevention, keeps object versions,
retains soft-deleted objects for 30 days, and has `force_destroy = false` plus Terraform
`prevent_destroy`. The GCS backend provides state locking. A restricted pre-migration
recovery backup is retained outside the repository. Terraform also left a gitignored
worktree-local migration backup; preserve it for now, but do not treat a disposable
worktree as durable backup storage. Remove it only in a separately approved, exact-target
cleanup after the external mode-`0600` backup has been independently verified. Never move
either copy into a tracked path or CI.

Routine operator flow:

```sh
scripts/verify_ops_foundation.sh --static
terraform -chdir=infra/gcp init
terraform -chdir=infra/gcp plan \
  -var 'agent_delivery_stage=services' \
  -var 'agent_bootstrap_image=REVIEWED_PRODUCTION_REGISTRY_DIGEST' \
  -var 'agent_preview_bootstrap_image=REVIEWED_PREVIEW_REGISTRY_DIGEST' \
  -var-file=/absolute/private/path/agent-secret-versions.tfvars
```

Use Terraform `1.13.5`; `required_version` and `infra/gcp/.terraform-version` pin the same
exact release. A fresh remote plan is mandatory before every apply. Review the full plan,
including imports and IAM removals, and stop on any persistent-resource replacement or
destroy. The mock plan in CI is not evidence of live safety and cannot substitute for
this review. During first-time setup, use the explicit `foundation → jobs → services`
sequence in the [Cloud Run delivery runbook](cloud-run-delivery.md), never `-target`.

CI deliberately uses `terraform init -backend=false` and mock-provider tests. It never
receives GCP credentials and cannot read or modify remote state.

### State recovery

Treat recovery as a separately approved maintenance event:

1. stop every Terraform writer and confirm no lock owner is active;
2. record the current object generation and checksum without printing state contents;
3. list GCS object generations and select the last known-good generation;
4. copy that generation into a new mode-`0600` file under a fresh mode-`0700` temporary
   directory;
5. verify its Terraform lineage, serial, and parseability locally without logging values;
6. take one more restricted copy of the current remote generation;
7. with explicit owner approval, restore the selected generation as a new current GCS
   generation; never delete historical generations and never use
   `terraform state push -force`;
8. run `terraform plan -refresh-only`, review every drift item, then run a normal plan.

If lineage or serial does not match expectations, stop. Do not “repair” it by editing the
JSON state file.

## Secret resources

Production resource names:

- `agent-database-url`;
- `agent-auth-secret`;
- `anthropic-api-key`;
- `langsmith-api-key`.

Preview resource names use the same suffixes with the `agent-preview-` prefix. Terraform
manages resource metadata and required additive runtime IAM members only; it never manages
secret payloads or creates versions. It does manage the non-secret positive numeric
version ID selected by each Cloud Run service and job. `latest`, `0`, and aliases are
rejected so scale-to-zero restart cannot silently change a revision's environment.
Effective direct-policy and numeric-reference acceptance remains unavailable until the
signed company-admin attestation gate lands.

The Cloud Run model is fixed to Anthropic. OpenAI credentials are not part of either
environment's runtime inventory. Any previously managed OpenAI secret is forgotten from
Terraform state without destroying the external Secret Manager object; removal of that
object is a separate, explicitly approved cleanup.

Inject each value out of band:

```sh
read -rs SECRET_VALUE
printf '%s' "$SECRET_VALUE" |
  gcloud secrets versions add SECRET_NAME \
    --project festive-ally-503605-v7 \
    --data-file=-
unset SECRET_VALUE
```

Do not place values in a command argument, shell history, GitHub variable, Terraform
variable, plan, state, issue, pull request, or log. Before deployment, check that every
required secret has exactly one intended enabled version without reading its payload.

## Web/Auth.js cutover

Keep Auth.js v5 and `@auth/pg-adapter`; only its Postgres endpoint changes.

The repository currently contains no committed Auth.js schema migration or migration
command. Do not describe one as reviewed, and do not cut over until a separate application
PR adds and tests that contract.

1. Confirm or create `syshin0116-web-prod` in the target region.
2. Create an isolated preview branch and credentials that cannot access the production
   branch.
3. Land a reviewed Auth.js schema/migration contract, then apply it to preview through a
   direct endpoint held only for migration.
4. Configure GitHub and Google OAuth callback URLs for Vercel Preview first.
5. Bind Vercel Preview `DATABASE_URL` to the preview branch's least-privileged direct
   endpoint.
6. Verify login, callback rejection, logout, session refresh, and a fresh browser session.
7. Apply the same reviewed schema contract to production through its direct migration
   endpoint.
8. Promote the same application revision with a separately scoped production direct
   runtime credential after approval.
9. Re-authenticate the sole owner; do not migrate old sessions.
10. Preserve the old database as the rollback source.

Rollback restores the previous Vercel deployment and its previous environment binding. It
does not copy new Auth.js rows back into the old database.

## Agent cutover

The target agent project starts empty. Do not copy test threads or legacy checkpoint
tables. The repository migration entrypoint is `python -m agent.migrate`; it upgrades
Aegra metadata and initializes the LangGraph checkpointer and store schema. The checked-in
Cloud Run migration jobs execute that entrypoint before service delivery, followed by
separate least-privileged grant-probe and guest-retention maintenance jobs. Runtime startup Alembic migration must be
disabled with the non-secret setting
`RUN_MIGRATIONS_ON_STARTUP=false`; a service revision is never the migration runner.
The serving template also fixes `REDIS_BROKER_ENABLED=false` and
`BG_JOB_MAX_RETRIES=0`; together with the other reviewed values and four numeric secret
references, each service has exactly 17 environment entries. The migration, grant-probe,
and maintenance entrypoints do not import `agent.graph` or its runtime preflight and retain
their separate exact three-entry Job environment.

The migration job uses the same immutable image digest as the service, receives an
elevated direct Neon `DATABASE_URL` only for the duration of the job, and must succeed
before deployment. The service receives a separate least-privileged direct runtime URL.
Preview must exercise every Aegra 0.9.24 async and synchronous database path before
cutover; a `-pooler` endpoint is not an allowed substitute.

Aegra 0.9.24 still invokes the LangGraph saver and store `setup()` methods from its
lifespan database initialization even when `RUN_MIGRATIONS_ON_STARTUP=false`. That setting
disables startup Alembic migration; it does not provide a no-DDL runtime startup.
Consequently, in addition to its normal narrow DML grants, the separated runtime role
temporarily needs only the schema-local, idempotent DDL privileges required by those exact
setup calls. It must not receive the broader migration credential, database
administration, role management, or cross-schema privileges.

This temporary grant is a deployment gate, not an assumed permission recipe. Before
preview or production rollout, prove the proposed grants with the actual Neon runtime
credential: initial startup and restart must complete, checkpoint and store operations
must pass, and the project-owned `agent_guest_execution_quarantine` table must permit
`SELECT`, `INSERT`, `UPDATE`, and `DELETE` for the shared runtime/maintenance credential.
The checked-in grant probe exercises that full quarantine CRUD path transactionally;
missing any operation fails before service promotion. Attempts to alter another schema,
manage roles, or perform administrative operations must fail. Record only the tested
grant shape and outcomes. Do not deploy until those real-Neon tests pass. Tighten the
runtime role to DML-only as soon as Aegra offers a supported startup path that skips
saver/store schema setup.

1. Confirm or create `syshin0116-agent-prod`.
2. Create an isolated preview branch and credentials that cannot access the `production`
   branch.
3. Provision the checked-in one-shot migration, grant-probe, and maintenance jobs at the explicit
   `jobs` Terraform stage, using the exact image digest selected for deployment and
   positive numeric secret versions.
4. Give the preview migration job its separately held direct `DATABASE_URL`, run it, and
   require success before creating or updating the service revision.
5. Inject only the preview branch's least-privileged direct runtime endpoint into
   `agent-preview-database-url`, and set `RUN_MIGRATIONS_ON_STARTUP=false`.
6. Prove the preview runtime role's schema-local grant and denial boundaries on real Neon
   as specified above; never print a connection string.
7. Record table names and migration revision only.
8. Deploy the same immutable image digest with the matching runtime service account,
   Cloud Run `max-instances=1`, and exactly one application server worker.
9. Prove the direct runtime endpoint works through every Aegra database path exercised by
   the preview smoke; reject any accidental `-pooler` hostname before startup.
10. Verify `/live`, `/ready`, owner auth, anonymous policy, two-turn persistence, restart
    persistence, exact Agent Protocol v2 streaming, and the deployed instance/worker
    limits.
11. Run the same digest's migration job against production through a separately held
    elevated direct endpoint, inject only its least-privileged direct runtime endpoint,
    repeat the real-Neon grant tests, and shift traffic after all gates pass.

Rollback reassigns Cloud Run traffic to the previous healthy revision. That revision
already retains its previous numeric secret references; do not mutate them in place.
Database migrations must remain compatible with one previous application revision.

## Cloud Run and CD

The repository-side follow-up is implemented. It declares preview/production services,
separate runtime/migration identities and URLs, isolated image builders and registries, one
active four-role WIF provider with a disabled legacy provider, split secretless build and
reviewer-gated release workflows, same-digest migration, grant-probe, and maintenance
jobs, a production-only paused-by-default 15-minute OAuth-authenticated Cloud Scheduler
trigger, exact Cloud Run REST v2 read-back plus etag-bound Job execution before traffic
movement, owner-auth APv2 smoke on the tagged no-traffic revision before promotion, and
revision-traffic rollback. Production deploy rechecks current `main` and all three exact
required GitHub Actions checks after approval; emergency rollback instead requires manual
dispatch, current `main`, an exact revision, and approval while remaining usable on red
CI. The root frozen uv workspace, delivery-specific Docker context allowlist, and real
Linux amd64 CI image build keep the deployed package graph and image inputs reproducible.

Nothing in that change applies Terraform or creates/configures GCP, Neon, GitHub
environment, or secret external state. Follow
[`cloud-run-delivery.md`](cloud-run-delivery.md) for bootstrap and keep
`AGENT_CLOUD_RUN_ENABLED` false until its live gates pass. That variable gates future
delivery workflows only; it does not pause Scheduler, revoke the public invoker, stop a
service, or guarantee zero cost. Terraform creates the production 15-minute schedule
paused, and only a separately reviewed public-launch and billing change may activate it.
The public-access policy remains in
[ADR-0006](../adr/0006-public-anonymous-chat-access.md); application auth is still
owner-only until that later hardening lands.
Anonymous visitors enter only through a separately reviewed Agent Production release
after ADR-0006's isolation, concurrency, retention, and spend gates pass; a pull-request
preview is never the guest release path.

## Verification

Credential-free checks:

```sh
scripts/verify_ops_foundation.sh --static
scripts/verify_ops_foundation.sh --terraform-fmt
scripts/verify_ops_foundation.sh --terraform-init
scripts/verify_ops_foundation.sh --terraform-validate
scripts/verify_ops_foundation.sh --terraform-test
shellcheck scripts/deploy_cloud_run.sh scripts/verify_ops_foundation.sh \
  scripts/validate_agent_delivery_identity.sh
```

Each `--terraform-*` wrapper performs an on-disk preflight before invoking Terraform.
The preflight enumerates Terraform 1.13.5's native `.tf`, `.tfvars`, `.tftest.hcl`,
`.tfmock.hcl`, and `.tfmock.json` candidates plus the reviewed JSON/load variants below
`infra/gcp`, then requires the exact reviewed tracked allowlist of regular files. An extra
tracked, untracked, or gitignored candidate, symlink, FIFO, socket, device, or directory
fails closed. Rejected candidates are classified from directory metadata only; their
contents are never opened. Terraform's internal `.terraform/` path is allowed only as an
ignored, untracked real directory; the preflight checks that boundary without traversing its
contents and does not inspect state, plan, or secret contents.

The static command runs through the root frozen agent workspace, whose development group
pins `python-hcl2==7.3.1`, and uses that parser rather than regular expressions or
source-string grep:

```sh
uv run --frozen --package syshin0116-dev-agent \
  python scripts/ops_foundation_contract.py static --repo-root .
```

It compares the complete
parsed bodies of the foundation resources, all locals, every root check, every output and variable,
the provider/data/backend blocks, and every import target and live object ID. It rejects
unreviewed modules, `moved` and `removed` blocks, provisioners, `local-exec`,
`remote-exec`, external providers/data, `terraform_remote_state`, and other executable
resource types after HCL comments and line breaks are parsed. The eleven deeply nested
Cloud Run and Scheduler resources are additionally covered by a byte-exact SHA-256 pin
over `cloud_run.tf`; the total reviewed inventory is 44 resources.

The only reviewed Terraform test file is
`infra/gcp/tests/foundation.tftest.hcl`; static verification pins its exact SHA-256.
`--terraform-test` runs Terraform's JSON test output through the contract and succeeds
only when that exact file's service, foundation-only, and jobs-only runs are discovered in
the reviewed order and the summary is exactly
`3 passed, 0 failed, 0 errored, 0 skipped`. Terraform's otherwise-successful zero-test
result is a failure. `fmt`, fresh `init -backend=false`, and `validate` remain independent
gates.

Unsigned v1 can be checked locally without any Google API call:

```sh
export OPS_FOUNDATION_ADMIN_EVIDENCE_FILE=/absolute/private/path/admin-iam-structure.json
scripts/verify_ops_foundation.sh --offline-admin-evidence-structure
scripts/verify_ops_foundation.sh --live
```

An invocation with no mode defaults to `--static`; `--live` is always an explicit
operator opt-in. Always invoke the executable directly as shown: sourcing the file and
`bash scripts/verify_ops_foundation.sh ...` are unconditionally rejected.

The first command prints `STRUCTURE ONLY / NOT AUTHENTICATED` on success. The second must
exit nonzero with the trusted-attestation blocker. Its implementation contains no GCP
request path. Neither result approves an apply or deployment. The structure file is
supplied out of band and must not be committed. It has this exact minimal topology
(placeholder IDs and policies only; never copy real company policy data into this
repository):

```json
{
  "schemaVersion": "syshin0116.gcp-admin-iam-evidence/v1",
  "capturedAt": "YYYY-MM-DDTHH:MM:SSZ",
  "project": {
    "id": "festive-ally-503605-v7",
    "number": "72919926064"
  },
  "ancestors": [
    {
      "scope": "organizations/<company-organization-id>",
      "policy": {"bindings": []},
      "rolePermissions": {}
    }
  ],
  "reviewedBindings": []
}
```

Despite the retained v1 field name, `ancestors` contains exactly one declared
organization and proves no parent relationship. Every role present in its policy has one
sorted, duplicate-free, non-empty permission array in `rolePermissions`.
`reviewedBindings` contains a record for every exact binding in that declared scope and
uses the digest rules below. Dangerous permissions, project custom roles, federated or
deleted principals, public principals, groups, and domains are not reviewable exceptions.
Every project remains undeployable through this verifier until signed v2 trust is
implemented.

Do not populate any future live-read environment variables from this document. The
signed-v2 design must separately define authenticated provenance, exact-project scope,
reviewed policy completeness, role and condition digests, and the live resource
inventory. Until that change lands, IAM, service-account keys, buckets, repositories,
WIF, Cloud Run, Secret Manager metadata, and Scheduler state are not live-verified by
this script.

## Deletion policy

Never delete the rollback database as part of a deploy or migration. A future deletion
requires:

1. a fresh logical backup;
2. recorded backup checksum and restore rehearsal;
3. successful web and agent operation through at least two production releases;
4. explicit owner approval in a separate change.
