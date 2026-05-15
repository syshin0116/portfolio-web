# wiki-curator: ingest

Convert source posts into wiki pages. Read [SKILL.md](./SKILL.md) and [conventions.md](./conventions.md) first.

## Anti-patterns specific to ingest

- **Forced cross-links.** Zero `[[wikilinks]]` is valid. Don't pad to look thorough.
- **Chat-style preamble.** Wiki pages don't open with "Here's a summary…".
- **Body `## Summary` section.** summary lives in frontmatter only.
- **Folder placement.** Always write to `content/wiki/<slug>.md` at root. migrate handles folders.
- **Full rewrites.** Surgical edits only. >30% body change → escalate.

## Inputs

This operation takes one of:

- **Explicit list** - caller specifies source paths (e.g., "ingest content/AI/2026-04-19-LLM-Text-to-SQL.md")
- **Recent N** - caller specifies a count (e.g., "ingest the 5 most recent posts")
- **Since-last-routine** - no explicit list, no count → process posts changed since the last `routine:` commit

### Resolving "recent N"

```bash
find content -name '*.md' \
  -not -path 'content/wiki/*' \
  -not -name 'Untitled.md' \
  -exec stat -f '%m %N' {} \; 2>/dev/null \
  | sort -rn | head -N | awk '{$1=""; print substr($0,2)}'
```

(macOS `stat`. On Linux replace with `stat -c '%Y %n'`.)

### Resolving "since last routine"

```bash
# Skip if the most recent commit is from the routine itself (loop guard)
if git log -1 --format=%s | grep -q "^routine:"; then
  echo "self-commit; nothing to do"
  exit 0
fi

LAST=$(git log --grep "^routine:" -1 --format=%H 2>/dev/null)
[ -z "$LAST" ] && LAST=$(git rev-list --max-parents=0 HEAD)

git diff --name-status "$LAST" HEAD -- 'content/*.md' \
  ':(exclude)content/wiki/' \
  ':(exclude)content/Untitled.md'
```

Treat `A` (added) and `M` (modified) as ingest targets. For `D` (deleted), see [deletion handling](#deletion-handling).

## Workflow per source

For each source in the input list:

### 1. Hash check (skip if unchanged)

```bash
NEW_HASH=$(git hash-object "$SOURCE")
EXISTING_HASH=$(grep -h "^$SOURCE " content/wiki/.hashes 2>/dev/null | awk '{print $2}')

if [ "$NEW_HASH" = "$EXISTING_HASH" ]; then
  echo "$SOURCE unchanged; skip"
  continue
fi
```

After successful processing, update `content/wiki/.hashes` (one `path<space>sha` per line).

### 2. Read the source

Read the entire file (frontmatter + body). Note its tags, title, date.

### 3. Identify candidate wiki targets

Look for existing wiki pages whose `sources:` already includes this path, OR whose topic clearly overlaps:

```bash
grep -rl "^  - $SOURCE" content/wiki/ 2>/dev/null
```

For each existing wiki page found, decide: **update** (same topic) or **none** (different angle).

### 4. Plan the page set

A single source typically touches **1 source-summary page + 0–N concept/tool pages**. Don't try to create one giant page that covers everything in the post.

Example: a post on "RAG with LangChain" might produce:
- New: `rag-langchain.md` (the post's main thesis)
- Update: `rag-pattern.md` (general RAG concept gets one more source)
- Update: `langchain.md` (tool page picks up one more usage example)

If the source is too thin or too narrow (e.g., a quick tip, a personal note), file a single short page or skip entirely. Log the skip reason to `log.md`.

### 5. Write each page

Follow the page structure in [conventions.md](./conventions.md#page-structure).

**File location: always `content/wiki/<slug>.md` at root.** Do not create folders. Don't try to fit pages into an existing folder structure either - let migrate consolidate later.

**Surgical updates only.** When updating an existing page:

- Use targeted Edit operations, not full rewrites.
- If you'd change >30% of the page → stop. Note in `log.md`: `skip | <page> needs human re-review (>30% rewrite)`.
- Bump `updated:` field.
- Append the new source path to `sources:` (don't replace).
- Update `summary:` if the new source materially changes the takeaway. Otherwise leave it.

**For new pages:**

- All mandatory frontmatter fields present, including `summary:` (1–3 sentences, single source - do not also write a `## Summary` section in body).
- Mandatory body sections: `## Key Claims`, `## Footnotes`. Other sections only if non-empty.
- Filename follows [conventions](./conventions.md#filename-rules).
- `created` = today (UTC), `updated` = today (UTC).

### 6. Update cross-links (forward only)

For each new/updated page, look for **existing wiki pages that should now link to it**:

```bash
# Find pages mentioning the same concept by title or tag
grep -rli "$NEW_PAGE_TITLE" content/wiki/
```

If you find a natural place to add a `[[wikilink]]`, add it. **Naturalness rule: only if the surrounding sentence already discusses the linked concept.** Never insert a "See also: [[X]]" appendix to satisfy a connection count.

### 7. Verify gate

See [SKILL.md → Verify gate](./SKILL.md#verify-gate) for the full check list and retry behavior.

```bash
bun .claude/skills/wiki-curator/scripts/verify.ts
```

If exit 1: read the per-check failures, fix in place, re-run. Up to 3 retries. After 3 failures → abort, do not commit.

## Filing back query answers (type: synthesis)

A second ingest input shape: a wiki query and its answer become a `type: synthesis` page.

### When this applies

A wiki query produced an answer that spans multiple existing pages — a cross-page conclusion that doesn't fit inside any single source post. The answer is worth keeping so future queries find it directly.

### Workflow

1. Identify which wiki pages the answer references — these become `sources:` (wiki paths, not source posts).
2. Title the page from the query intent, not the answer text.
3. Write the page following the standard structure (`## Key Claims`, `## Footnotes` mandatory), but:
   - `sources:` lists `content/wiki/*.md` paths
   - Add `synthesis_query:` frontmatter field with the verbatim query
   - Footnotes cite wiki pages (`[^1]: content/wiki/rag.md`)
4. Place at `content/wiki/<slug>.md` root. Folder decisions are `migrate`'s problem.
5. Run the verify gate — it accepts wiki-path sources and footnotes unchanged.

See [conventions.md](./conventions.md#type-synthesis-pages) for the full frontmatter contract.

### What this is NOT

- Not a Q&A archive of every wiki query. Synthesis pages are reserved for cross-page conclusions worth re-reading. One-off lookups don't need filing.
- Not a place for new claims. If the answer introduces an idea not in any cited wiki page, that idea belongs in a regular ingest from a real source — not a synthesis. Synthesis re-arranges existing wiki content; it doesn't extend it.

## Deletion handling

When a source is deleted (`D` in git diff):

1. Find every wiki page whose `sources:` includes the deleted path:
   ```bash
   grep -rl "^  - $DELETED_PATH" content/wiki/
   ```
2. Remove that source path from each `sources:` list.
3. If the page now has zero sources → move it to `content/wiki/.orphaned/<slug>.md` (do NOT delete; user can recover or confirm). Log: `orphan | <page> moved to .orphaned/`.

## index.md and log.md

After processing all sources:

- Rebuild `content/wiki/index.md` via the script (don't generate the table token-by-token):
  ```bash
  bun .claude/skills/wiki-curator/scripts/rebuild-index.ts
  ```
- Append one line to `content/wiki/log.md` (use `date -u +'%Y-%m-%d %H:%M UTC'` for the timestamp):
  ```
  ## [YYYY-MM-DD HH:MM UTC] ingest | N sources → A new, B updated, C skipped
  ```

## Commit & PR

Default workflow (Routine restricted to `claude/*` branches):

```bash
TS=$(date -u +%Y%m%d-%H%M%S)
BRANCH="claude/wiki-ingest-$TS"
git checkout -b "$BRANCH"
git add content/wiki/
git commit -m "routine: wiki ingest - N sources processed"
git push origin "$BRANCH"
gh pr create \
  --base main \
  --title "routine: wiki ingest - N pages affected" \
  --body "$(generate_pr_body)"
```

The PR body must include:

- Summary line (N sources → A new, B updated, C skipped)
- Table of new pages with their sources
- Table of updated pages with the source(s) added and a one-line diff hint
- Any skipped sources with the reason
- Any contradictions surfaced (if `## Contradictions` was added/extended)

