# syshin0116.dev - AI Working Guide

Auto-loaded by Claude Code (and Anthropic Routines) when operating in this repo.

## What this repo is

Personal blog for syshin0116 at https://syshin0116.dev (also deployed at https://syshin0116.vercel.app), used as a testbed for two things:

1. **The LLM Wiki pattern.**
   - Existing posts under `content/AI/`, `content/Dev/`, `content/Tools/`, etc. are **immutable source material**.
   - A curated knowledge layer is built at `content/wiki/`.
2. **RAG retrieval-method evaluation.** `agent/` exists to implement and compare many
   retrieval methods; the blog is the corpus because the owner knows it best and it is
   already preprocessed. **Answering blog questions well is a side effect, not the goal.**
   Read [`docs/adr/0008`](docs/adr/0008-chatbot-is-a-rag-evaluation-testbed.md) **before
   proposing any simplification of the retrieval layer** - arguments from "the corpus is
   only 336 files" are correct for a product and backwards here. The method catalogue is
   [`docs/reference/retrieval-methods.md`](docs/reference/retrieval-methods.md).

## Repo layout

```
content/
├── AI/, Dev/, Events/, Others/, Projects/, Study/, Tools/   ← source posts (immutable)
└── wiki/                                                     ← curated knowledge layer
agent/    Python RAG agent - the retrieval-method testbed (branch + PR, see rule 2)
web/      Next.js + Nuartz frontend, incl. the chat UI (branch + PR, see rule 2)
.claude/skills/   skill definitions (auto-discovered) - see each SKILL.md frontmatter for when to use
```

## Hard rules

1. **Never modify source posts.** Every `.md` outside `content/wiki/` is read-only. If something looks wrong in a post, surface it to the user - do not edit.
2. **Changes to `web/`, `agent/`, and build/deploy config go through a branch and a PR** - never a direct commit to `main`, and never merge on red CI. See [`docs/adr/0003`](docs/adr/0003-agent-code-changes-via-pr.md).
3. **All `content/wiki/` work goes through skills.** Don't write to `content/wiki/` ad-hoc - use the relevant skill, which carries the full contract.
4. **Never commit build artifacts.** `.next/`, `node_modules/`, `.generated/`, etc.
5. **Propose a decision record when a decision lands.** When a structural or hard-to-reverse choice is made (content taxonomy, wiki contract, frontmatter schema, skill contract, a new dependency, deploy surface), propose a one-line entry for [`DECISIONS.md`](DECISIONS.md) yourself - do not wait to be asked. Promote an entry to a full ADR in `docs/adr/` only once it proves durable. Before changing an established pattern, read `DECISIONS.md` first.
