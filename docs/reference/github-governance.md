---
title: "GitHub governance verification runbook"
description: >
  The checked-in and external settings that keep parallel contributor and agent
  work behind the same pull-request, CI, action-pinning, and deployment gates.
when_to_read: >
  Before changing GitHub rulesets, Actions policy, Dependabot behavior, required
  check names, CODEOWNERS, or deployment environment branch policies.
tags: [github, governance, ci, dependabot, runbook]
status: stable
updated: "2026-07-27"
owners: ["@syshin0116"]
refs:
  - ../../.github/repository-governance.json
  - ../../.github/workflows/ci.yml
  - ../../.github/workflows/protocol-compat.yml
  - ../../.github/workflows/wiki-verify.yml
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

The `ci/agent` job also has an immutable-resolution contract. It runs exactly
one executable `uv lock --check` before its exact
`uv sync --frozen --package syshin0116-dev-agent --all-extras --dev` install,
and every project-bound
`uv run` places `--frozen` immediately after `uv run`. Without that flag,
`uv run` may resolve a stale `pyproject.toml`/`uv.lock` pair after the frozen
sync and silently replace the environment that CI was meant to verify. The
local verifier binds this contract to the AST-selected `agent` job and its
`agent` working directory, tokenizes executable `run` scalars with shell
comments removed, and binds every run step—including the fail-closed and
unaffected-component reports—to an exact name, condition, command-token, and
order inventory. The four frozen commands and their complete scopes—Ruff
check, Ruff format check, index build/audit, and pytest—are exact within that
inventory, so variable executables, wrapper commands, deletions, renames, and
extra direct or indirect runs require a deliberate contract change. Run-step
execution metadata is limited to `name`, `if`, and `run`; step `shell`, `env`,
or working-directory overrides fail, as do workflow-level inherited
defaults/environment and changes to the job's exact environment or
agent-only working directory. A comment, `echo`, or quoted command string
therefore cannot stand in for an executable gate.

The same exact job AST pins a PostgreSQL 17 service, database credentials, published test
port, `pg_isready` health check, and `AEGRA_POSTGRES_TEST_URL`. The ordinary pytest command
therefore executes migration, checkpointer, real `/memories/` isolation, and pool-recreation
coverage instead of reporting a green job with that integration test skipped.

That contract binds the complete `agent` job AST, not only its `run` strings.
The only job keys are the reviewed name, `always()` condition, `changes`
dependency, Ubuntu runner, 20-minute timeout, agent working directory, exact CI
environment, exact PostgreSQL service, and ordered steps. `container`, `strategy`,
`environment`, a self-hosted runner, any additional service, or any other extra or
changed job key fails; changing any field of the one reviewed PostgreSQL service also
fails. All eleven steps are exact and ordered: checkout is pinned to its
reviewed SHA with only `persist-credentials: false`; setup-python v7.0.0 is
pinned with Python 3.12; setup-uv v8.3.2 is pinned with only the reviewed cache
inputs; and the eight run steps retain their exact names, conditions, commands,
and allowed keys. Adding, deleting, moving, replacing, or changing an action,
including a pinned or local composite action, is a deliberate baseline change
in the verifier and its mutation tests.

The setup-python v7 major removes only the unused `pip-install` input from this
repository's surface. setup-uv v8 removes the deprecated custom
`manifest-file` format and mutable major/minor tags; this repository uses
neither, keeps full-SHA pins, and uses inputs still declared by v8.3.2:
`version`, `checksum`, `enable-cache`, and `cache-dependency-glob`.

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
uv run --no-project --with pyyaml==6.0.3 \
  python scripts/verify_repository_governance.py
uv run --no-project --with pyyaml==6.0.3 \
  python scripts/verify_repository_governance.py --live
```

Run the local command before changing a workflow. Run `--live` after changing
repository settings and during a governance audit.

## Owner-safe main ruleset

In **Settings → Rules → Rulesets**, create one active branch ruleset named
`main` for the default branch with:

1. Restrict deletions.
2. Require a pull request before merging.
3. Require **zero** approving reviews.
4. Allow merge commits, squash merges, and rebases, matching the repository
   settings.
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
silently redefining the contract. An intentional evolution—such as adding a
Cloud Run `Staging` environment—updates the manifest, hardcoded baseline,
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

Keep the existing Vercel environments explicit:

| Environment | Deployment branches |
|---|---|
| `Preview` | No branch restriction and no required reviewer, so every contributor branch can receive a routine preview |
| `Production` | Selected branches and tags: branch `main` only; required reviewer `syshin0116`, with self-review allowed |

The verifier compares these settings exactly, including branch policy,
protection-rule types, reviewer identities, `prevent_self_review`, and admin
bypass. The environment-name set is also exact, so an undeclared `Staging` or
other environment cannot silently become a deployment surface. At the time
this contract was recorded, both environments had the owner as a required
reviewer with `prevent_self_review: false`. The desired routine state removes
that reviewer from `Preview`; `Production` keeps the existing owner gate and
explicitly permits self-review so a solo owner cannot deadlock. The current
Preview mismatch is an external rollout item, not something this PR mutates.

When separate Cloud Run `preview` and `production` environments are introduced,
add them to the checked-in policy in the same PR as their workflows; do not
silently reuse the Vercel environments.

Environment reviewers are independent of branch policy. A solo-owner approval
is safe only when `prevent_self_review` is disabled. Keep routine previews free
of mandatory review; reserve an owner approval for a deliberately gated
production or spend-bearing preview.

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

The identities run weekly on Monday in `Asia/Seoul`, staggered at 04:00, 04:10,
04:20, and 04:40. Bun, uv, and Actions allow three version PRs; the npm bridge
allows zero version PRs. Bun and uv use the reviewed 7-day default, 14-day
major, 7-day minor, and 3-day patch cooldowns; Actions uses the reviewed 7-day
default cooldown. Routine minor/patch updates are grouped for Bun, uv, and
Actions; the npm bridge opens no version PRs. Security updates are not grouped
or cooled, so one vulnerable package is not held behind unrelated upgrades.
Aegra (`aegra-*`), Deep Agents, LangChain (`langchain` and `langchain-*`),
LangGraph (`langgraph` and `langgraph-*`), LangSmith, assistant-ui,
`@langchain/*`, Next.js, NextAuth, `@auth/*`, React/React DOM and their type
packages, and NumPy remain isolated bump PRs. React updates require focused
build/browser evidence, while NumPy is part of the persisted BM25 artifact
provenance contract; the other exclusions can change an agent, protocol,
framework, or authentication compatibility surface. The local verifier compares
version, update identity set, schedule, open-PR limit, full cooldown object, and
every group exactly; missing, duplicate, changed, or extra updates/groups fail.

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
resolution with pinned `pip-audit`, and reports
one stable `dependency/audit` result. It is an alerting workflow, not a required
main check; a discovered vulnerability should create a focused fix PR rather
than making every unrelated PR permanently pending.

Its agent job deliberately pins uv 0.11.29 under setup-uv v8.3.2. That action's
built-in checksum table ends at uv 0.11.28, so the workflow also pins the
official Linux x64 0.11.29 archive SHA-256 rather than allowing an unverified
download. Local uv commands validate the lock/export semantics but cannot
emulate the GitHub Action's Node runtime, release download, checksum, and cache
path. After this action rollup is pushed, manually dispatch **Dependency
audit** and require its agent job to install uv 0.11.29 and pass before
considering that scheduled path verified.

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

1. Merge the repository-side governance PR after the existing three required
   checks pass.
2. Confirm each required check has reported successfully on `main`.
3. Confirm the ruleset list is empty and legacy `main` branch protection
   returns the exact unprotected `404`. Create the single main ruleset as
   `disabled`, read it back, and compare the complete normalized contract.
   Delete it on any mismatch; otherwise activate that same ruleset ID and
   verify it again. It must have zero required approvals and no bypass.
4. Enable repository Actions and its full-SHA policy.
5. Enable vulnerability alerts and Dependabot security updates, then confirm
   that security updates are not paused.
6. Remove the required reviewer from routine `Preview`; retain the existing
   `syshin0116` reviewer on `Production` with self-review allowed, and confirm
   both branch policies.
7. Run the `--live` command from this runbook; it must pass.
8. Manually dispatch **Dependency audit** once and triage any reported
   vulnerabilities in separate PRs.

The settings in steps 3–6 live outside Git. A green local verifier does not mean
they have been applied.

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
