# GCP agent delivery

This directory declares the keyless GCP foundation and the reviewed Cloud Run delivery
topology for the syshin0116.dev native Aegra agent. Terraform still never owns a secret
payload, creates a secret version, or owns a Neon project/credential. It does own the
reviewed positive numeric Secret Manager version ID selected by each Cloud Run template;
mutable aliases such as `latest` are forbidden.

## Managed resources

- required Google APIs;
- one versioned, public-access-blocked GCS Terraform backend;
- four Docker Artifact Registry resources: production and preview names in the active
  Singapore region and the legacy US region, with 90-day/30-version and
  14-day/20-version cleanup floors respectively;
- distinct production/preview runtime, migrator, deployer, and image-builder service
  accounts, plus a dedicated production maintenance-scheduler identity;
- one canonical active GitHub OIDC provider that maps exact caller/reusable-workflow
  claims to four disjoint builder/deployer roles, plus the managed but disabled legacy
  preview provider;
- environment-specific act-as, service/job update, and secret-access bindings;
- five Production and four disjoint Preview runtime Secret Manager resources, plus one
  separately scoped migration URL resource per environment;
- one Production Cloud Run service fixed to one instance and one Uvicorn worker; Preview
  registry, identities, and secret containers remain dormant with no service or job;
- four Production jobs for migration, real-Neon runtime grants, manual retention, and
  scheduled retention, plus a Production-only 15-minute Cloud Scheduler resource created
  only at launch;
- each repository writable only by its matching builder and readable only by its matching
  deployer plus the Cloud Run service agent.

The existing `agent-runtime` resource remains the production runtime. Deployers have no
project-wide Cloud Run role, Artifact Registry write, or Secret Manager payload access.
The Production deployer receives repository-scoped Artifact Registry read plus the project
custom role `cloudRunAgentDelivery` only on the exact service and the migration,
grant-probe, and manual-maintenance jobs. Its complete
permission set is `run.services.get`, `run.services.update`, `run.revisions.get`,
`run.jobs.get`, `run.jobs.update`, `run.jobs.run`, and `run.operations.get`; it excludes
delete, create, IAM-policy mutation, and job overrides.
A separate custom role gives the Production deployer only `run.jobs.get`,
`run.jobs.update`, and `run.operations.get` on the scheduled-maintenance job, without
execution permission. Only the Scheduler identity has
`roles/run.invoker` on that job, and only at the `launch` stage.
Repository tags are intentionally mutable because Artifact Registry cannot delete tagged
versions when immutable tags are enabled. Delivery never trusts or reuses a pre-existing
tag: each run attempt pushes a fresh run/attempt-scoped tag, resolves it in the same job,
and passes only the digest. The repository statically pins active cleanup policies and
retention floors. The explicit post-apply live verifier reads and checks the exact
repository metadata and direct IAM, but the documented dry-run candidate review remains
mandatory before any foundation apply that enables deletion.
The Production service is publicly invokable at the Cloud Run layer so Vercel-hosted
browsers can reach it; fail-closed Aegra bearer authentication protects APv2 operations.
Public Cloud Run invocation is only transport reachability, not anonymous product access.
Production anonymous Luna chat is live on `https://syshin0116.vercel.app`; Preview remains
closed and is never the public guest path.

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
`refs/heads/main`; it accepts `push` plus `workflow_dispatch` for delivery. The workflow
has no automated rollback path.

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
forbid admin bypass, and contain zero environment secrets and zero environment variables.
The image build job references no environment; only the release job crosses this approval
boundary.

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
  -var 'agent_delivery_stage=launch' \
  -var 'agent_bootstrap_image=REVIEWED_PRODUCTION_REGISTRY_DIGEST' \
  -var 'agent_preview_bootstrap_image=null' \
  -var-file=/absolute/private/path/agent-secret-versions.tfvars
```

Terraform is pinned to `1.15.8` in both configuration and `.terraform-version`. Every
remote plan is mandatory review material. Do not apply until the operator has confirmed
that the plan contains only the intended imports, additions, metadata changes, and IAM
member removals; any resource replacement or persistent-resource destroy is a blocker.

Initial setup is an explicit complete-root progression:

1. `foundation` with null image/version inputs creates the registries, identities, WIF,
   IAM, state bucket, and empty secret containers, but no Cloud Run resources;
2. `jobs` with one Production digest, a null Preview image, and the exact four-key
   Production numeric version map creates four Production jobs plus resource IAM;
3. after migration, grant-probe, and manual maintenance pass, `services` adds one
   Production service and its IAM, with no Scheduler;
4. after the serving release passes, `launch` adds only the Production maintenance
   Scheduler and its invoker binding on `agent-scheduled-maintenance`.

This is a Terraform bootstrap sequence, not the native release workflow. Normal CD does
not update or execute the migration, grant-probe, or maintenance jobs.

Never use `-target` to emulate a stage. After bootstrap, retain `launch`, the current
Production digest, a null Preview image, and the complete four-key Production version
file on every plan. Omission proposes protected removal and fails closed. Payload
injection and version creation remain out-of-band.

The Scheduler `paused = false` value is a repository-owned Terraform constant, not an
operator input. Production anonymous chat is already live, but a first bounded Scheduler
execution is not recorded here. Pausing it requires a matching reviewed code change.
`AGENT_CLOUD_RUN_ENABLED` gates future GitHub delivery attempts only; changing it does not
pause Scheduler, revoke the public invoker, stop a running service, or guarantee zero
cost.

Production owner runs use the server-owned OpenAI default or the signed-in OpenAI
selector. Isolated evaluation fixtures may inject the existing Anthropic path, but the
Cloud Run runtime does not bind that secret. Anonymous Production runs use the exact
`openai:gpt-5.6-luna / 500000 / 53837` tuple, requiring the restored
`openai-api-key` resource and one positive numeric version, and combines the 21,837 µUSD
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
exact reviewed `foundation_security_contract`, `foundation_bootstrap_contract`,
`jobs_bootstrap_contract`, and `services_bootstrap_contract` runs with summary
`4 passed, 0 failed, 0 errored, 0 skipped`; a green zero-test command is rejected.
Formatting, fresh initialization, and validation remain separate gates.

Application CI also resolves the agent from the root frozen uv workspace and builds the
actual delivery Dockerfile for Linux amd64 through its Dockerfile-specific allowlist.
This rejects workspace-lock, excluded-context, baked-corpus, or target-architecture drift
as required pre-merge evidence. Preview delivery is dormant: its caller also requires
`AGENT_CLOUD_RUN_PREVIEW_ENABLED=true`, while Terraform creates no Preview service or job
and requires a null Preview image. Do not enable it until those resources are restored.
The current Preview release does not recheck the pull-request head or CI after approval,
so restoration must close that gap. Production deploy requires the current
`main` SHA's exact `ci/check`, `protocol/compat`, and `wiki/verify` check-runs after
approval. It deploys the immutable digest to a no-traffic revision, checks `/live`,
`/ready`, and unauthenticated APv2 `401`, then promotes 100% traffic. It does not run the
Terraform jobs or an authenticated two-turn provider smoke. Rollback is a separately
approved manual traffic reassignment to a known healthy revision.

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

A passing live result proves neither bounded nor zero spend. Production anonymous Luna
chat is live on `https://syshin0116.vercel.app`, while Preview remains closed. Auth.js
owner-login verification, provider hard-cap proof, the first bounded Scheduler execution,
and retained abuse/retention/recovery evidence remain unverified. Secret injection and
state recovery remain in
[`docs/runbooks/gcp-neon-foundation.md`](../../docs/runbooks/gcp-neon-foundation.md).
Bootstrap, normal delivery, and rollback are in
[`docs/runbooks/cloud-run-delivery.md`](../../docs/runbooks/cloud-run-delivery.md).
