---
title: "GitHub governance verification runbook"
description: >
  The checked-in and external settings that keep parallel contributor and agent
  work behind the same pull-request, CI, action-pinning, and deployment gates.
when_to_read: >
  Before changing GitHub rulesets, Actions policy, Dependabot behavior, required
  check names, CODEOWNERS, deployment environment branch policies, or the scheduled
  dependency and upstream-version audit.
tags: [github, governance, ci, dependabot, runbook]
status: stable
updated: "2026-08-15"
owners: ["@syshin0116"]
refs:
  - ../../.github/repository-governance.json
  - ../../.github/workflows/ci.yml
  - ../../.github/workflows/protocol-compat.yml
  - ../../.github/workflows/vercel-production.yml
  - ../../.github/workflows/wiki-verify.yml
  - ../runbooks/upstream-version-audit.md
  - ../adr/0003-agent-code-changes-via-pr.md
template: spec
---

# GitHub governance verification runbook

## Contract

The repository stores the expected external state in
[`repository-governance.json`](../../.github/repository-governance.json). Local
verification checks that every external action is pinned to a full 40-character
commit SHA and that each stable required check has one exact executable
emitter. GitHub recognizes workflow YAML only directly under
`.github/workflows/`; YAML in a subdirectory is rejected rather than counted as
a workflow or required-check emitter.

The verifier parses YAML syntax trees with the same PyYAML dependency already
locked by the agent; duplicate keys, anchors, aliases, merge keys, directives,
explicit tags, and multiple documents fail closed. It follows only executable
`uses` positions:

- `jobs.<id>.uses` must target a reusable workflow.
- `jobs.<id>.steps[*].uses` must target an action.
- A repository action must have exactly one `action.yml` or `action.yaml` with
  `runs.using: composite`; its `runs.steps[*].uses` edges are followed
  recursively.
- A local reusable workflow must be a top-level workflow file with
  `on.workflow_call`.
- An action/workflow inversion, an escaping, missing, ambiguous, or cyclic
  local target, or an external reference without a full commit SHA fails.

Keys named `uses` in ordinary input, environment, or metadata mappings are not
invocations and are ignored. This position-aware parsing applies equally to
flow mappings and quoted or explicit keys.

The manifest binds each stable context to one exact top-level workflow and job:

- `ci/check`
- `protocol/compat`
- `wiki/verify`

Each emitter workflow must have exactly `pull_request`, `push` restricted to
`main`, `merge_group` restricted to `checks_requested`, and
`workflow_dispatch`. Workflow-level `paths` filters, schedule-only emission,
extra triggers, or a renamed/missing emitter fail. The emitter's complete
`needs` graph must exist without cycles; jobs with dependencies use
`if: always()`, and no job in that graph may have another skipping condition.
Neither those jobs nor their steps may set `continue-on-error`, including
`false`: presence would make a future expression or edit an easy false-green
escape. The same ban is followed recursively through every reachable local
composite action and reusable workflow, including nested local calls.
This keeps a required check from remaining permanently pending after an
upstream failure or merge-queue run.

The Application CI `changes` bootstrap job has an exact 10-minute ceiling for
frozen toolchain setup, the repository governance/unit suite, and component
classification. The verifier targets only `jobs.changes.timeout-minutes`; it
does not introduce a workflow-wide timeout baseline.

The `ci/agent` job also has an immutable-resolution contract. It runs exactly
one executable `uv lock --check` before its exact
`uv sync --frozen --package syshin0116-dev-agent --all-extras --dev` install,
and every project-bound
`uv run` places `--frozen` immediately after `uv run`. Without that flag,
`uv run` may resolve a stale `pyproject.toml`/`uv.lock` pair after the frozen
sync and silently replace the environment that CI was meant to verify. The
local verifier binds this contract to the AST-selected `agent` job and its
root-workspace execution, tokenizes executable `run` scalars with shell
comments removed, and binds every run step, including the fail-closed and
unaffected-component reports, to an exact name, condition, command-token, and
order inventory. The four frozen commands and their complete scopes, Ruff
check, Ruff format check, index build/audit, and pytest restricted to
`agent/tests`, are exact within that
inventory, so variable executables, wrapper commands, deletions, renames, and
extra direct or indirect runs require a deliberate contract change. The final
reviewed step is the one intentional exception to the ordinary run-step key
set: it uses `shell: bash` to build the actual root `Dockerfile` for
`linux/amd64`, inspect the resulting platform, run that image's migration
entrypoint against the job's PostgreSQL service, and boot the same image for
health and unauthenticated-boundary checks. No job or workflow
`defaults.run.working-directory` is allowed, because the root `pyproject.toml`,
root `uv.lock`, `agent/`, `eval/`, scripts, and Docker context are one reviewed
workspace contract. A comment, `echo`, or quoted command string therefore
cannot stand in for an executable gate.

The same exact job AST pins a PostgreSQL 17 service, database credentials, published test
port, `pg_isready` health check, and `AEGRA_POSTGRES_TEST_URL`. The ordinary pytest command
therefore executes migration, checkpointer, real `/memories/` isolation, and pool-recreation
coverage instead of reporting a green job with that integration test skipped. The final
step reuses that database to run `python -m agent.migrate` inside the exact built image,
boots the image with startup migration, Redis dispatch, and background retries disabled,
waits for `/live` and `/ready`, and requires an unauthenticated AP v2 command to return
401. It always emits container logs and removes the container. It deliberately makes no
provider or model request; real Neon, provider, browser, and capability evidence remain
deployment gates.

That contract binds the complete `agent` job AST, not only its `run` strings.
The only job keys are the reviewed name, `always()` condition, `changes`
dependency, Ubuntu runner, 30-minute timeout, exact CI environment, exact PostgreSQL
service, and ordered steps. `defaults`, `container`, `strategy`, `environment`, a
self-hosted runner, any additional service, or any other extra or changed job key fails;
changing any field of the one reviewed PostgreSQL service also fails. All twelve steps
are exact and ordered: checkout is pinned to its
reviewed SHA with only `persist-credentials: false`; setup-python v7.0.0 is
pinned with Python 3.12; setup-uv v9.0.0 is pinned with uv 0.12.3, its reviewed
checksum, and the reviewed cache inputs; the eight ordinary run steps retain their exact
names, conditions, commands, and allowed keys; and the twelfth step builds, inspects,
migrates, boots, probes, logs, and removes the real delivery image.
Adding, deleting, moving, replacing, or changing an action or step, including a pinned or
local composite action, is a deliberate baseline change in the verifier and its mutation
tests.

The setup-python v7 major removes only the unused `pip-install` input from this
repository's surface. Every setup-uv invocation uses the same full-SHA v9.0.0 action,
explicit `version` and `checksum`, plus only its job's reviewed cache inputs. The root
`[tool.uv] required-version = "==0.12.3"` rejects a mismatched local binary, and the
agent Dockerfile binds the same version to its immutable uv image digest. The repository
verifier rejects a missing call, a new unreviewed call, or drift in any of those three
surfaces.

No job in the required-check emitter or its transitive `needs` graph may use
job-level `uses`, whether it calls a local or external reusable workflow.
GitHub can report the caller job successful when every called-workflow job is
skipped, so a reusable workflow is not a safe required-check boundary. The
verifier still descends into a referenced local workflow after reporting that
boundary violation, preserving the recursive `continue-on-error` audit instead
of letting the first error mask a nested false-green path.

Each required check is bound to GitHub Actions integration ID `15368`, not just
its mutable display context. A read-only check-runs query against
`main@d058ebc` confirmed all three contexts came from app slug
`github-actions`, ID `15368`. The live verifier rejects missing IDs, a context
bound to another integration, duplicate bindings, and undocumented contexts.

The live verifier additionally reads GitHub rulesets, Actions policy, and
environment branch and protection policies. It checks that vulnerability
alerts return an empty HTTP 204, that `automated-security-fixes` returns exactly
`{"enabled": true, "paused": false}`, and that the admin-only repository
response independently reports
`security_and_analysis.dependabot_security_updates.status: enabled`. It also
requires the legacy `main` branch-protection endpoint to return the exact
unprotected-branch 404; rulesets are the only allowed main-protection surface.
It performs GET requests only and verifies that GitHub selected the API version
pinned in the manifest. An inaccessible endpoint, unexpected status/body,
missing admin-only security state, or API-version downgrade fails closed. It
reads the repository's enabled merge methods as well, so the pull-request rule
cannot require a method that the repository has disabled. The repository
response must also report the exact `full_name`
`syshin0116/syshin0116.dev` and `default_branch: main`; a rename, transfer, API
redirect, or default-branch change is explicit drift. `~DEFAULT_BRANCH` is
evaluated against that live default ref, not treated as an alias that always
matches the manifest's `refs/heads/main`.
Rulesets, environments, and branch policies request an explicit
`per_page=100&page=1`; any pagination `Link`, inconsistent `total_count`, or
second-page requirement fails closed:

```bash
uv run --frozen --package syshin0116-dev-agent \
  python scripts/verify_repository_governance.py
scripts/verify_ops_foundation.sh --governance-live
```

Run the local command before changing a workflow. Run `--live` after changing
repository settings and during a governance audit.

## Owner-safe main ruleset

In **Settings → Rules → Rulesets**, create one active branch ruleset named
`main` for the default branch with:

1. Restrict deletions.
2. Require a pull request before merging.
3. Require **zero** approving reviews.
4. Allow rebases only. Disable merge commits and squash merges in the
   repository settings because GitHub has no separate default merge-method
   setting.
5. Leave stale-review dismissal, Code Owner review, last-push approval, and
   required review-thread resolution disabled. Leave review-dismissal
   restrictions disabled and the beta required-reviewer list empty. GitHub's
   repository ruleset API omits `dismissal_restriction` from the returned
   parameter object when that optional restriction is disabled; the reviewed
   manifest therefore expects the field to be absent.
6. Require `ci/check`, `protocol/compat`, and `wiki/verify`, with the branch
   required to be up to date and `do_not_enforce_on_create: false`.
7. Block force pushes.
8. Leave the bypass list empty.

`CODEOWNERS` still routes responsibility and makes ownership visible. It is
deliberately advisory: a required self-review cannot be satisfied safely in a
solo repository. Add mandatory review only after another maintainer has write
access and can cover the owner.

Keep this contract in one active ruleset. Disabled rulesets that target `main`
and rules distributed over multiple active rulesets fail verification, as does
any bypass actor. Remove legacy branch protection from `main`; overlapping a
branch-protection rule with the ruleset is policy drift even if both look
equivalent in the UI. The owner can edit the ruleset if GitHub itself has an
outage; that is an emergency settings change, not a normal merge path.
The ruleset name, repository source, `branch` target, active enforcement, and
the exact `~DEFAULT_BRANCH` include with no excludes are manifest-owned. A
broader `~ALL` include is rejected even though it also matches `main`.

Required checks and the full pull-request and status-check parameter objects
are compared exactly with JSON types preserved. This includes disabled/default
values returned by GitHub, the empty reviewer collection, allowed merge
methods, strict status checks, and `do_not_enforce_on_create: false`. The
API-normalized omission of a disabled `dismissal_restriction` is part of that
exact response contract; if GitHub starts returning it or another semantic
parameter, verification fails closed until it is reviewed. The complete
rule-type allowlist is also exact: `deletion`, `non_fast_forward`,
`pull_request`, and `required_status_checks`. An additional rule such as
`required_deployments`, a missing rule, or a duplicate type is policy drift.
GitHub-supplied ruleset metadata such as IDs, links, and timestamps is ignored;
owned identity, target, conditions, rule types, and parameter objects are not.

The verifier also contains a deliberately hardcoded reviewed baseline for the
repository/API/main identities, required-check emitters, Actions object,
environment payloads, Dependabot configuration, and ruleset parameters. This
prevents changing the manifest and implementation under test together from
silently redefining the contract. An intentional evolution, such as adding a
Cloud Run `Staging` environment, updates the manifest, hardcoded baseline,
mutation tests, and this runbook in the same PR.

## Full-SHA Actions policy

First run the local verifier. Then enable **Settings → Actions → General →
Require actions to be pinned to a full-length commit SHA**. Dependabot's
`github-actions` updater will continue moving the immutable SHA and its readable
version comment together.

Repository Actions must also remain enabled and the allowed-actions policy must
remain `all`; the live verifier compares the complete three-key response
exactly, including its key set.

GitHub documents a full commit SHA as the only immutable release reference for
an action. The checked-in verifier fails before an unpinned action can make this
external setting disable a workflow.

## Deployment environment branches

Keep the Vercel and agent delivery environments explicit and disjoint:

| Environment | Deployment branches |
|---|---|
| `Preview` | No branch restriction and no required reviewer, so every contributor branch can receive a routine preview |
| `Production` | Selected branches and tags: branch `main` only; required reviewer `syshin0116`, with self-review allowed |
| `Agent Preview` | No branch restriction; required reviewer `syshin0116`, with self-review allowed; in-repository pull requests only are enforced by the workflow and WIF condition |
| `Agent Production` | Selected branches and tags: branch `main` only; required reviewer `syshin0116`, with self-review allowed |

The verifier compares these settings exactly, including branch policy,
protection-rule types, reviewer identities, `prevent_self_review`, and admin
bypass. Admin bypass is disabled for `Agent Preview`, `Agent Production`, and
`Evaluation Publication`; the Vercel environments retain their existing settings. The
environment-name set is also exact, so an undeclared `Staging` or other environment
cannot silently become a deployment surface. Vercel `Preview` remains review-free for
routine contributor previews. Both agent environments keep the owner gate and explicitly
permit self-review so a solo owner cannot deadlock. Creating or reconciling these settings
is an external rollout item; the checked-in contract does not claim it has already been
applied.

[`web/vercel.json`](../../web/vercel.json) uses Vercel's official static schema
and deliberately has no checked-in top-level `git` object at all. The linked
Vercel Git Integration therefore retains its default behavior: a `main` push is
eligible for Production deployment and contributor branches remain eligible
for Preview. The local governance verifier rejects even an empty `git` object,
any branch-level deployment override, a different schema, duplicate JSON keys,
and non-standard JSON.

The canonical public domain is the verified Production project domain
`syshin0116.vercel.app`, not a one-off deployment alias. Keep Vercel Production's
**Auto-assign Custom Production Domains** and **Automatically expose System
Environment Variables** settings enabled. The first setting makes each successful
`main` Production deployment current on the public domain; the second supplies the
runtime deployment, project, repository, branch, and SHA identity used by the
read-only observer.

[`vercel-production.yml`](../../.github/workflows/vercel-production.yml) observes every
`main` push and every successful Vercel `Production` deployment status. It gives GitHub
no Vercel token and no write permission. Instead it polls the canonical domain's
no-store [`/api/deployment-revision`](../../web/app/api/deployment-revision/route.ts)
response until the runtime Git SHA matches the exact GitHub deployment SHA. For a
Vercel deployment-status event it also requires the runtime's unique `VERCEL_URL` to
equal that status's `environment_url`, so an older redeployment of the same commit
cannot satisfy the check. The endpoint returns 503 unless the Vercel project ID,
GitHub repository, `main` ref, Production environment, system-variable exposure, and
runtime identifiers all match the reviewed contract. This detects a staged or stale
public domain without storing a Vercel secret in GitHub.

The checked-in contract still cannot mutate or fully inventory Vercel dashboard
settings. A red or missing observer run is an incident to investigate; it is not
permission for CI to promote, alias, redeploy, or change environment variables.

The image builder runs first through `agent-image-build.yml` without any GitHub
environment, environment secret, or deployment credential. It can write only to the
target's isolated registry. The one subsequent `agent-release.yml` job references the
exact target environment. Production delivery needs one approval before the deployer
identity or traffic update is available; a restored Preview delivery would use the same
boundary through `Agent Preview`.
This two-workflow shape keeps registry-writer and deployer credentials on different
runners without claiming that one environment review yields two independent approvals.
The sole active `github-production` WIF provider explicitly maps numeric repository and
owner IDs plus the four phase-specific delivery roles, and its condition references only
those mapped attributes. The legacy `github-preview` provider is managed disabled as
described in the [Cloud Run delivery runbook](../runbooks/cloud-run-delivery.md).

The Cloud Run preview caller requires both `AGENT_CLOUD_RUN_ENABLED=true` and
`AGENT_CLOUD_RUN_PREVIEW_ENABLED=true`. Only the first repository variable exists.
Terraform retains Preview identities, registries, and empty secret containers, but creates
no Preview Cloud Run service or jobs. The caller is therefore dormant until a reviewed
change restores those resources and enables the second flag. Its builder resolves the PR
head before approval, but the release workflow does not revalidate that head or required
CI after `Agent Preview` approval. That check must land before this becomes a supported
deployment path.

After the reviewer releases `agent-release.yml`, Production rechecks current `main` and
the exact successful `ci/check`, `protocol/compat`, and `wiki/verify` check runs before
GCP authentication. The release deploys the immutable digest to a no-traffic revision,
verifies `/live`, `/ready`, and an unauthenticated APv2 `401`, then promotes 100% traffic.
It does not execute migration, grant-probe, or maintenance jobs, run an authenticated
provider smoke, or automate rollback. Caller-only preview/production concurrency never
cancels an approved release.

Environment inventory is also exact. `Evaluation Publication` contains no secrets or
variables. `Agent Preview` and `Agent Production` also contain zero secrets and zero
variables. Vercel environment secrets are outside this repository-governance inventory.

Environment reviewers are independent of branch policy. A solo-owner approval
is usable only when `prevent_self_review` is disabled. Keep routine Vercel previews free
of mandatory review; retain owner approval for Vercel Production and Agent Production.
Anonymous visitor access remains authorized only through reviewed Agent Production
releases under ADR-0006. The retained `Agent Preview` environment is not a current
deployment validation surface and is never the public guest path.

## Dependabot and scheduled audit

Dependabot version 2 has exactly four update identities: Bun at `/web`, an npm
security-only bridge at `/web`, uv at `/`, and GitHub Actions at `/`. The
native Bun and uv ecosystems are required so version updates change
`web/bun.lock` and the root `uv.lock` with their manifests instead of opening
predictably red manifest-only PRs. GitHub does not yet support Dependabot
security updates for Bun, so the npm bridge sets
`open-pull-requests-limit: 0`: npm version PRs are disabled while npm security
PRs remain enabled. Such a security PR does not own `bun.lock`; regenerate and
verify that lock in a dedicated worktree before merge.

The identities run monthly in `Asia/Seoul`, staggered at 04:00, 04:10, 04:20,
and 04:40. Bun, uv, and Actions allow 10, eight, and one version PRs
respectively; the npm bridge allows zero version PRs. Bun and uv use the
reviewed 7-day default, 14-day major, 7-day minor, and 3-day patch cooldowns;
Actions uses the reviewed 7-day default cooldown. Routine updates of every
SemVer level are grouped for Bun, uv, and Actions; the npm bridge opens no
version PRs. These groups apply only to version updates, so security updates
remain outside the routine rollups.
Aegra (`aegra-*`), Deep Agents, LangChain (`langchain` and `langchain-*`),
the OpenAI Python SDK (`openai`), the direct QuickJS Rust binding
(`quickjs-rs`), LangGraph (`langgraph` and `langgraph-*`), LangSmith, assistant-ui,
`@langchain/*`, Next.js, NextAuth, `@auth/*`, `@neondatabase/*`, TypeScript,
`lucide-react`, React/React DOM and their type packages, and NumPy remain
isolated bump PRs. The Bun limit equals its 10 possible group PRs, so all nine
focused compatibility updates can coexist without starving the routine monthly
rollup. React and icon updates require focused build/browser evidence, Neon
updates require the Auth.js adapter type contract, and TypeScript updates
must be validated against the pinned ESLint/Bun/Next toolchain. NumPy is part of the
persisted BM25 artifact provenance contract; the other exclusions can change an
agent, protocol, framework, or authentication compatibility surface. The local
verifier compares version, update identity set, schedule, open-PR limit, full
cooldown object, and every group exactly; missing, duplicate, changed, or extra
updates/groups fail.

The version-update schedule in `dependabot.yml` does not itself enable GitHub's
repository security features. The external contract separately requires
vulnerability alerts and unpaused Dependabot security updates. The security
update state is checked through both the dedicated
`automated-security-fixes` endpoint and the admin-only repository security
summary so one stale or incomplete surface cannot appear green by itself. A
missing summary fails closed rather than assuming the caller lacks permission.
Vulnerability alerts and automated security updates are enabled. The live
verifier confirms both the dedicated endpoint and the repository security
summary, so disabling or pausing either feature is external policy drift.

[`dependency-audit.yml`](../../.github/workflows/dependency-audit.yml) runs
weekly and manually. It verifies the web and root Python lockfiles, runs the web
policy below, exports only the agent workspace member, audits that exact Python
resolution with pinned `pip-audit`, compares the reviewed framework pins with
stable official upstream releases, and reports
one stable `dependency/audit` result. It is an alerting workflow, not a required
main check; a discovered vulnerability should create a focused fix PR rather
than making every unrelated PR permanently pending.

The `dependency/upstream-versions` job invokes the dependency-free
[`upstream_version_audit.py`](../../scripts/upstream_version_audit.py) with Python 3.12.
Its job AST, the final aggregation job AST, and the complete audit-script SHA-256 are
hardcoded in the local governance verifier so removing a target, removing the audit from
`needs`, changing its source command, or masking its result is deliberate reviewed drift.
The script reads exact manifest and lock pins but never changes them. It emits
deterministic JSON and a GitHub step summary; exit `1`
means a newer stable release exists, while transport, redirect, response-size, schema,
pin, and canonical-repository failures exit `2`. Both fail the scheduled/manual run.
The full target, stable-release, triage, and extension contract is in the
[upstream version audit runbook](../runbooks/upstream-version-audit.md).

Its agent job uses the repository-wide uv 0.12.3 and setup-uv v9.0.0 pins, including
the reviewed official archive SHA-256 rather than allowing an unverified download. Local
uv commands validate the version gate and lock/export semantics but cannot emulate the
GitHub Action's Node runtime, release download, checksum, and cache path. After this action
rollup is pushed, manually dispatch **Dependency audit** and require its agent job to
install uv 0.12.3 and pass before considering that scheduled path verified.

The web policy is executable in
[`audit-dependencies.ts`](../../web/scripts/audit-dependencies.ts) and fails
closed in three stages:

1. `bun audit --prod --audit-level=high --json` must return an empty object.
   Production high and critical findings have no exception.
2. The complete high/critical audit must contain exactly
   `CVE-2026-14257` / `GHSA-mh99-v99m-4gvg`, and the lock must show every
   affected `brace-expansion@1.1.16` path beneath the root
   `eslint-config-next` dev dependency through the exact current
   `eslint-plugin-import`, `eslint-plugin-jsx-a11y`, and
   `eslint-plugin-react` chain. Any extra advisory, production move, package
   version, or path drift fails.
3. Only after those checks, a second audit ignoring the reviewed GHSA must
   return zero. Bun 1.3.10 does not honor the advisory's CVE alias, despite the
   CLI help calling the option a CVE ID, and also does not apply `--ignore`
   with JSON output; the policy therefore validates the CVE/GHSA pair itself
   and uses the GHSA identifier for the final non-JSON command.

The exception expires after **2026-08-31**. Review it sooner when any of the
three ESLint plugins stops depending on Minimatch 3, when Brace Expansion
backports the fix to its CommonJS 1.x API, or when Bun fixes CVE alias handling.
Do not force Brace Expansion 5 into Minimatch 3: version 5 returns an object
with an `expand` member while Minimatch 3 calls the required module itself as a
function, so that override makes lint fail. Do not add another ignore,
`continue-on-error`, or a severity downgrade.

Two temporary top-level Bun overrides cover production parents that have not
yet released compatible ranges: PostCSS 8.5.23 replaces Next 16.2.12's exact
8.4.31, and Sharp 0.35.3 replaces its `^0.34.5` optional dependency. Both
resolve on every lock path and support the repository's Node floor; remove each
override as soon as stable Next selects the patched line itself.

The remediation lock is based on the pre-remediation lock and uses
package-specific Bun 1.3.10 updates for the affected parent closures. Nine of
the 60 direct resolutions change; the other 51 are pinned to their reviewed
base resolutions by the executable policy. That guard deliberately includes
Radix, Framer Motion, Pagefind, React Icons, Tailwind, and
`use-stick-to-bottom`, so a future security update cannot silently turn into a
repository-wide dependency refresh. Do not replace this with a clean
re-resolution or add temporary transitive packages to `package.json`.

## Rollout order

1. Before merging the change that restores or enables Vercel Git
   auto-deployment, prove the current `main` revision's Production Neon schema
   and Vercel runtime/OAuth environment prerequisites independently. Apply the
   same pre-merge gate to every later revision that changes or depends on the
   Auth/Neon contract; automatic delivery is not a database migration gate.
2. After each merge, require `vercel/production` to observe the exact merge SHA on
   `syshin0116.vercel.app`; a Vercel deployment-status run must also match its unique
   deployment URL. Confirm the PR source branch received its routine Preview. Do not
   create an extra `main` or Preview probe push. Investigate any missing, duplicate,
   staged, or revision-mismatched deployment before another production merge.
3. Confirm each required check has reported successfully on `main`.
4. Confirm the ruleset list is empty and legacy `main` branch protection
   returns the exact unprotected `404`. Create the single main ruleset as
   `disabled`, read it back, and compare the complete normalized contract.
   Delete it on any mismatch; otherwise activate that same ruleset ID and
   verify it again. It must have zero required approvals and no bypass.
5. Enable repository Actions and its full-SHA policy.
6. Enable vulnerability alerts and Dependabot security updates, then confirm
   that security updates are not paused.
7. Remove the required reviewer from routine Vercel `Preview`; retain the existing
   `syshin0116` reviewer on Vercel `Production` with self-review allowed, and confirm
   both branch policies.
8. Create or reconcile `Agent Preview` and `Agent Production` with required reviewer
   `syshin0116`, self-review allowed, admin bypass disabled, the branch policies above,
   zero secrets, and zero variables.
9. Run the `--live` command from this runbook; it must pass.
10. Manually dispatch **Dependency audit** once. Require the web vulnerability, Python
   vulnerability, and upstream-version jobs to pass; triage each finding in a focused PR.

The observations and settings in steps 1–8 live outside Git. A green local
verifier does not mean they have been applied.

## Official references

- [GitHub rules available in rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [GitHub Actions full-SHA enforcement](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)
- [GitHub deployment environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [GitHub deployment branch policy API](https://docs.github.com/en/rest/deployments/branch-policies)
- [Dependabot options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)
- [Dependabot supported ecosystems and lockfiles](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories)
- [Dependabot security-only ecosystem configuration](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/configure-security-updates#overriding-the-default-behavior-with-a-configuration-file)
- [GitHub vulnerability-alert status API](https://docs.github.com/en/rest/repos/repos#check-if-vulnerability-alerts-are-enabled-for-a-repository)
- [GitHub Dependabot security-update status API](https://docs.github.com/en/rest/repos/repos#check-if-automated-security-fixes-are-enabled-for-a-repository)
- [GitHub repository security-and-analysis response](https://docs.github.com/en/rest/repos/repos#get-a-repository)
- [Bun dependency audit](https://bun.com/docs/pm/cli/audit)
- [Brace Expansion advisory GHSA-mh99-v99m-4gvg](https://github.com/advisories/GHSA-mh99-v99m-4gvg)
