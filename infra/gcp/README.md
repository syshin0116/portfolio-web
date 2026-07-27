# GCP agent delivery

This directory declares the keyless GCP foundation and the reviewed Cloud Run delivery
topology for the syshin0116.dev native Aegra agent. Terraform still never owns a secret
payload, secret version, Neon project, or Neon credential.

## Managed resources

- required Google APIs;
- one versioned, public-access-blocked GCS Terraform backend;
- one regional Docker Artifact Registry repository with immutable tags;
- distinct production/preview runtime, migrator, and deployer service accounts plus one
  image-builder identity;
- separate GitHub OIDC providers for exact `Agent Preview` and `Agent Production`
  caller/reusable workflow paths;
- environment-specific act-as, service/job update, and secret-access bindings;
- five disjoint empty runtime Secret Manager resources plus one separately scoped
  migration URL resource per environment;
- production and preview Cloud Run services fixed to one instance/one Uvicorn worker;
- same-image migration and real-Neon runtime-grant jobs for each service;
- repository writer only for the builder and readers only for the deployers plus the
  Cloud Run service agent.

The existing `agent-runtime` resource remains the production runtime. Deployers have no
project-wide Cloud Run role, Artifact Registry write, or Secret Manager payload access.
They receive repository-scoped Artifact Registry read and `roles/run.developer` only on
the exact service and two jobs they operate.
The services are publicly invokable at the Cloud Run layer so Vercel-hosted browsers can
reach them; fail-closed Aegra bearer authentication protects APv2 operations.

IAM member resources are deliberately additive: changing them to authoritative
role-level bindings without a reviewed live plan could remove unrelated or
Google-managed members. The post-apply live verifier is the acceptance gate. It reads
project, ancestor, repository, state-bucket, service-account, and secret policies and
resolves every predefined or custom role before checking sensitive permissions. Public
members fail. Every sensitive, custom-role, group/domain/principal-set, and direct
state-bucket binding must match an explicit reviewed JSON record by exact scope, role, and
member. Custom roles additionally pin the digest of the full included-permission set, and
conditional bindings pin their condition digest. The verifier also rejects extra direct
members for the managed roles and direct project or ancestor roles on the seven
user-managed workload identities. That rejection covers exact service-account members plus
project, containing-folder, and containing-organization `ServiceAccount` principal sets;
those encompassing sets cannot be allowlisted as reviewed. The complete repository policy
must contain only the builder writer and the two deployer plus Cloud Run service-agent
readers. An unreadable policy or role and any other failure require a separate reviewed
IAM remediation; they are never ignored or overwritten blindly. Google Group membership
is not expanded by the policy API, so any reviewed `group:` binding also requires a
separately reviewed directory-membership export.

The OIDC providers pin the immutable repository and owner numeric IDs, environment, event,
caller `workflow_ref`, and called `job_workflow_ref`. Production additionally pins
`refs/heads/main`; it accepts `push` plus an environment-approved `workflow_dispatch` for
manual digest deployment or revision rollback.

The existing `github` pool deliberately retains exactly the enabled `github-preview` and
`github-production` providers. Splitting environments into separate pools requires a
reviewed state/import and federation migration plan; it is not an in-place hardening edit.
GitHub environment reviewers, self-review, and the canonical agent/Vercel production
branch sets `{main}` live only in `.github/repository-governance.json`. When that manifest and
`scripts/verify_repository_governance.py` are present, the live foundation verifier
requires `uv` and `gh`, then delegates without duplicating the rules:

```sh
uv run --no-project --with pyyaml==6.0.3 \
  python scripts/verify_repository_governance.py --live
```

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
terraform -chdir=infra/gcp plan
```

Terraform is pinned to `1.13.5` in both configuration and `.terraform-version`. Every
remote plan is mandatory review material. Do not apply until the operator has confirmed
that the plan contains only the intended imports, additions, metadata changes, and IAM
member removals; any resource replacement or persistent-resource destroy is a blocker.

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
uv run --no-project --with python-hcl2==7.3.1 \
  python scripts/ops_foundation_contract.py static --repo-root .
```

It exact-compares the parsed bodies of the foundation resources, every local, check, output,
variable, provider/data/backend block, and import target/live object ID. It rejects
unreviewed modules, `moved` and `removed` blocks, every provisioner, external
provider/data, `terraform_remote_state`, and executable escape resources. The seven
deeply nested Cloud Run resources are protected by a byte-exact hash of `cloud_run.tf`;
the reviewed inventory totals 32 resources. The reviewed
`.tftest.hcl` file is SHA-256 pinned because the pinned HCL parser cannot parse every valid
Terraform test expression. Before every wrapped Terraform command, an on-disk preflight
uses directory metadata—not candidate contents—to reject any extra tracked, untracked, or
gitignored Terraform 1.13.5 `.tf`, `.tfvars`, `.tftest.hcl`, `.tfmock.hcl`, or
`.tfmock.json` candidate, including every reviewed JSON/load variant, and every symlink
or non-regular candidate.
It permits `.terraform/` only as an ignored, untracked real directory, checks that
boundary without traversing it, and never opens state, plan, secret, or rejected-extra
contents. `--terraform-test` validates Terraform's JSON event stream and requires the
exact single reviewed run and summary `1 passed, 0 failed, 0 errored, 0 skipped`; a green
zero-test command is rejected. Formatting, fresh initialization, and validation remain
separate gates.

Run `scripts/verify_ops_foundation.sh --static` before review and `--live` only after an
explicitly approved apply. Live mode requires
`OPS_FOUNDATION_REVIEWED_IAM_BINDINGS` and
`OPS_FOUNDATION_REVIEWED_STATE_BUCKET_BINDINGS`, each populated with exact JSON
scope/role/member records from reviewed live policy exports. Custom-role records include
the complete permission-set digest; conditional records include the condition digest.
Absence, extra records within an audited scope, or drift fails closed. Secret injection
and state recovery remain in
[`docs/runbooks/gcp-neon-foundation.md`](../../docs/runbooks/gcp-neon-foundation.md).
Bootstrap, normal delivery, and rollback are in
[`docs/runbooks/cloud-run-delivery.md`](../../docs/runbooks/cloud-run-delivery.md).
