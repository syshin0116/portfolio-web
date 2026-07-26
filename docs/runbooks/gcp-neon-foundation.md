---
title: "GCP and Neon foundation runbook"
description: >
  Inventory, secret injection, cutover, verification, and rollback procedures for the
  keyless GCP deployment foundation and split Neon projects.
when_to_read: >
  Before changing GCP IAM or Workload Identity Federation, injecting production secrets,
  connecting Vercel or Cloud Run to Neon, or deleting the Singapore database.
tags: [operations, gcp, neon, workload-identity, cloud-run, secrets]
status: active
date: "2026-07-26"
owners: ["@syshin0116"]
---

# GCP and Neon foundation runbook

## Resource map

### GCP

- project: `festive-ally-503605-v7` (`syshin0116-prod`);
- region: `us-east4`;
- Artifact Registry repository: `agent`;
- runtime service account: `agent-runtime`;
- preview deployer: `agent-preview-deployer`;
- production deployer: `agent-prod-deployer`;
- WIF pool: `github`;
- providers: `github-preview`, `github-production`.

No service-account JSON key is permitted. GitHub obtains short-lived credentials through
OIDC. Production requires the immutable GitHub repository and owner numeric IDs,
`refs/heads/main`, and the `Production` environment.

### Neon

| Purpose | Project | Region | Default branch | Migration policy |
|---|---|---|---|---|
| Web and authentication | `syshin0116-web-prod` | `aws-us-east-1` | `production` | Greenfield Neon Auth |
| Agent runtime | `syshin0116-agent-prod` | `aws-us-east-1` | `production` | Empty Aegra schema |
| Rollback source | `syshin0116-dev` | `aws-ap-southeast-1` | `main` | Preserve unchanged |

The agent must use its direct endpoint, never a `-pooler` endpoint. The web and agent
projects have separate credentials and failure domains.

## Secret resources

Only these resource names are managed as infrastructure:

- `agent-database-url`;
- `agent-auth-secret`;
- `anthropic-api-key`;
- `openai-api-key`;
- `langsmith-api-key`.

Terraform never manages secret versions. Inject each value out of band:

```sh
read -rs SECRET_VALUE
printf '%s' "$SECRET_VALUE" |
  gcloud secrets versions add SECRET_NAME \
    --project festive-ally-503605-v7 \
    --data-file=-
unset SECRET_VALUE
```

Do not place values in a command argument, shell history, GitHub variable, Terraform
variable, plan, state, issue, pull request, or log.

## Web cutover

The current web application uses Auth.js and the mixed Singapore database. Neon Auth is a
greenfield application change and must ship in a separate `web/` pull request after the
current authentication stack is ready.

1. Configure GitHub and Google OAuth in `syshin0116-web-prod`.
2. Configure the callback URLs for Vercel Preview without changing Production.
3. Apply the Neon Auth SDK change in a dedicated application PR.
4. Verify login, callback rejection, logout, session refresh, and a fresh browser session.
5. Switch only Vercel Preview to the new project.
6. After approval, switch Vercel Production independently.
7. Re-authenticate the sole owner; do not migrate the old Auth.js session.
8. Preserve `syshin0116-dev` as the rollback source.

Rollback restores the previous Vercel deployment and its previous environment-variable
binding. It does not copy new Neon Auth rows into the Singapore Auth.js tables.

## Agent cutover

The agent project starts empty. Do not copy the existing 25 test threads or legacy
checkpoint tables.

1. Obtain the direct `production` branch endpoint out of band.
2. Inject it as the first version of `agent-database-url`.
3. Run the Aegra schema migration from the reviewed application revision.
4. Record table names and migration revision only; never print the connection string.
5. Deploy an immutable image digest with the dedicated runtime service account.
6. Verify `/live`, `/ready`, owner auth, unauthenticated rejection, two-turn persistence,
   restart persistence, and exact AP v2 streaming.
7. Shift traffic only after smoke tests pass.

Rollback reassigns Cloud Run traffic to the previous healthy revision and restores the
previous secret version. Database migrations must remain compatible with one previous
application revision.

## Verification

```sh
scripts/verify_ops_foundation.sh
```

Before deployment, additionally verify that every runtime secret has one enabled version
and that no service account has a user-managed key. Do not display secret payloads.

## Deletion policy

Never delete `syshin0116-dev` as part of a deploy or migration. A future deletion requires:

1. a fresh logical backup;
2. recorded backup checksum and restore rehearsal;
3. successful web and agent operation through at least two production releases;
4. explicit owner approval in a separate change.
