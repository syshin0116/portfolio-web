---
title: "Native Aegra Cloud Run delivery runbook"
description: >
  Bootstrap, deploy, smoke, and roll back the immutable native Aegra image through
  GitHub OIDC, environment-scoped identities, and Cloud Run revision traffic.
when_to_read: >
  Before applying the Cloud Run Terraform, enabling agent delivery, changing its
  workflows or image, rotating agent database credentials, or rolling back a revision.
tags: [operations, gcp, cloud-run, aegra, github-actions, neon, rollback]
status: stable
updated: "2026-07-28"
owners: ["@syshin0116"]
refs:
  - ../../infra/gcp/README.md
  - gcp-neon-foundation.md
  - ../adr/0004-adopt-aegra.md
  - ../adr/0007-postgres-on-neon-split-projects.md
  - ../plans/rag-restack.md
template: spec
---

# Native Aegra Cloud Run delivery runbook

The web application remains on Vercel. This delivery surface owns only the native Aegra
agent, its two Cloud Run services, and their one-shot jobs.

No checked-in file creates a Neon project, adds a Secret Manager payload, changes a GitHub
environment, or applies Terraform. Those are explicit external gates. Keep the repository
variable `AGENT_CLOUD_RUN_ENABLED` absent or set to `false` until every bootstrap check
below passes; both trigger workflows then report a deliberate skip instead of attempting a
half-configured deployment.

## Reviewed topology

| Environment | Service | Migration job | Runtime-grant job | Runtime identity | Migration identity |
|---|---|---|---|---|---|
| Agent Preview | `agent-preview` | `agent-preview-migrate` | `agent-preview-grants` | `agent-preview-runtime` | `agent-preview-migrator` |
| Agent Production | `agent` | `agent-migrate` | `agent-grants` | `agent-runtime` | `agent-prod-migrator` |

`agent-image-builder` is the only user-managed identity with repository-scoped
`roles/artifactregistry.writer`. The Google-managed Cloud Run service agent is the only
explicit repository reader. Each deployer has `roles/run.developer` only on its own
service and two jobs, plus `actAs` only on that environment's runtime and migration
identities. No deployer can read Secret Manager payloads or write images.

The services intentionally allow unauthenticated Cloud Run invocation because browsers at
the Vercel site must reach them. Aegra's outer bearer-token middleware remains the
application authorization boundary: the delivery gate proves `/live` and `/ready` are
public while an unauthenticated APv2 `run.start` returns 401.

Both services are fixed to one instance and one Uvicorn worker. This is a correctness
constraint, not a cost optimization: Aegra 0.9.24's same-thread mutation guard is
process-local.

## GitHub configuration

Create two GitHub deployment environments in addition to the existing Vercel `Preview`
and `Production` environments:

| Environment | Branch policy | Reviewer |
|---|---|---|
| `Agent Preview` | no branch restriction | none |
| `Agent Production` | branch `main` only | `syshin0116`, self-review allowed |

Set these environment variables with the exact Terraform outputs:

```text
GCP_WORKLOAD_IDENTITY_PROVIDER
GCP_BUILDER_SERVICE_ACCOUNT
GCP_DEPLOYER_SERVICE_ACCOUNT
```

The builder value is identical in both environments. Provider and deployer values are
environment-specific. The reusable workflow validates the exact reviewed project,
provider, and builder addresses before requesting an OIDC token.

Set this environment secret in both environments:

```text
AGENT_SMOKE_BEARER_TOKEN
```

It must be a short-lived owner bearer token accepted by `agent.auth`; it is never printed.
Rotate or replace it before expiry. Do not store `AGENT_AUTH_SECRET`, a database URL, or a
service-account JSON key in GitHub.

The WIF providers require the exact caller workflow (`preview-agent.yml` or
`deploy-agent.yml`) and the exact called reusable workflow (`agent-delivery.yml`) at the
same ref. Preview additionally accepts only the `pull_request` event. Production accepts
only `push` or explicitly approved `workflow_dispatch` at `refs/heads/main`.

## Secret Manager payloads

The foundation's five runtime secrets per environment remain unchanged. Add one separate
migration URL secret per environment:

```text
agent-preview-migration-database-url
agent-migration-database-url
```

Runtime services and the grant-probe jobs receive only the least-privileged direct Neon
runtime URL. Migration jobs receive only their elevated direct migration URL. Neither URL
may contain a Neon `-pooler` hostname. Add values out of band as described in the
[foundation runbook](gcp-neon-foundation.md); Terraform owns resource metadata and IAM,
not secret versions.

Before rollout, prove on real Neon that the runtime role can perform Aegra's idempotent
checkpointer/store setup and DML but cannot create another schema, create a role, or hold
`rolsuper`, `rolcreaterole`, `rolcreatedb`, or `rolreplication`. The
`agent.neon_grant_probe` Cloud Run job makes that proof executable on every deployment.

## One-time bootstrap

Cloud Run needs an existing digest to create the initial revision, while the GitHub builder
identity does not exist until Terraform is applied. Resolve that cycle once with an owner
ADC session—never a JSON key:

1. Confirm or create the split Neon projects/branches and real grant shapes. Do not copy
   the disposable legacy agent data.
2. Add all Secret Manager versions without printing payloads.
3. Build the reviewed commit locally for Linux x86-64 with the checked-in Dockerfile and
   push it to `us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent`.
4. Record the registry-resolved `.../agent@sha256:<64 hex>` value. A tag alone is not an
   accepted Terraform input.
5. Run every credential-free verifier, then make and review a remote Terraform plan:

   ```sh
   scripts/verify_ops_foundation.sh --static
   scripts/verify_ops_foundation.sh --terraform-fmt
   scripts/verify_ops_foundation.sh --terraform-init
   scripts/verify_ops_foundation.sh --terraform-validate
   scripts/verify_ops_foundation.sh --terraform-test
   terraform -chdir=infra/gcp plan \
     -var 'agent_bootstrap_image=us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:REPLACE'
   ```

6. Reject any persistent-resource replacement/destroy, project-wide deployer role, secret
   payload, or mutable image reference. Apply only after owner approval.
7. Run `scripts/verify_ops_foundation.sh --live` with the exact reviewed IAM inventories.
8. Create/configure the two GitHub environments and run the local plus live repository
   governance verifiers.
9. Manually dispatch a preview-capable PR, confirm migration → grant probe → no-traffic
   revision → health/auth → traffic → two-turn APv2 smoke, and inspect logs without secret
   values.
10. Only then set the repository variable `AGENT_CLOUD_RUN_ENABLED=true`.

The bootstrap image is an input only for initial resource creation. Terraform ignores
subsequent image and traffic changes; the delivery workflow owns those two revision
fields. Every other service/job field remains Terraform-owned and drift-visible.

## Normal delivery

`preview-agent.yml` deploys same-repository, non-Dependabot pull requests to
`agent-preview`. Fork pull requests never receive the deployment job. `deploy-agent.yml`
deploys reviewed `main` pushes to `agent`.

The reusable workflow:

1. authenticates the dedicated builder through WIF;
2. reuses an existing immutable `git-<SHA>` image or builds it once with provenance and
   SBOM attestations;
3. passes only the registry-resolved digest to the deployer;
4. updates and executes the same-digest migration job;
5. updates and executes the same-digest real-Neon grant/denial job;
6. creates a no-traffic service revision and checks the exact digest, one-instance, and
   one-worker contract;
7. health-checks the tagged no-traffic revision and proves APv2 rejects missing auth;
8. moves 100% traffic to that revision;
9. runs the two-turn APv2 protocol smoke against the service URL.

Any failure after revision creation restores 100% traffic to the previously ready
revision. The workflow never rebuilds to roll back.

## Manual rollback

Dispatch **Deploy agent** on `main`, select `rollback`, and provide an exact existing
`agent-...` revision name. The `Agent Production` environment approval is still required.
The workflow shifts traffic, runs health/auth and the two-turn APv2 smoke, and restores the
previous revision automatically if that smoke fails.

Database migrations must remain compatible with one previous application revision.
Rollback changes traffic only; it does not reverse a Neon migration or secret version.
Restore a prior secret version only as a separately reviewed operation.

## External gates that remain

- Terraform has not been applied by this repository change.
- No GCP or Neon resource/payload has been created or changed.
- The real Neon runtime and migration credentials still need grant/denial acceptance.
- GitHub `Agent Preview` / `Agent Production` environments, their variables, reviewer
  policy, and smoke tokens still need external configuration.
- The first provider-backed Korean two-turn APv2 smoke is still a live deployment gate.
