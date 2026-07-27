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

Dependabot version 2 has exactly three update identities: Bun at `/web`, uv at
`/agent`, and GitHub Actions at `/`. The native ecosystems are required so
Dependabot updates `web/bun.lock` and `agent/uv.lock` with their manifests
instead of opening predictably red manifest-only PRs. They run weekly on Monday
in `Asia/Seoul`, staggered at 04:00, 04:20, and 04:40, with three open PRs per
ecosystem. Bun and uv use the reviewed 7-day default, 14-day major, 7-day
minor, and 3-day patch cooldowns; Actions uses the reviewed 7-day default
cooldown. Routine minor/patch updates are grouped per ecosystem. Security
updates are not grouped or cooled, so one vulnerable package is not held behind
unrelated upgrades.
Aegra (`aegra-*`), Deep Agents, LangChain (`langchain` and `langchain-*`),
LangGraph (`langgraph` and `langgraph-*`), LangSmith, assistant-ui,
`@langchain/*`, Next.js, NextAuth, and `@auth/*` remain isolated bump PRs because
each can change an agent, protocol, framework, or authentication compatibility
surface. The local verifier compares version, update identity set, schedule,
open-PR limit, full cooldown object, and every group exactly; missing,
duplicate, changed, or extra updates/groups fail.

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
weekly and manually. It verifies both lockfiles, runs Bun's high/critical audit,
audits the exact exported Python resolution with pinned `pip-audit`, and reports
one stable `dependency/audit` result. It is an alerting workflow, not a required
main check; a discovered vulnerability should create a focused fix PR rather
than making every unrelated PR permanently pending.

The introduction audit found existing dependency debt, so scheduled/manual runs
will remain red until focused remediation PRs clear it. Do not add an ignore
baseline, `continue-on-error`, or another false-green suppression.

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
- [GitHub vulnerability-alert status API](https://docs.github.com/en/rest/repos/repos#check-if-vulnerability-alerts-are-enabled-for-a-repository)
- [GitHub Dependabot security-update status API](https://docs.github.com/en/rest/repos/repos#check-if-automated-security-fixes-are-enabled-for-a-repository)
- [GitHub repository security-and-analysis response](https://docs.github.com/en/rest/repos/repos#get-a-repository)
