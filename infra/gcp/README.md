# GCP foundation

This directory declares the keyless GCP foundation for the syshin0116.dev agent. It
intentionally does not declare a Cloud Run service, deployment workflow, Dockerfile,
secret payload, secret version, or Neon credential.

## Managed resources

- required Google APIs;
- one versioned, public-access-blocked GCS Terraform backend;
- one regional Docker Artifact Registry repository with immutable tags;
- distinct production runtime, preview runtime, preview deployer, and production deployer
  service accounts;
- separate GitHub OIDC providers for `Preview` pull requests and `Production` pushes to
  `main`;
- environment-specific act-as and secret-access bindings;
- five disjoint empty Secret Manager resources per runtime environment.

The existing `agent-runtime` resource remains the production runtime. Deployers have no
project-wide Cloud Run role and no Artifact Registry writer role. A later deployment PR
must create the Cloud Run services and a separate image-builder identity before granting
service-scoped deployment permissions. It must also grant repository-scoped
Artifact Registry reader access to the exact Cloud Run image-pull principal.

IAM member resources are deliberately additive: changing them to authoritative
role-level bindings without a reviewed live plan could remove unrelated or
Google-managed members. The post-apply live verifier is the acceptance gate. It reads
project, ancestor, repository, state-bucket, service-account, and secret policies and
resolves every predefined or custom role before checking sensitive permissions. Public
members fail; group, domain, principal-set, other sensitive principals, and every direct
state-bucket member must match explicit newline-separated allowlists copied from a reviewed
live inventory. The verifier also rejects extra direct members for the managed roles and
direct project or repository roles on the four workload identities. Before builder and
Cloud Run image-pull identities exist, it requires repository-level reader and writer
roles to be empty. An unreadable policy or role and any other failure require a separate
reviewed IAM remediation; they are never ignored or overwritten blindly.

The production OIDC provider is currently pinned to the repository and owner numeric IDs,
the `push` event, `refs/heads/main`, and the `Production` environment. There is no
production deployment workflow yet, so a `job_workflow_ref` condition would be fictional.
The deployment PR must add that condition after the exact workflow path exists.

The existing `github` pool deliberately retains exactly the enabled `github-preview` and
`github-production` providers. Splitting environments into separate pools requires a
reviewed state/import and federation migration plan; it is not an in-place hardening edit.
GitHub environment reviewers, self-review, and the canonical Production branch set
`{main}` live only in `.github/repository-governance.json`. When that manifest and
`scripts/verify_repository_governance.py` are present, the live foundation verifier
delegates to `verify_repository_governance.py --live` instead of duplicating the rules.

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

Routine operator commands:

```sh
terraform init
terraform plan
```

Terraform is pinned to `1.13.5` in both configuration and `.terraform-version`. Every
remote plan is mandatory review material. Do not apply until the operator has confirmed
that the plan contains only the intended imports, additions, metadata changes, and IAM
member removals; any resource replacement or persistent-resource destroy is a blocker.

Use an ephemeral access token or Application Default Credentials. Never pass a service
account JSON key to Terraform. Do not run `apply` from CI.

Credential-free CI uses:

```sh
terraform init -backend=false -input=false -lockfile=readonly
terraform validate
terraform test
```

Run `scripts/verify_ops_foundation.sh --static` before review and `--live` only after an
explicitly approved apply. Live mode requires
`OPS_FOUNDATION_ALLOWED_SENSITIVE_MEMBERS` and
`OPS_FOUNDATION_STATE_BUCKET_ALLOWED_MEMBERS`, each populated with exact newline-separated
members from reviewed live policy exports; absence or drift fails closed. Secret injection,
state recovery, Neon cutover, and deployment are documented in
[`docs/runbooks/gcp-neon-foundation.md`](../../docs/runbooks/gcp-neon-foundation.md).
