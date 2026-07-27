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

The live verifier reads direct policies at the project, every reported folder and
organization ancestor, the Artifact Registry repository, the state bucket, service
accounts, and each managed secret. It resolves every role, including project and
organization custom roles, before classifying impersonation, secret read or mutation,
Artifact Registry read or write, state-object access, and IAM-policy escalation. Sensitive
bindings, every custom-role binding, and every direct state-bucket binding must match
operator-supplied JSON records by exact `scope` + `role` + `member`. Custom roles also pin
the SHA-256 of their complete included-permission inventory; conditional bindings pin the
condition digest. Group, domain, and unrelated principal-set members therefore fail unless
that exact binding was reviewed; public members always fail. A project, containing folder,
or containing organization `ServiceAccount` principal set includes the four workload
identities and is forbidden at the project, ancestor, and repository scopes even when
listed as reviewed. An unreadable ancestor, role, or policy is a blocker.

Terraform uses additive IAM member resources so an unreviewed apply cannot erase unrelated
or Google-managed members. The verifier additionally rejects any direct role on the four
workload identities at the project, ancestor, or repository scopes, whether granted to
their exact addresses or through an encompassing Resource Manager service-account
principal set, project-level
`serviceAccountUser`/`serviceAccountTokenCreator`/`secretAccessor`/Secret Manager admin,
extra members in the managed resource roles, and direct token-creator bindings. If it
finds drift, remediate the exact binding in a separately reviewed plan. Until the follow-up
creates the builder and Cloud Run image-pull identities, direct repository-level Artifact
Registry reader and writer bindings must also be empty; a Google-managed member discovered
there is reviewed, not silently removed.

The policy API does not expand Google Group membership. A reviewed `group:` binding proves
only that the exact policy binding was reviewed, not that directory membership is unchanged;
the operator must attach a separately reviewed group-membership export before approving
such a binding. The service-account principal-set guard does not rely on group expansion.

There is no production deployment workflow in the repository yet. The production
provider therefore cannot honestly bind `job_workflow_ref`; `push` + `main` +
`Production` is the current fail-closed boundary. The deployment PR must add the exact
workflow-ref claim and condition after its workflow path exists, then update both the
Terraform exact-value test and live verifier.

GitHub environment names are exactly `Preview` and `Production`. Their reviewers,
self-review settings, and deployment branches are governed only by
`.github/repository-governance.json` and
`scripts/verify_repository_governance.py`; this foundation does not duplicate that policy.
When those central files are present, `--live` delegates to their live verifier. The
canonical Production deployment-branch set is `{main}`. Delegation requires both `uv` and
`gh` and runs the verifier exactly as:

```sh
uv run --no-project --with pyyaml==6.0.3 \
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
manages resource metadata and required additive runtime IAM members only; it never manages
secret versions or claims that unrelated direct policy members do not exist. The
post-apply live verifier is the acceptance gate for the effective direct policies.

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
Aegra metadata and initializes the LangGraph checkpointer and store schema. This repository
does not yet contain the one-shot deployment job that must run it. Runtime startup
Alembic migration must be disabled with the non-secret setting
`RUN_MIGRATIONS_ON_STARTUP=false`; a service revision is never the migration runner.

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
must pass, and attempts to alter another schema, manage roles, or perform administrative
operations must fail. Record only the tested grant shape and outcomes. Do not deploy
until those real-Neon tests pass. Tighten the runtime role to DML-only as soon as Aegra
offers a supported startup path that skips saver/store schema setup.

1. Confirm or create `syshin0116-agent-prod`.
2. Create an isolated preview branch and credentials that cannot access the `production`
   branch.
3. Land and test a one-shot migration job that runs `python -m agent.migrate` from the
   exact image digest selected for deployment.
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
9. set `RUN_MIGRATIONS_ON_STARTUP=false` on both services and run the same-digest,
   direct-URL `python -m agent.migrate` job before each deployment;
10. configure and verify Cloud Run `max-instances=1` and exactly one application server
    worker, because the concurrency guard is process-local;
11. make the real-Neon runtime grant matrix a required preview and production deployment
    gate; and
12. add preview, production, smoke, rollback, and concurrency gates in a separate PR.

## Verification

Credential-free checks:

```sh
scripts/verify_ops_foundation.sh --static
scripts/verify_ops_foundation.sh --terraform-fmt
scripts/verify_ops_foundation.sh --terraform-init
scripts/verify_ops_foundation.sh --terraform-validate
scripts/verify_ops_foundation.sh --terraform-test
shellcheck scripts/verify_ops_foundation.sh
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

The static command runs `uv run --no-project --with python-hcl2==7.3.1` and uses that
pinned parser, not regular expressions or source-string grep. It compares the complete
parsed bodies of all 16 resources, all locals, the root check, every output and variable,
the provider/data/backend blocks, and every import target and live object ID. It rejects
unreviewed modules, `moved` and `removed` blocks, provisioners, `local-exec`,
`remote-exec`, external providers/data, `terraform_remote_state`, and other executable
resource types after HCL comments and line breaks are parsed.

The only reviewed Terraform test file is
`infra/gcp/tests/foundation.tftest.hcl`; static verification pins its exact SHA-256.
`--terraform-test` runs Terraform's JSON test output through the contract and succeeds only
when that exact file and `foundation_security_contract` run are discovered and the summary
is exactly `1 passed, 0 failed, 0 errored, 0 skipped`. Terraform's otherwise-successful
zero-test result is a failure. `fmt`, fresh `init -backend=false`, and `validate` remain
independent gates.

After an explicitly approved foundation apply, run the live metadata checks:

```sh
scripts/verify_ops_foundation.sh --live
```

Before that command, populate `OPS_FOUNDATION_REVIEWED_IAM_BINDINGS` and
`OPS_FOUNDATION_REVIEWED_STATE_BUCKET_BINDINGS` with reviewed JSON arrays. The first
covers sensitive, critical-principal, and custom-role bindings across the project,
ancestors, and Artifact Registry. The second contains every direct state-bucket binding.
Each record has exact `scope`, `role`, and `member` strings. A custom role additionally
requires `permissions_sha256`; a conditional binding additionally requires
`condition_sha256`.

Canonical scope strings are `projects/<project-id>`, `folders/<folder-id>`,
`organizations/<organization-id>`,
`projects/<project-id>/locations/<region>/repositories/agent`, and
`buckets/<bucket-name>`. Records are compared only against the matching audited scope;
missing or extra records within that scope fail.

`permissions_sha256` is SHA-256 over the UTF-8 compact JSON array of the role's sorted,
unique permission strings. `condition_sha256` uses compact JSON with recursively sorted
object keys. These canonical forms are the ones used by
`scripts/ops_foundation_contract.py`; a different permission, role scope, member, or
condition fails. Do not invent records or digests from this document—derive them from a
separately reviewed live policy and role export. Missing, extra, incomplete, or stale
records for an audited scope fail closed, and public members cannot be reviewed through
this input.

The live verifier inspects API, direct IAM, role definitions, keys, bucket, repository,
WIF provider, and secret-resource metadata only. It never reads secret payloads or
Terraform state values. If the canonical repository-governance files are present, it also
delegates GitHub environment verification to that verifier; otherwise it makes no GitHub
environment claim.

## Deletion policy

Never delete the rollback database as part of a deploy or migration. A future deletion
requires:

1. a fresh logical backup;
2. recorded backup checksum and restore rehearsal;
3. successful web and agent operation through at least two production releases;
4. explicit owner approval in a separate change.
