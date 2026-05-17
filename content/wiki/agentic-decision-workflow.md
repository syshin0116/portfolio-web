---
title: "Agentic decision workflow"
type: pattern
tags:
  - ai
  - agent
  - github
  - adr
  - decision-making
  - knowledge-base
  - automation
  - workflow
  - human-in-the-loop
summary: "Agentic decision workflow는 에이전트가 GitHub issue, 리서치, ADR, PR, 리뷰 댓글 반영을 자동화하되 사람은 되돌리기 어려운 선택과 trade-off 승인에 집중하는 운영 패턴이다. 실행 기록은 issue/PR에, 결정의 이유는 append-only ADR에, 현재 팀 지식은 mutable wiki에 남기는 3층 구조가 핵심이다."
sources:
  - https://www.atlassian.com/blog/atlassian-engineering/hula-blog-autodev-paper-human-in-the-loop-software-development-agents
  - https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/
  - https://arxiv.org/html/2602.17084
  - https://aws.amazon.com/blogs/architecture/master-architecture-decision-records-adrs-best-practices-for-effective-decision-making/
  - https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record
  - https://adr.github.io/
  - https://code.claude.com/docs/en/github-actions
  - https://developers.openai.com/cookbook/examples/codex/build_code_review_with_codex_sdk
created: 2026-05-17
updated: 2026-05-17
author: wiki-curator
draft: false
---

## Key claims

- Agentic workflow의 목표는 사람을 완전히 제거하는 것이 아니라, 사람이 **decision making**에 집중하도록 반복 작업과 정리를 agent에게 넘기는 것이다.
- Atlassian HULA 사례는 좋은 기준점을 준다. agent는 work item을 읽고 plan, code, PR까지 만들지만, engineer가 plan approval, code review, feedback을 담당한다.[^hula]
- GitHub Agentic Workflows는 agent 자동화를 GitHub Actions 안에 넣고 permissions, logs, review boundary를 repository owner가 통제하는 방향을 제안한다. Continuous AI는 CI/CD를 대체하지 않고, 주관적·반복적 repository 작업을 보완한다.[^github-agentic]
- AI coding agent PR 연구는 구조화된 PR 설명이 reviewer 부담을 줄일 수 있음을 보여준다. 하지만 설명만으로 merge가 보장되지는 않고, 코드 품질과 검증이 여전히 중심이다.[^pr-communication]
- ADR은 decision의 context, alternatives, rationale, consequences를 남기는 lightweight 기록이다. Microsoft는 ADR을 append-only log로 다루고, 결정이 바뀌면 기존 record를 수정하지 말고 새 record가 supersede하도록 권장한다.[^ms-adr]
- 따라서 실행 기록은 issue/PR, 결정 이유는 ADR, 최신 팀 지식은 wiki에 둔다. 이 3층을 분리해야 agent가 과거 논쟁을 반복하지 않고 현재 지식과 과거 이유를 함께 읽을 수 있다.

## Operating loop

| 단계 | Agent output | Human gate | Persisted artifact |
|---|---|---|---|
| Repo scan | repo map, constraints, existing conventions | 목표·제약 확인 | wiki draft 또는 project brief |
| Research | related docs, examples, risks | 빠진 맥락 피드백 | research note, source links |
| Decision brief | options, trade-offs, recommendation | **choose / defer / reject** | proposed ADR |
| Planning | issues, acceptance criteria, task breakdown | scope 승인 | GitHub issues |
| Implementation | branch, commits, PR, tests | 큰 방향 변경 승인 | PR |
| Review | Claude/Codex cross-review, CI interpretation | merge decision | PR comments |
| Knowledge update | wiki synthesis, ADR links, supersession notes | accepted decision 확인 | wiki page + ADR log |

## Decision gate rule

Low-risk operations should run automatically. High-impact decisions should stop at a human gate.

| Ask a human | Let the agent continue |
|---|---|
| Public API change | Test addition |
| DB schema or migration | Formatting, lint, small refactor |
| Security, auth, privacy, cost impact | PR summary and changelog draft |
| Architecture direction with hard rollback | Documentation update |
| ADR status change to accepted | ADR draft in proposed state |
| Product or UX trade-off | Evidence collection and comparison |

This balances performance better than both extremes. Full manual review wastes time on mechanical work; full autonomy hides irreversible decisions inside generated commits.

## Multi-model split

- Hermes Agent or a similar orchestrator should own state, tools, repository actions, memory, and delivery.
- GPT-5.5/Codex is a good default implementer and structured reviewer, especially when JSON output or exact file/line findings are needed.[^codex-review]
- Claude Opus / Claude Code is useful as a design critic and reviewer, especially for architecture, UX, and instruction-following heavy review. Claude Code GitHub Actions can respond to mentions in issues and PRs, while an automation workflow can run without a mention when configured with a prompt.[^claude-actions]
- A second model should not be treated as an oracle. It is a different failure mode. Hermes should still verify diff, tests, CI, and final PR state.

## Wiki and ADR division

[[llm-wiki]] and ADR solve different memory problems.

| Layer | Time model | Answers | Mutation rule |
|---|---|---|---|
| Issue / PR | event log | What happened during execution? | append comments and commits |
| ADR | append-only decision log | Why did the team choose this? | never rewrite accepted decisions; supersede |
| Wiki | mutable semantic layer | What is true now? | update as current understanding changes |

A team decision becomes durable knowledge only when the wiki page includes:

1. decision summary,
2. context and constraints,
3. options considered,
4. decision drivers,
5. consequences and revisit conditions,
6. links to ADR, issue, PR, and relevant code paths.

Without context and rejected alternatives, the wiki becomes a conclusion dump. Future agents can repeat the same debate because they cannot see why previous options were rejected.

## Connections

- [[llm-wiki]] - mutable semantic knowledge layer that should absorb accepted decision outcomes.
- [[github-actions-gcp-cicd]] - deterministic CI/CD remains the verification layer; agentic workflows should complement it, not replace it.
- [[vibe-coding]] - agentic development is safer when vibe coding is constrained by decision gates, tests, and ADRs.
- [[second-brain-rag]] - decision-aware wiki pages make retrieval more useful because they encode rationale, not just facts.

## Footnotes

[^hula]: [Atlassian, "Human in the Loop Software Development Agents"](https://www.atlassian.com/blog/atlassian-engineering/hula-blog-autodev-paper-human-in-the-loop-software-development-agents)
[^github-agentic]: [GitHub Blog, "Automate repository tasks with GitHub Agentic Workflows"](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/)
[^pr-communication]: [Watanabe et al., "How AI Coding Agents Communicate"](https://arxiv.org/html/2602.17084)
[^ms-adr]: [Microsoft, "Maintain an architecture decision record"](https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record)
[^codex-review]: [OpenAI Cookbook, "Build Code Review with the Codex SDK"](https://developers.openai.com/cookbook/examples/codex/build_code_review_with_codex_sdk)
[^claude-actions]: [Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions)
