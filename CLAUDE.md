# syshin0116.dev - AI Working Guide

Auto-loaded by Claude Code (and Anthropic Routines) when operating in this repo.

## What this repo is

Personal blog for syshin0116 at https://syshin0116.dev (also deployed at https://syshin0116.vercel.app), currently used as a **testbed for the LLM Wiki pattern**:

- Existing posts under `content/AI/`, `content/Dev/`, `content/Tools/`, etc. are **immutable source material**.
- A curated knowledge layer is built at `content/wiki/`.

## Repo layout

```
content/
├── AI/, Dev/, Events/, Others/, Projects/, Study/, Tools/   ← source posts (immutable)
└── wiki/                                                     ← curated knowledge layer
agent/    Python RAG chatbot (do not modify)
web/      Next.js + Nuartz frontend (do not modify)
.claude/skills/   skill definitions (auto-discovered) - see each SKILL.md frontmatter for when to use
```

## Hard rules

1. **Never modify source posts.** Every `.md` outside `content/wiki/` is read-only. If something looks wrong in a post, surface it to the user - do not edit.
2. **Never modify `web/`, `agent/`, or build/deploy config.** That's human territory.
3. **All `content/wiki/` work goes through skills.** Don't write to `content/wiki/` ad-hoc - use the relevant skill, which carries the full contract.
4. **Never commit build artifacts.** `.next/`, `node_modules/`, `.generated/`, etc.
5. **Propose a decision record when a decision lands.** When a structural or hard-to-reverse choice is made (content taxonomy, wiki contract, frontmatter schema, skill contract, a new dependency, deploy surface), propose a one-line entry for [`DECISIONS.md`](DECISIONS.md) yourself - do not wait to be asked. Promote an entry to a full ADR in `docs/adr/` only once it proves durable. Before changing an established pattern, read `DECISIONS.md` first.
