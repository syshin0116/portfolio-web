# syshin0116.dev — AI Working Guide

This file is auto-loaded by Claude Code (and Anthropic Routines) when operating in this repo.

## What this repo is

Personal blog at https://syshin0116.vercel.app, currently used as a **testbed for the LLM Wiki pattern**:

- Existing blog posts under `content/AI/`, `content/Dev/`, `content/Tools/`, etc. are treated as **immutable source material**.
- A curated knowledge layer is built at `content/wiki/`.
- Operations on `content/wiki/` are owned by the **`wiki-curator`** skill.

## Repo layout

```
content/
├── AI/, Dev/, Events/, Others/, Projects/, Study/, Tools/   ← source posts (immutable)
└── wiki/                                                     ← curated knowledge layer (LLM owned)
agent/    Python RAG chatbot (do not modify)
web/      Next.js + Nuartz frontend (do not modify)
skills/
└── wiki-curator/   Skill that owns content/wiki/ — see skills/wiki-curator/SKILL.md
```

## Hard rules

1. **Never modify source posts.** Every `.md` outside `content/wiki/` is read-only. If something looks wrong in a post, surface it to the user — do not edit.
2. **Never modify `web/`, `agent/`, or build/deploy config.** That's human territory.
3. **All `content/wiki/` work goes through the `wiki-curator` skill.** See [skills/wiki-curator/SKILL.md](./skills/wiki-curator/SKILL.md). Don't write to `content/wiki/` ad-hoc.
4. **Never commit build artifacts.** `.next/`, `node_modules/`, `.generated/`, etc.

## Routine entry point

When invoked by an Anthropic Routine, the prompt should:

1. Read `skills/wiki-curator/SKILL.md` for the operation menu.
2. Pick the operation it was asked to run (`ingest`, `lint`, `reflect`).
3. Read the matching sub-doc (`ingest.md`, `lint.md`, `reflect.md`) and `conventions.md` before doing any work.
4. Execute on a `claude/wiki-<op>-<timestamp>` branch and open a PR to `main`.

The Routine's prompt itself stays short — the skill files carry the contract.

## Quick reference for skill operations

| Operation | Reads | Writes | Mode |
|-----------|-------|--------|------|
| `ingest` | source posts | `content/wiki/` (new + surgical updates) | additive |
| `lint` | `content/wiki/` | report only (no file changes) | read-only |
| `reflect` | `content/wiki/` | `content/wiki/` (links only, no new pages) | conservative |

For details, frontmatter, tag vocabulary, and link rules, see `skills/wiki-curator/conventions.md`.
