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
- separate GitHub OIDC providers for `Preview` pull requests and `Production` main;
- environment-specific act-as and secret-access bindings;
- five disjoint empty Secret Manager resources per runtime environment.

The existing `agent-runtime` resource remains the production runtime. Deployers have no
project-wide Cloud Run role and no Artifact Registry writer role. A later deployment PR
must create the Cloud Run services and a separate image-builder identity before granting
service-scoped deployment permissions.

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

Use an ephemeral access token or Application Default Credentials. Never pass a service
account JSON key to Terraform. Do not run `apply` from CI.

Credential-free CI uses:

```sh
terraform init -backend=false -input=false -lockfile=readonly
terraform validate
terraform test
```

Run `scripts/verify_ops_foundation.sh --static` before review and `--live` only after an
explicitly approved apply. Secret injection, state recovery, Neon cutover, and deployment
are documented in
[`docs/runbooks/gcp-neon-foundation.md`](../../docs/runbooks/gcp-neon-foundation.md).
