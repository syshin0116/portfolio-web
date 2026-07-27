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
updated: "2026-07-27"
owners: ["@syshin0116"]
refs:
  - ../../infra/gcp/README.md
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

- immutable image tags;
- distinct `agent-preview-runtime` and `agent-runtime` identities;
- the managed direct act-as role on each runtime containing only its matching deployer,
  with known project- and resource-level bypasses rejected by the live verifier;
- no project-wide Cloud Run role and no image-writer role on either deployer;
- five disjoint empty Secret Manager resources per environment, each with one managed
  direct `secretAccessor` member for the matching runtime;
- preview federation restricted to the numeric repository and owner IDs, the `Preview`
  environment, and the `pull_request` event;
- production federation restricted to the numeric repository and owner IDs, the `push`
  event, `refs/heads/main`, and the `Production` environment;
- no user-managed service-account keys.

The live verifier additionally rejects public IAM members, any direct project or
repository role on the four workload identities, project-level
`serviceAccountUser`/`serviceAccountTokenCreator`/`secretAccessor`/Secret Manager admin,
extra members in the managed resource roles, and direct token-creator bindings. Terraform
uses additive IAM member resources so an unreviewed apply cannot erase unrelated or
Google-managed members. If the verifier finds drift, treat it as a blocker and remediate
the exact binding in a separately reviewed plan. Until the follow-up creates the builder
and Cloud Run image-pull identities, direct repository-level Artifact Registry reader and
writer bindings must also be empty; a Google-managed member discovered there is reviewed,
not silently removed.

There is no production deployment workflow in the repository yet. The production
provider therefore cannot honestly bind `job_workflow_ref`; `push` + `main` +
`Production` is the current fail-closed boundary. The deployment PR must add the exact
workflow-ref claim and condition after its workflow path exists, then update both the
Terraform exact-value test and live verifier.

Preview has no required environment reviewer so pull-request deployments cannot deadlock
on the sole owner approving their own change. Production keeps the owner review gate; its
self-review setting is governed by the repository governance manifest.

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
runtimes use Neon pooled endpoints. Schema or migration commands use separately held
direct endpoints only; never expose a direct migration credential to Vercel or Cloud Run
runtime configuration.

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
terraform -chdir=infra/gcp init
terraform -chdir=infra/gcp plan
```

Use Terraform `1.13.5`; `required_version` and `infra/gcp/.terraform-version` pin the same
exact release. A fresh remote plan is mandatory before every apply. Review the full plan,
including imports and IAM removals, and stop on any persistent-resource replacement or
destroy. The mock plan in CI is not evidence of live safety and cannot substitute for
this review.

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
- `openai-api-key`;
- `langsmith-api-key`.

Preview resource names use the same suffixes with the `agent-preview-` prefix. Terraform
manages resource metadata and exact runtime IAM only; it never manages secret versions.

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
5. Bind Vercel Preview `DATABASE_URL` to the preview branch's pooled endpoint.
6. Verify login, callback rejection, logout, session refresh, and a fresh browser session.
7. Apply the same reviewed schema contract to production through its direct migration
   endpoint.
8. Promote the same application revision with a separately scoped production pooled
   runtime credential after approval.
9. Re-authenticate the sole owner; do not migrate old sessions.
10. Preserve the old database as the rollback source.

Rollback restores the previous Vercel deployment and its previous environment binding. It
does not copy new Auth.js rows back into the old database.

## Agent cutover

The target agent project starts empty. Do not copy test threads or legacy checkpoint
tables. The repository does not yet contain the target Aegra schema/migration command;
the legacy custom server's startup-created tables are not that contract.

1. Confirm or create `syshin0116-agent-prod`.
2. Create an isolated preview branch and credentials that cannot access the `production`
   branch.
3. Land and test the target Aegra schema/migration contract in the application revision.
4. Run that reviewed migration against preview with its direct endpoint.
5. Inject only the preview branch's pooled runtime endpoint into
   `agent-preview-database-url`.
6. Record table names and migration revision only; never print a connection string.
7. Deploy an immutable image digest with the matching runtime service account.
8. Verify `/live`, `/ready`, owner auth, anonymous policy, two-turn persistence, restart
   persistence, and exact Agent Protocol v2 streaming.
9. Apply the same migration to production through a separately held direct endpoint,
   inject only its pooled runtime endpoint, and shift traffic after smoke tests pass.

Rollback reassigns Cloud Run traffic to the previous healthy revision and restores the
previous secret version. Database migrations must remain compatible with one previous
application revision.

## Cloud Run and CD follow-up

This foundation intentionally creates no Cloud Run service, build workflow, or deployment
workflow. Until those resources exist, neither deployer needs a Cloud Run role.
Deployment sequencing remains in the
[RAG restack plan](../plans/rag-restack.md), and the public-access policy remains in
[ADR-0006](../adr/0006-public-anonymous-chat-access.md).

The follow-up deployment PR must:

1. create preview and production services through reviewed infrastructure;
2. grant each deployer update access only to its existing service, never project-wide
   `roles/run.admin`;
3. keep the existing environment-specific `serviceAccountUser` binding;
4. build images through a distinct builder identity with repository-scoped writer access;
5. grant repository-scoped `roles/artifactregistry.reader` to the exact Cloud Run
   image-pull principal, not to either deployer or application runtime by assumption;
6. pass only an immutable digest from the builder to the deployer;
7. add exact `job_workflow_ref` mapping and conditions to both OIDC providers after the
   workflow paths exist;
8. use GitHub OIDC and reviewed environments, with no JSON keys or long-lived cloud
   credentials;
9. add preview, production, smoke, rollback, and concurrency gates in a separate PR.

## Verification

Credential-free checks:

```sh
terraform -chdir=infra/gcp fmt -check -recursive
terraform -chdir=infra/gcp init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/gcp validate
terraform -chdir=infra/gcp test
shellcheck scripts/verify_ops_foundation.sh
scripts/verify_ops_foundation.sh --static
```

After an explicitly approved foundation apply, run the live metadata checks:

```sh
scripts/verify_ops_foundation.sh --live
```

The live verifier inspects API, IAM, key, bucket, repository, provider, secret-resource,
and GitHub environment metadata only. It never reads secret payloads or Terraform state
values.

## Deletion policy

Never delete the rollback database as part of a deploy or migration. A future deletion
requires:

1. a fresh logical backup;
2. recorded backup checksum and restore rehearsal;
3. successful web and agent operation through at least two production releases;
4. explicit owner approval in a separate change.
