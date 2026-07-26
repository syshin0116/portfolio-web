# GCP foundation

This directory declares the keyless GCP foundation for the syshin0116.dev agent.
It intentionally does not declare a Cloud Run service, deployment workflow, Dockerfile,
secret payload, or Neon credential.

## Managed resources

- required Google APIs;
- one regional Docker Artifact Registry repository;
- separate runtime, preview deployer, and production deployer service accounts;
- separate GitHub OIDC providers for `Preview` and `Production`;
- additive least-privilege IAM bindings;
- empty Secret Manager resources.

The GitHub provider conditions use immutable numeric repository and owner IDs. Production
also requires `refs/heads/main` and the exact `Production` environment claim.

## State and adoption

The resources were bootstrapped through authenticated administrative commands. Import
blocks adopt them into Terraform on the first apply. Terraform state is deliberately
local and gitignored until a remote-state decision is recorded. No secret payload is
managed by Terraform, so no credential or connection string enters configuration or state.

```sh
cd infra/gcp
terraform init
terraform plan -out=foundation.tfplan
terraform apply foundation.tfplan
```

Use an ephemeral access token or Application Default Credentials. Never pass a service
account JSON key to Terraform.

Run `scripts/verify_ops_foundation.sh` after apply. Secret payload injection and deployment
remain separate, manual steps documented in
[`docs/runbooks/gcp-neon-foundation.md`](../../docs/runbooks/gcp-neon-foundation.md).
