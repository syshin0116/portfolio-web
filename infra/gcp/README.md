# GCP agent delivery

This directory declares the keyless GCP foundation and the reviewed Cloud Run delivery
topology for the syshin0116.dev native Aegra agent. Terraform still never owns a secret
payload, creates a secret version, or owns a Neon project/credential. It does own the
reviewed positive numeric Secret Manager version ID selected by each Cloud Run template;
mutable aliases such as `latest` are forbidden.

## Managed resources

- required Google APIs;
- one versioned, public-access-blocked GCS Terraform backend;
- isolated regional Docker Artifact Registry repositories for production and preview,
  with active 90-day/30-version and 14-day/20-version cleanup floors respectively;
- distinct production/preview runtime, migrator, deployer, and image-builder service
  accounts, plus a dedicated production maintenance-scheduler identity;
- one canonical active GitHub OIDC provider that maps exact caller/reusable-workflow
  claims to four disjoint builder/deployer roles, plus the managed but disabled legacy
  preview provider;
- environment-specific act-as, service/job update, and secret-access bindings;
- five Production and four disjoint Preview runtime Secret Manager resources, plus one
  separately scoped migration URL resource per environment;
- production and preview Cloud Run services fixed to one instance/one Uvicorn worker;
- same-image migration, real-Neon runtime-grant, and guest-retention maintenance jobs
  for each service, with an active production-only 15-minute Cloud Scheduler job;
- each repository writable only by its matching builder and readable only by its matching
  deployer plus the Cloud Run service agent.

The existing `agent-runtime` resource remains the production runtime. Deployers have no
project-wide Cloud Run role, Artifact Registry write, or Secret Manager payload access.
They receive repository-scoped Artifact Registry read plus the project custom role
`cloudRunAgentDelivery` only on the exact service and three jobs they operate. Its complete
permission set is `run.services.get`, `run.services.update`, `run.revisions.get`,
`run.jobs.get`, `run.jobs.update`, `run.jobs.run`, and `run.operations.get`; it excludes
delete, create, IAM-policy mutation, and job overrides.
Repository tags are intentionally mutable because Artifact Registry cannot delete tagged
versions when immutable tags are enabled. Delivery never trusts or reuses a pre-existing
tag: each run attempt pushes a fresh run/attempt-scoped tag, resolves it in the same job,
and passes only the digest. The repository statically pins active cleanup policies and
retention floors. The explicit post-apply live verifier reads and checks the exact
repository metadata and direct IAM, but the documented dry-run candidate review remains
mandatory before any foundation apply that enables deletion.
The services are publicly invokable at the Cloud Run layer so Vercel-hosted browsers can
reach them; fail-closed Aegra bearer authentication protects APv2 operations.
Public Cloud Run invocation is only transport reachability, not anonymous product access.
Guest subjects remain disabled until ADR-0006's gates pass and a reviewed production
release enables them; an Agent Preview release is never the public guest path.

IAM member resources are deliberately additive: changing them to authoritative
role-level bindings without a reviewed live plan could remove unrelated or
Google-managed members. Post-apply direct-state verification is an explicit read-only
gate: it runs the static contract, permits a fixed command catalogue against only
`festive-ally-503605-v7`, and then requires canonical exact-repository GitHub governance.
It reads direct IAM and repository-owned resource metadata only. It never reads secret
payloads or Terraform state contents, executes workloads, mutates resources, follows or
queries organization/folder/ancestor/project-parent scopes, or queries another project.
The exact project describe may return a parent field; the verifier ignores it and makes
no project-parent claim.

Unsigned v1 is a structure-only file outside every repository/worktree, not
company-admin evidence. It declares exactly one organization but proves no parent
linkage. Every binding must be reviewed; public, group, domain, federated, deleted,
direct workload-account, dangerous or unclassified permission-verb, and
project-custom-role bindings are forbidden. Missing, malformed, stale, future-dated,
duplicate-key, unrelated, or incomplete structure fails, but a passing structure still
is not deployment approval.

Run the verifier only from a trusted local workstation, shell, checkout, and toolchain,
and only through its executable path as shown below. The preflight requires selected
`uv`, `gh`, `gcloud`, and Python executables to be current-user/root-owned regular files
with non-group/other-writable ancestry, derives `HOME` from passwd, and launches children
with an explicit sanitized environment. This boundary does not resist a malicious
same-user workstation or loader injection before the initial shell starts. Its direct
`/bin/bash -p` process ignores `BASH_ENV` and imported shell functions; sourcing the file
is unconditionally refused with no environment override, and invoking
`bash scripts/verify_ops_foundation.sh ...` is also unsupported and refused.
Unsigned structure is not permission to inspect company hierarchy from this repository
and not a waiver of inherited-IAM risk. The live gate verifies exact-project direct IAM,
service-account-key absence, repositories, services, jobs, secrets, WIF, state metadata,
and Scheduler state without claiming inherited-IAM completeness. A signed company-admin
format is needed only if that broader claim is later required.

The canonical active `github-production` provider explicitly maps the immutable repository
and owner numeric IDs. Its `delivery_role` mapping pins event, caller `workflow_ref`, and
called `job_workflow_ref`, and resolves to exactly one of `preview-builder`,
`preview-deployer`, `production-builder`, or `production-deployer`. The provider condition
uses only the mapped numeric IDs and that mapped role allowlist. Builders call
`agent-image-build.yml` without a GitHub environment. Deployers call `agent-release.yml`
and must carry the exact target environment. Production additionally pins
`refs/heads/main`; it accepts `push` plus `workflow_dispatch` for manual build-and-deploy
or revision rollback.

The existing `github` pool deliberately retains both provider resource IDs, but only
`github-production` is active. `github-preview` is Terraform-managed with
`disabled=true`, an inert condition, no delivery-role mapping, and `prevent_destroy`.
Removing or re-enabling it requires a separately reviewed federation migration; the staged
hardening plan must not destroy it.
GitHub environment reviewers, self-review, and the canonical agent/Vercel production
branch sets `{main}` live only in `.github/repository-governance.json`. When that manifest and
`scripts/verify_repository_governance.py` are present, the independent
`--governance-live` mode requires `uv` and `gh`, then delegates without duplicating the
rules. Foundation `--live` requires this same delegation after exact-project GCP reads:

```sh
scripts/verify_ops_foundation.sh --governance-live
```

Any missing API, inaccessible endpoint, or permission denial is a hard **STOP**. The
verifier does not authorize granting IAM, enabling an API, attaching billing, changing
project settings, or executing a job; each requires a separate reviewed change.

Both `Agent Preview` and `Agent Production` require `syshin0116`, allow self-review,
forbid admin bypass, contain exactly `AGENT_SMOKE_BEARER_TOKEN`, and contain zero
environment variables. The image build job references no environment and receives no
smoke token; only the release job crosses this single approval boundary.
That secret must be replaced immediately before each approval with an owner JWT whose
total lifetime is at most two hours and whose remaining lifetime is at least 65 minutes.
The release gate validates those public claims before GCP authentication and never logs
the token. There is no automatic mint yet; a stale secret is an explicit deployment
blocker, not a reason to create a long-lived JWT.

No user-managed service-account key is permitted.

## Remote state

The GCS backend is:

```text
gs://festive-ally-503605-v7-tfstate/syshin0116.dev/gcp/foundation/default.tfstate
```

It uses native locking, object versioning, uniform bucket access, enforced public-access
prevention, and 30-day soft delete. The restricted external copy is the durable recovery
backup. Preserve the gitignored worktree-local migration artifact until that external copy
is independently verified, then remove it only through a separate exact-target cleanup;
never commit either copy.

From the repository root, routine operator commands are:

```sh
scripts/verify_ops_foundation.sh --static
terraform -chdir=infra/gcp init
terraform -chdir=infra/gcp plan \
  -var 'agent_delivery_stage=services' \
  -var 'agent_bootstrap_image=REVIEWED_PRODUCTION_REGISTRY_DIGEST' \
  -var 'agent_preview_bootstrap_image=REVIEWED_PREVIEW_REGISTRY_DIGEST' \
  -var-file=/absolute/private/path/agent-secret-versions.tfvars
```

Terraform is pinned to `1.15.8` in both configuration and `.terraform-version`. Every
remote plan is mandatory review material. Do not apply until the operator has confirmed
that the plan contains only the intended imports, additions, metadata changes, and IAM
member removals; any resource replacement or persistent-resource destroy is a blocker.

Initial setup is an explicit complete-root progression:

1. `foundation` with null image/version inputs creates the registries, identities, WIF,
   IAM, state bucket, and eleven empty secrets, but no Cloud Run resources;
2. `jobs` with isolated production and preview digests plus the exact eleven-key numeric
   version map creates only the two migration, two grant-probe, and two maintenance jobs
   plus resource IAM;
3. after all six jobs pass, `services` adds the two serving surfaces, service IAM, and
   the active production-only 15-minute maintenance schedule.

Never use `-target` to emulate a stage. After bootstrap, retain `services`, both current
exact digests, and the complete external version file on every plan; omission proposes
protected removal and fails closed. Payload injection and version creation remain
out-of-band.

The Scheduler `paused = false` value is a repository-owned Terraform constant, not an
operator input. Its reviewed activation still requires an exact live plan and a verified
first bounded maintenance execution before the web public flags may be enabled. Pausing
it again requires a matching reviewed code change. `AGENT_CLOUD_RUN_ENABLED` gates future
GitHub delivery attempts only; changing it does not pause Scheduler, revoke the public
invoker, stop a running service, or guarantee zero cost.

Owner/evaluation runs may use the existing Anthropic path or the signed-in OpenAI
selector. Anonymous production runs use the exact
`openai:gpt-5.6-luna / 500000 / 51892` tuple, requiring the restored
`openai-api-key` resource and one positive numeric version, and combines the 19,892 µUSD
worst generation allocation with a separate 128,000-token aggregate count-risk ledger
priced at 32,000 µUSD. This is not a documented count price, hidden-token bound, or
provider hard cap; the public billing and account-stop gates remain mandatory. Preview
has no OpenAI credential; its reviewed `removed` block keeps the retired legacy Preview
secret out of Terraform state with `destroy = false`.

Use an ephemeral access token or Application Default Credentials. Never pass a service
account JSON key to Terraform. Do not run `apply` from CI.

From the repository root, credential-free CI uses:

```sh
scripts/verify_ops_foundation.sh --static
scripts/verify_ops_foundation.sh --terraform-fmt
scripts/verify_ops_foundation.sh --terraform-init
scripts/verify_ops_foundation.sh --terraform-validate
scripts/verify_ops_foundation.sh --terraform-test
```

The static verifier runs:

```sh
uv run --frozen --package syshin0116-dev-agent \
  python scripts/ops_foundation_contract.py static --repo-root .
```

It exact-compares the parsed bodies of the foundation resources, every local, check, output,
variable, provider/data/backend block, and import target/live object ID. It rejects
unreviewed modules, `moved` and `removed` blocks, every provisioner, external
provider/data, `terraform_remote_state`, and executable escape resources. The eleven
deeply nested Cloud Run and Scheduler resources are protected by a byte-exact hash of
`cloud_run.tf`; the reviewed inventory totals 44 resources. The reviewed
`.tftest.hcl` file is SHA-256 pinned because the pinned HCL parser cannot parse every valid
Terraform test expression. Before every wrapped Terraform command, an on-disk preflight
uses directory metadata—not candidate contents—to reject any extra tracked, untracked, or
gitignored Terraform 1.15.8 `.tf`, `.tfvars`, `.tftest.hcl`, `.tfmock.hcl`, or
`.tfmock.json` candidate, including every reviewed JSON/load variant, and every symlink
or non-regular candidate.
It permits `.terraform/` only as an ignored, untracked real directory, checks that
boundary without traversing it, and never opens state, plan, secret, or rejected-extra
contents. `--terraform-test` validates Terraform's JSON event stream and requires the
exact reviewed service, foundation-only, and jobs-only runs with summary
`3 passed, 0 failed, 0 errored, 0 skipped`; a green zero-test command is rejected.
Formatting, fresh initialization, and validation remain separate gates.

Application CI also resolves the agent from the root frozen uv workspace and builds the
actual delivery Dockerfile for Linux amd64 through its Dockerfile-specific allowlist.
This rejects workspace-lock, excluded-context, baked-corpus, or target-architecture drift
as required pre-merge evidence. Do not approve `Agent Preview` until `ci/agent` has passed
for the same pull-request head; the release workflow rechecks the live PR head but does
not itself wait on Application CI. Production deploy additionally requires the current
`main` SHA's exact `ci/check`, `protocol/compat`, and `wiki/verify` check-runs after
approval. Manual rollback remains usable on red CI but requires
`workflow_dispatch`, current `main`, environment approval, and an exact revision.

Run `scripts/verify_ops_foundation.sh --static` directly before review; no-argument
execution also defaults to `--static`, while `--live` always requires explicit opt-in.
Select the locally reviewed account explicitly before the post-apply gate:

```sh
export OPS_FOUNDATION_GCLOUD_ACCOUNT='<reviewed local account>'
scripts/verify_ops_foundation.sh --live
```

The repository-pinned account-name digest prevents accidental local-account drift; it
does not authenticate company-admin origin, project parentage, or inherited policy. The
optional `OPS_FOUNDATION_ADMIN_EVIDENCE_FILE` command described in
[`docs/runbooks/gcp-neon-foundation.md`](../../docs/runbooks/gcp-neon-foundation.md)
validates unsigned structure only and is not a live prerequisite or approval input.

A passing live result proves neither public launch nor bounded or zero spend. The
production Scheduler must be `ENABLED`; `PAUSED` is drift, but its exact plan/apply and
first bounded execution still must pass. Public launch remains gated by the Vercel BotID
Basic, provider, and browser checks. Secret injection and state recovery remain in
[`docs/runbooks/gcp-neon-foundation.md`](../../docs/runbooks/gcp-neon-foundation.md).
Bootstrap, normal delivery, and rollback are in
[`docs/runbooks/cloud-run-delivery.md`](../../docs/runbooks/cloud-run-delivery.md).
