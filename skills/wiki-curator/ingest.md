# wiki-curator: ingest

Convert one or more source posts into wiki pages. Read [SKILL.md](./SKILL.md) and [conventions.md](./conventions.md) first.

## Inputs

This operation takes one of:

- **Explicit list** — caller specifies source paths (e.g., "ingest content/AI/2026-04-19-LLM-Text-to-SQL.md")
- **Recent N** — caller specifies a count (e.g., "ingest the 5 most recent posts")
- **Since-last-routine** — no explicit list, no count → process posts changed since the last `routine:` commit

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

**Surgical updates only.** When updating an existing page:

- Use targeted Edit operations, not full rewrites.
- If you'd change >30% of the page → stop. Note in `log.md`: `skip | <page> needs human re-review (>30% rewrite)`.
- Bump `updated:` field.
- Append the new source path to `sources:` (don't replace).
- Recompute `coverage:` from new `sources` length.

**For new pages:**

- All mandatory sections present (Summary, Key Claims).
- Filename follows [conventions](./conventions.md#filename-rules).
- `created` = today, `updated` = today.

### 6. Update cross-links (forward only)

For each new/updated page, look for **existing wiki pages that should now link to it**:

```bash
# Find pages mentioning the same concept by title or tag
grep -rli "$NEW_PAGE_TITLE" content/wiki/
```

If you find a natural place to add a `[[wikilink]]`, add it. **Naturalness rule: only if the surrounding sentence already discusses the linked concept.** Never insert a "See also: [[X]]" appendix to satisfy a connection count.

### 7. Verify all wikilinks resolve

```bash
# Extract all wikilinks
grep -roE '\[\[[^]]+\]\]' content/wiki/ \
  | sed 's/.*\[\[\([^]|#]*\).*/\1/' \
  | sort -u > /tmp/wikilinks.txt

# Compare to actual filenames
ls content/wiki/*.md \
  | xargs -n1 basename \
  | sed 's/\.md$//' \
  | sort -u > /tmp/wikipages.txt

comm -23 /tmp/wikilinks.txt /tmp/wikipages.txt  # broken links
```

If any broken links → fix or remove before commit.

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

- Rebuild `content/wiki/index.md` from scratch using current page set.
- Append one line to `content/wiki/log.md`:
  ```
  ## [YYYY-MM-DD HH:MM] ingest | N sources → A new, B updated, C skipped
  ```

## Commit & PR

Default workflow (Routine restricted to `claude/*` branches):

```bash
TS=$(date -u +%Y%m%d-%H%M%S)
BRANCH="claude/wiki-ingest-$TS"
git checkout -b "$BRANCH"
git add content/wiki/
git commit -m "routine: wiki ingest — N sources processed"
git push origin "$BRANCH"
gh pr create \
  --base main \
  --title "routine: wiki ingest — N pages affected" \
  --body "$(generate_pr_body)"
```

The PR body must include:

- Summary line (N sources → A new, B updated, C skipped)
- Table of new pages with their sources
- Table of updated pages with the source(s) added and a one-line diff hint
- Any skipped sources with the reason
- Any contradictions surfaced (if `## Contradictions` was added/extended)

## Anti-patterns to avoid

| Anti-pattern | Why it's bad | What to do instead |
|--------------|--------------|---------------------|
| Paraphrase the whole post into one wiki page | Loses fidelity, duplicates content, drift | Extract atomic claims, distribute across concept pages |
| Add `[[See also: X]]` lists | Forced links pollute the graph | Link only inline where the connection is natural |
| Rewrite a page to "improve" it | Self-corruption, loss of original phrasing | Surgical edits only; if >30% needed, escalate |
| Create empty placeholder pages "to be filled later" | Litter | Don't create until you have content |
| Drop `sources` entries when content is rephrased | Breaks provenance | Sources are append-only (except on source deletion) |
| Use chat-style preamble ("Here's a wiki page on…") | Wiki readers see this | Start with a heading or substantive sentence |
