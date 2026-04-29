# wiki-curator routine: dispatcher prompt

This is the prompt currently saved in the Anthropic Routine `blog-to-wiki-experiment`. The routine has a single saved prompt; this dispatcher handles every fire (push event, cron, manual) by inspecting state and choosing the right operation.

When updating the routine, copy the block below verbatim.

---

```
Use the wiki-curator skill (.claude/skills/wiki-curator/).

Look at the current state of the wiki and recent activity (`git log`, `content/wiki/log.md`). Decide what operation, if any, would be useful right now.

Each operation file has its own "When to run" guidance - read those before deciding. Trust your judgment based on the actual state, not arbitrary thresholds.

Common cases:
- New source posts since the last routine commit → ingest those specific files (use the "since-last-routine" mode in ingest.md, not "recent N").
- No source changes but accumulated drift, stale lint, or pending consolidation → consider lint or migrate per their guidance.
- Nothing meaningful to do → exit cleanly without committing.

Run the verify gate at the end. See SKILL.md → Verify gate for retry behavior.

Don't mix operations in one session - pick the most useful single one.
```

---

## Why dispatch in the prompt rather than 4 separate routines?

A single routine + judgment-based dispatch keeps the moving parts in `.claude/skills/wiki-curator/` rather than fragmented across the Anthropic Routines UI. Updating skill behavior happens in one place; we don't have to remember which routine has which trigger.

Trade-off: the LLM has to make a judgment call each fire. We accept some non-determinism in exchange for not encoding magic thresholds (e.g., "lint every 7 days") that we'd just be guessing at anyway.

## Updating the routine

After editing this file, copy the prompt block above into the routine via `RemoteTrigger` `update`, or by editing the routine on https://claude.ai/code/routines.
