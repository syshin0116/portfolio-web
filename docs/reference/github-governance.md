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
commit SHA and that exactly one workflow job emits each stable required check.
It parses YAML syntax trees with the same PyYAML dependency already locked by
the agent; duplicate keys, anchors, aliases, merge keys, directives, explicit
tags, and multiple documents fail closed. Flow mappings and quoted or explicit
`uses` keys cannot bypass the full-SHA walk. The walk covers nested workflow
files plus every `.github/actions/**/action.yml` or `action.yaml`, then follows
local `./` action and reusable-workflow edges recursively. A local target that
escapes the repository, is missing or ambiguous, or forms a cycle fails:

- `ci/check`
- `protocol/compat`
- `wiki/verify`

Each required check is bound to GitHub Actions integration ID `15368`, not just
its mutable display context. A read-only check-runs query against
`main@d058ebc` confirmed all three contexts came from app slug
`github-actions`, ID `15368`. The live verifier rejects missing IDs, a context
bound to another integration, duplicate bindings, and undocumented contexts.

The live verifier additionally reads GitHub rulesets, Actions policy, and
environment branch and protection policies. It performs GET requests only.
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

In **Settings → Rules → Rulesets**, create one active branch ruleset for the
default branch (`main`) with:

1. Restrict deletions.
2. Require a pull request before merging.
3. Require **zero** approving reviews.
4. Leave Code Owner review and approval of the last push disabled.
5. Require `ci/check`, `protocol/compat`, and `wiki/verify`, with the branch
   required to be up to date.
6. Block force pushes.
7. Leave the bypass list empty.

`CODEOWNERS` still routes responsibility and makes ownership visible. It is
deliberately advisory: a required self-review cannot be satisfied safely in a
solo repository. Add mandatory review only after another maintainer has write
access and can cover the owner.

Keep this contract in one active ruleset. Disabled rulesets that target `main`
and rules distributed over multiple active rulesets fail verification, as does
any bypass actor. The owner can edit the ruleset if GitHub itself has an
outage; that is an emergency settings change, not a normal merge path. Required
checks are compared exactly. The complete rule-type allowlist is also exact:
`deletion`, `non_fast_forward`, `pull_request`, and
`required_status_checks`. An additional rule such as `required_deployments`, a
missing rule, or a duplicate type is policy drift. GitHub-supplied metadata is
ignored; the rule type and the parameters whose semantics this contract owns
are compared.

## Full-SHA Actions policy

First run the local verifier. Then enable **Settings → Actions → General →
Require actions to be pinned to a full-length commit SHA**. Dependabot's
`github-actions` updater will continue moving the immutable SHA and its readable
version comment together.

Repository Actions must also remain enabled and the allowed-actions policy must
remain `all`; the live verifier compares all three settings exactly.

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

Dependabot groups routine minor/patch updates per ecosystem and cools new
releases before opening version-update PRs. Security updates are not grouped or
cooled, so one vulnerable package is not held behind unrelated upgrades.
Aegra (`aegra-*`), Deep Agents, LangChain (`langchain` and `langchain-*`),
LangGraph (`langgraph` and `langgraph-*`), LangSmith, assistant-ui,
`@langchain/*`, Next.js, NextAuth, and `@auth/*` remain isolated bump PRs because
each can change an agent, protocol, framework, or authentication compatibility
surface. The local verifier compares these groups with the machine-readable
manifest exactly.

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
3. Create the single main ruleset with zero required approvals and no bypass.
4. Enable repository Actions and its full-SHA policy.
5. Remove the required reviewer from routine `Preview`; retain the existing
   `syshin0116` reviewer on `Production` with self-review allowed, and confirm
   both branch policies.
6. Run the `--live` command from this runbook; it must pass.
7. Manually dispatch **Dependency audit** once and triage any reported
   vulnerabilities in separate PRs.

The settings in steps 3–5 live outside Git. A green local verifier does not mean
they have been applied.

## Official references

- [GitHub rules available in rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [GitHub Actions full-SHA enforcement](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)
- [GitHub deployment environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [GitHub deployment branch policy API](https://docs.github.com/en/rest/deployments/branch-policies)
- [Dependabot options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)
