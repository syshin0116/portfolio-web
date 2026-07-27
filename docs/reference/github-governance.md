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
commit SHA and that exactly one workflow job emits each stable required check:

- `ci/check`
- `protocol/compat`
- `wiki/verify`

The live verifier additionally reads GitHub rulesets, Actions policy, and
environment branch policies. It performs GET requests only:

```bash
python scripts/verify_repository_governance.py
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

`CODEOWNERS` still routes responsibility and makes ownership visible. It is
deliberately advisory: a required self-review cannot be satisfied safely in a
solo repository. Add mandatory review only after another maintainer has write
access and can cover the owner.

Do not give a permanent bypass that permits red checks to merge. The owner can
edit the ruleset if GitHub itself has an outage; that is an emergency settings
change, not a normal merge path.

## Full-SHA Actions policy

First run the local verifier. Then enable **Settings → Actions → General →
Require actions to be pinned to a full-length commit SHA**. Dependabot's
`github-actions` updater will continue moving the immutable SHA and its readable
version comment together.

GitHub documents a full commit SHA as the only immutable release reference for
an action. The checked-in verifier fails before an unpinned action can make this
external setting disable a workflow.

## Deployment environment branches

Keep the existing Vercel environments explicit:

| Environment | Deployment branches |
|---|---|
| `Preview` | No restriction, so every contributor branch can receive a preview |
| `Production` | Selected branches and tags: branch `main` only |

The verifier compares these settings exactly, including the `main` branch
policy. When separate Cloud Run `preview` and `production` environments are
introduced, add them to the checked-in policy in the same PR as their workflows;
do not silently reuse the Vercel environments.

Environment reviewers are independent of branch policy. A solo-owner approval
is safe only when `prevent_self_review` is disabled. Keep routine previews free
of mandatory review; reserve an owner approval for a deliberately gated
production or spend-bearing preview.

## Dependabot and scheduled audit

Dependabot groups routine minor/patch updates per ecosystem and cools new
releases before opening version-update PRs. Security updates are not grouped or
cooled, so one vulnerable package is not held behind unrelated upgrades.
Aegra, Deep Agents, LangChain, LangGraph, QuickJS, assistant-ui, the web
LangChain packages, Next.js, and Auth.js remain isolated bump PRs because each
one can change an agent, protocol, framework, or authentication compatibility
surface.

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
3. Create the main ruleset with zero required approvals.
4. Enable the repository full-SHA Actions policy.
5. Confirm `Preview` and `Production` branch policies.
6. Run `python scripts/verify_repository_governance.py --live`; it must pass.
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
