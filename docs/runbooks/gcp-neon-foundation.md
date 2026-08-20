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
updated: "2026-08-15"
owners: ["@syshin0116"]
refs:
  - ../../infra/gcp/README.md
  - cloud-run-delivery.md
  - web-auth.md
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
- snapshot region: `us-east4` (legacy); active delivery region: `asia-southeast1`;
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

### Production status recorded on 2026-08-15

- the native release deploys an immutable digest to a no-traffic revision, checks
  `/live`, `/ready`, and an unauthenticated APv2 `401`, then promotes it to 100% traffic;
- anonymous Luna chat is live on `https://syshin0116.vercel.app` in Production;
- Preview remains closed to anonymous chat;
- live Auth.js owner-login verification remains unrecorded;
- no provider hard-cap proof, first bounded Scheduler execution, or retained
  abuse/retention/recovery evidence is claimed here.

The reviewed Terraform target remains:

- four `agent` and `agent-preview` repository resources across the active Singapore and
  legacy US regions, with never-reused delivery tags, digest-only deployment, and bounded
  cleanup retention;
- Production-only Cloud Run resources: four jobs at `jobs`, one service at `services`,
  and the maintenance Scheduler plus its invoker at `launch`; Preview registry,
  identities, and secret containers remain dormant;
- distinct preview/production builder, runtime, migrator, and deployer identities;
- the managed direct act-as role on each runtime containing only its matching deployer,
  with known project- and resource-level bypasses rejected by the live verifier;
- no project-wide Cloud Run role and no image-writer role on either deployer;
- five Production and four disjoint Preview runtime Secret Manager resources. The
  Production runtime has direct `secretAccessor` on auth, database, OpenAI, and
  LangSmith; Anthropic remains an unbound container. Each dormant Preview runtime secret
  retains its matching Preview runtime accessor;
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
- the exact seven-permission `cloudRunAgentDelivery` custom role bound only to the
  Production service and its migration, grant-probe, and manual-maintenance jobs, with no
  delete, create, IAM-policy mutation, or job-override permission;
- the `run.jobs.get`, `run.jobs.update`, and `run.operations.get` scheduled-maintenance
  delivery role bound to the Production scheduled-maintenance job without execution
  permission;
- a dedicated keyless scheduler identity with `roles/run.invoker` only on
  `agent-scheduled-maintenance`, and no database-secret access or project-wide role;
- no user-managed service-account keys.

Post-apply direct-state verification is available through the explicit `--live` mode. It
runs the credential-free static contract first, then permits only a fixed read-only
`gcloud` catalogue against project `festive-ally-503605-v7`, and finally requires the
canonical exact-repository GitHub governance verifier to pass. The GCP catalogue checks
the project identity and direct IAM, enabled APIs, custom delivery roles, all four active
and legacy registries and their direct IAM, state-bucket and state-object metadata, exact-project service
accounts and user-managed keys, Secret Manager metadata and direct IAM, WIF, Cloud Run
Production service/jobs and their direct IAM, and the maintenance Scheduler.
For anonymous runtime drift, Production must expose exactly
`openai:gpt-5.6-luna / 500000 / 53837`; Preview has no Cloud Run service or job to inspect.
Its registry, identities, and secret containers remain dormant. This verifies deployed
direct state only and does not prove a provider-side hard spend stop, Scheduler execution,
or retained operational evidence.

The live verifier never reads a secret payload or Terraform state contents, executes a
job, inspects logs, mutates a resource, follows or queries an organization/folder/
ancestor/project-parent scope, or queries another project. An exact project describe may
contain a parent field; the verifier ignores it and makes no parentage claim. It rejects
ambient `CLOUDSDK_*` and `GOOGLE_*` overrides and injects the exact project into every
allowlisted command. The operator must explicitly select the locally reviewed account:

```sh
export OPS_FOUNDATION_GCLOUD_ACCOUNT='<reviewed local account>'
scripts/verify_ops_foundation.sh --live
```

The repository stores only a SHA-256 digest of the expected account name. Matching that
digest prevents accidental use of another local account; it does not authenticate the
account's company-admin provenance or make claims about inherited IAM. A passing result
therefore proves only the checked exact-project direct state plus canonical GitHub
repository/environment governance. It does not prove bounded spend, complete inherited
policy, or project-parent linkage.

Invoke this verifier only from a trusted local workstation, shell, checkout, and
toolchain, and only through its executable path, for example
`scripts/verify_ops_foundation.sh --static`. Its `/bin/bash -p` process ignores
`BASH_ENV` and imported shell functions. Sourcing it or running
`bash scripts/verify_ops_foundation.sh ...` is unsupported and refused; sourcing has no
test or environment override. Live preflight accepts only current-user/root-owned regular
`uv`, `gh`, `gcloud`, and Python executables whose selected and resolved ancestry is not
group/other writable; it derives `HOME` from passwd and gives children a fixed, sanitized
environment. Live mode requires an existing `.venv/bin/python3`, validates its selected
and resolved path before `uv` can query it, pins the exact absolute path into a
configuration-free frozen sync with Python downloads disabled, then validates it again.
Only that absolute selected path may run the static, GCP, or GitHub governance verifier.
The GCP reader is a separate Python process launched with `-E -s`, and every request must
match the SHA-pinned literal command oracle. This boundary does not resist a malicious
same-user workstation or loader injection before the initial shell starts.

A missing API, permission denial, inaccessible endpoint, or unreadable response is a
hard **STOP**, not remediation authority. This verifier never authorizes an IAM grant,
API enablement, billing attachment, project-setting change, or job execution; make any
such change only through its own reviewed plan and PR.

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
shape, not live or inherited IAM. The explicit live mode checks direct roles on the nine
workload identities, Resource Manager service-account principal sets, project-wide
impersonation or secret access, extra managed-resource members, user-managed keys, and
repository cross-write. Inherited organization/folder IAM remains outside this
repository's verified boundary.

Unsigned v1 is a structure-only precursor, not a waiver of inherited-IAM risk. This
repository must not collect policy by traversing the company hierarchy. Until a trusted
company-admin signature authenticates complete project-bound inherited-IAM input,
no command or document may claim inherited-IAM completeness. Signed evidence is not a
prerequisite for the narrower exact-project direct-state gate.

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
`scripts/verify_ops_foundation.sh --governance-live`; foundation `--live` requires the
same delegation after its exact-project GCP reads and fails if it cannot run. The
canonical `Agent Production`, `Evaluation Publication`, and Vercel `Production`
deployment-branch set is `{main}`. `Evaluation Publication` must use `syshin0116` as its
required reviewer, allow the solo owner to review, forbid admin bypass, and contain no
environment secrets or variables. It must never be added to the GCP WIF provider
conditions.

Both agent environments require reviewer `syshin0116`, allow the solo owner to review,
forbid admin bypass, and contain zero environment secrets and zero environment variables.
The image build job references no environment. The release job crosses the environment
approval boundary before GCP authentication and deployment. It does not consume an owner
JWT or run an authenticated APv2 smoke.

As of 2026-07-28, the live repository has the `Evaluation Publication` environment with
required reviewer `syshin0116`, `prevent_self_review=false`, admin bypass disabled, and one
custom deployment branch policy for `main`. The frozen live verifier below passes,
including its fail-closed zero-count checks for environment secrets and variables; an
independent direct GitHub API check also confirmed both inventories are empty. The manual
publication workflow has not been dispatched, and no evaluation result is claimed as
published gold.
Delegation requires both `uv` and `gh` and runs the verifier exactly as:

```sh
scripts/verify_ops_foundation.sh --governance-live
```

### Neon: verified live agent state versus remaining target

A later read-only Neon/SQL acceptance recorded the following non-secret live inventory:

- account plan: `free`;
- agent project: `restless-firefly-14926671`, region `us-east-1`, PostgreSQL 17;
- production branch: `br-damp-term-au77gvkd`, runtime role `agent_runtime`;
- preview branch: `br-ancient-flower-aukvhvxj`, runtime role
  `agent_preview_runtime`;
- both runtime roles have zero admin flags and zero role memberships;
- both can connect to their own database without database-level `CREATE`;
- both have `USAGE` and `CREATE` on the intended `public` schema, while independent
  probes reject `CREATE SCHEMA` and `CREATE ROLE`;
- cross-branch credential-denial probes pass in both directions.

Endpoint hosts, URLs, passwords, and credentials are deliberately omitted. They remain
only in private local mode-`0600` state and must never be copied into this repository,
logs, issues, plans, or pull requests. This evidence covers the agent project only; it
does not silently promote the still-separate Auth.js web-database target to verified.

What is verified in this repository is the authentication architecture:

- `web/` uses Auth.js v5 (`next-auth` v5 beta);
- `@auth/neon-adapter` stores Auth.js tables through the request-scoped Neon Pool and
  `DATABASE_URL`;
- GitHub and Google remain the OAuth providers;
- Neon supplies Postgres only. **Neon Auth is not being adopted.**

The accepted target from
[ADR-0007](../adr/0007-postgres-on-neon-split-projects.md) is:

| Purpose | Target project | Target region | Target branch | Status |
|---|---|---|---|---|
| Auth.js production | `syshin0116-web-prod` | `aws-us-east-1` | `production` | Unverified; create or confirm before cutover |
| Auth.js preview | `syshin0116-web-prod` | `aws-us-east-1` | isolated preview branch | Unverified; create with separate credentials |
| Aegra production | `restless-firefly-14926671` | `us-east-1` | `br-damp-term-au77gvkd` | Verified project/branch and least-privileged runtime-role probes |
| Aegra preview | `restless-firefly-14926671` | `us-east-1` | `br-ancient-flower-aukvhvxj` | Verified isolation and cross-branch credential denial |
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
  -var 'agent_delivery_stage=launch' \
  -var 'agent_bootstrap_image=REVIEWED_PRODUCTION_REGISTRY_DIGEST' \
  -var 'agent_preview_bootstrap_image=null' \
  -var-file=/absolute/private/path/agent-secret-versions.tfvars
```

Use Terraform `1.15.8`; `required_version` and `infra/gcp/.terraform-version` pin the same
exact release. A fresh remote plan is mandatory before every apply. Review the full plan,
including imports and IAM removals, and stop on any persistent-resource replacement or
destroy. The mock plan in CI is not evidence of live safety and cannot substitute for
this review. During first-time setup, use the explicit
`foundation -> jobs -> services -> launch` sequence in the
[Cloud Run delivery runbook](cloud-run-delivery.md), never `-target`.

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
- `langsmith-api-key` (Production tracing runtime only);
- `openai-api-key` (Production guest runtime only).

Preview owns `agent-preview-database-url`, `agent-preview-auth-secret`,
`agent-preview-anthropic-api-key`, and `agent-preview-langsmith-api-key`; it has no
OpenAI runtime credential. Terraform
manages resource metadata and required additive runtime IAM members only; it never manages
secret payloads or creates versions. It does manage the non-secret positive numeric
version ID selected by each Cloud Run service and job. `latest`, `0`, and aliases are
rejected so scale-to-zero restart cannot silently change a revision's environment.
The exact-project live gate checks secret metadata, exact direct accessors, and the
positive numeric references exposed by Cloud Run. It never reads or validates a secret
payload, so payload correctness remains an independent smoke-test responsibility.

The Production Cloud Run service declares Luna as the default model, injects
`openai-api-key`, pins anonymous runs to Luna, and lets signed runs select the reviewed
Luna, Terra, or Sol models. Preview has no Cloud Run service and remains OpenAI-free. It
cannot be enabled until its resources and provider contract are restored through a
reviewed change. The previously
managed Preview OpenAI secret stays forgotten from Terraform state without destroying
the external Secret Manager object; removal of that object is a separate, explicitly
approved cleanup.

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

Keep Auth.js v5 and `@auth/neon-adapter`; only its Postgres endpoint changes.

The committed, idempotent Auth.js schema and exact verifier are operated through
`bun run auth:migrate` and `bun run auth:verify` from `web/`. Follow the
[web authentication runbook](web-auth.md); the elevated
`AUTH_DATABASE_MIGRATION_URL` must never enter Vercel runtime configuration.

1. Confirm or create `syshin0116-web-prod` in the target region.
2. Create an isolated preview branch and credentials that cannot access the production
   branch.
3. Apply the reviewed Auth.js schema contract to preview through its separately held
   direct migration endpoint, then require the independent verifier to pass.
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

The repository migration entrypoint is `python -m agent.migrate`; it upgrades Aegra
metadata and initializes the LangGraph checkpointer and store schema. Terraform declares
four jobs: `agent-migrate`, `agent-grants`, the manually runnable `agent-maintenance`, and
the Scheduler-only `agent-scheduled-maintenance`. The first three require separate
operator approval to run. After the launch stage, Scheduler invokes only
`agent-scheduled-maintenance`. Normal native CD does not update or execute those jobs.
Runtime startup Alembic migration must be disabled with the
non-secret setting
`RUN_MIGRATIONS_ON_STARTUP=false`; a service revision is never the migration runner.
The serving template also fixes `REDIS_BROKER_ENABLED=false` and
`BG_JOB_MAX_RETRIES=0`; together with the other reviewed values, Production has 16 plain
values and three numeric secret references for 19 total environment entries. Preview has
no serving template.
The migration, grant-probe, and both maintenance entrypoints do not import `agent.graph`
or its runtime preflight and retain their separate exact three-entry Job environment.

Any manual migration run receives an elevated direct Neon `DATABASE_URL` only for the
duration of the job. The service receives a separate least-privileged direct runtime URL.
Job image selection and execution require a separate approval; a successful service
release is not evidence that any job ran. A `-pooler` endpoint is not an allowed
substitute.

Aegra 0.9.25 still invokes the LangGraph saver and store `setup()` methods from its
lifespan database initialization even when `RUN_MIGRATIONS_ON_STARTUP=false`. That setting
disables startup Alembic migration; it does not provide a no-DDL runtime startup.
Consequently, in addition to its normal narrow DML grants, the separated runtime role
temporarily needs only the schema-local, idempotent DDL privileges required by those exact
setup calls. It must not receive the broader migration credential, database
administration, role management, or cross-schema privileges.

This temporary grant is a deployment gate, not an assumed permission recipe. Before a
new environment or schema change, prove the proposed grants with the actual Neon runtime
credential: initial startup and restart must complete, checkpoint and store operations
must pass, and the project-owned `agent_guest_execution_quarantine` table must permit
`SELECT`, `INSERT`, `UPDATE`, and `DELETE` for the shared runtime/maintenance credential.
The checked-in grant probe exercises that full quarantine CRUD path transactionally;
missing any operation fails before service promotion. Attempts to alter another schema,
manage roles, or perform administrative operations must fail. Record only the tested
grant shape and outcomes. Do not deploy until those real-Neon tests pass. Tighten the
runtime role to DML-only as soon as Aegra offers a supported startup path that skips
saver/store schema setup.

For a future Production cutover or schema change, follow the four-stage
`foundation -> jobs -> services -> launch` sequence in the
[Cloud Run delivery runbook](cloud-run-delivery.md). Use one reviewed Production digest,
keep `agent_preview_bootstrap_image=null`, and supply exactly four positive numeric
Production secret version IDs. Run only migration, grant-probe, and manual maintenance
after the `jobs` apply. Do not run scheduled maintenance manually. Preview requires a
separate reviewed restoration before it can participate in this sequence.

The release workflow has no automated rollback path. A separately approved operator can
manually reassign Cloud Run traffic to a known healthy previous revision. That revision
retains its previous numeric secret references; do not mutate them in place. Database
migrations must remain compatible with one previous application revision.

## Cloud Run and CD

The native build resolves an immutable image digest. After `Agent Production` approval,
the Production release rechecks current `main` and its exact required checks, deploys that
digest to a tagged no-traffic revision, verifies `/live`, `/ready`, and unauthenticated
APv2 `401`, then sends 100% traffic to the new revision and removes the smoke tag.

The normal workflow does not apply Terraform, run migration/grant/maintenance jobs, run
an authenticated two-turn provider smoke, or automate rollback. Manual traffic
reassignment to a known healthy revision requires separate approval. Terraform resources
for jobs and Scheduler remain staged infrastructure operated outside normal CD.

Production anonymous Luna chat is live on `https://syshin0116.vercel.app`; Preview remains
closed and has no Cloud Run resource. Its workflow requires a separate Preview flag, and
the current release does not recheck the pull-request head or CI after approval. Do not
enable it until the resources are restored and that gap is closed. Auth.js owner-login
verification, provider hard-cap proof, the first bounded Scheduler execution, and retained
abuse/retention/recovery evidence remain unverified.
The public-access policy remains in
[ADR-0006](../adr/0006-public-anonymous-chat-access.md).

## Verification

Credential-free checks:

```sh
scripts/verify_ops_foundation.sh --static
scripts/verify_ops_foundation.sh --terraform-fmt
scripts/verify_ops_foundation.sh --terraform-init
scripts/verify_ops_foundation.sh --terraform-validate
scripts/verify_ops_foundation.sh --terraform-test
shellcheck scripts/verify_ops_foundation.sh scripts/validate_agent_delivery_identity.sh
```

Each `--terraform-*` wrapper performs an on-disk preflight before invoking Terraform.
The preflight enumerates Terraform 1.15.8's native `.tf`, `.tfvars`, `.tftest.hcl`,
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
only when that exact file's `foundation_security_contract`,
`foundation_bootstrap_contract`, `jobs_bootstrap_contract`, and
`services_bootstrap_contract` runs are discovered in the reviewed order and the summary is
exactly
`4 passed, 0 failed, 0 errored, 0 skipped`. Terraform's otherwise-successful zero-test
result is a failure. `fmt`, fresh `init -backend=false`, and `validate` remain independent
gates.

Unsigned v1 remains available only as an optional structure diagnostic without any
Google API call:

```sh
export OPS_FOUNDATION_ADMIN_EVIDENCE_FILE=/absolute/private/path/admin-iam-structure.json
scripts/verify_ops_foundation.sh --offline-admin-evidence-structure
```

Success prints `STRUCTURE ONLY / NOT AUTHENTICATED`. This diagnostic is neither an input
nor a prerequisite to `--live`, and the live path never upgrades unsigned input into
approval. The structure file is supplied out of band and must not be committed.

The exact-project direct-state and GitHub governance gate is a separate explicit
operator action:

```sh
export OPS_FOUNDATION_GCLOUD_ACCOUNT='<reviewed local account>'
scripts/verify_ops_foundation.sh --live
```

An invocation with no mode defaults to `--static`. Always invoke the executable directly
as shown: sourcing the file and `bash scripts/verify_ops_foundation.sh ...` are
unconditionally rejected. `--live` runs static verification first, requires the
repository-pinned account name, permits only its fixed reads against
`festive-ally-503605-v7`, then runs the exact-repository GitHub governance verifier. It
does not read unsigned evidence, another GCP project, the company hierarchy, secret
payloads, or Terraform state contents.

The optional structure file has this exact minimal topology (placeholder IDs and policies
only; never copy real company policy data into this repository):

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
No direct-state result consumes this file or treats it as company-admin evidence.

Do not populate the live account selector from unsigned evidence. The pinned account-name
digest prevents accidental local-account drift but does not prove company-admin origin,
project parentage, or inherited-policy completeness. Introduce signed company-admin
evidence only through a separate reviewed contract if those broader claims become
necessary; do not add organization/folder traversal to this repository.

Even a passing `--live` result is not spend acceptance. Production anonymous chat is
already live and Preview remains closed. The first bounded Scheduler execution and
retained migration/grant/retention, abuse, and recovery evidence remain unverified. Luna
input-count billing, including rejected or oversized count requests and a proven
pre-provider upper bound, remains unresolved; the configured daily ledger and per-run
reservation do not prove a provider-wide hard cap or zero spend.

## Deletion policy

Never delete the rollback database as part of a deploy or migration. A future deletion
requires:

1. a fresh logical backup;
2. recorded backup checksum and restore rehearsal;
3. successful web and agent operation through at least two production releases;
4. explicit owner approval in a separate change.
