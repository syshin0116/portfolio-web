# wiki-curator: reflect

Cross-source connection pass. Read [SKILL.md](./SKILL.md) and [conventions.md](./conventions.md) first.

Reflect runs **after** ingest has already produced isolated wiki pages. Its job: surface and add cross-links that ingest couldn't see (because each ingest only had its own narrow context).

## When to run

- Periodically (weekly or monthly).
- After a large batch ingest (e.g., backfill).
- When `lint` reports many orphan pages.
- Never in the same routine session as ingest — reflect needs a fresh view of all pages.

## What reflect does NOT do

- Does not create new pages. Only adds links between existing pages.
- Does not modify `## Summary`, `## Key Claims`, or any source-derived content. Only edits `## Connections` and inline body links.
- Does not delete or rename pages.
- Does not add `[[X]]` to a page that doesn't exist yet (run ingest if a target is missing).

## Workflow

### 1. Build the page graph

```bash
mkdir -p .wiki-cache
> .wiki-cache/pages.tsv
> .wiki-cache/links.tsv

for page in content/wiki/*.md; do
  slug=$(basename "$page" .md)
  title=$(awk '/^title:/{$1=""; gsub(/^ *"|"$/,""); print; exit}' "$page")
  tags=$(awk '/^tags:/{f=1;next} /^[a-z]/{f=0} f && /^  - /{print $2}' "$page" | tr '\n' ',')
  echo -e "$slug\t$title\t$tags" >> .wiki-cache/pages.tsv

  grep -oE '\[\[[^]]+\]\]' "$page" \
    | sed "s/^\[\[\([^]|#]*\).*/$slug\t\1/" >> .wiki-cache/links.tsv
done
```

### 2. Find candidate connections

For each page, look for other pages it should plausibly link to. Three heuristics:

#### a. Tag overlap

Two pages sharing 2+ tags are likely related.

```bash
# Pseudocode: pages_by_tag = invert pages.tsv tags column
# For each page, collect pages that share 2+ of its tags
```

#### b. Title mention in body

If page B's title appears verbatim in page A's body but isn't already wikilinked, that's a missed connection.

```bash
for page in content/wiki/*.md; do
  while IFS=$'\t' read -r other_slug other_title _; do
    [ "$(basename "$page" .md)" = "$other_slug" ] && continue
    if grep -F -q "$other_title" "$page" \
       && ! grep -F -q "[[$other_slug]]" "$page"; then
      echo "$page mentions '$other_title' but doesn't link [[$other_slug]]"
    fi
  done < .wiki-cache/pages.tsv
done
```

#### c. Shared sources

Pages that share 1+ source paths are by construction discussing related material.

```bash
# Pseudocode: build sources_by_page, invert to pages_by_source
# Pages that co-occur in multiple sources' inverted lists are candidates
```

### 3. Rank and filter candidates

For each candidate connection (page A → page B):

- **Strong** (auto-add): tag overlap ≥ 2 AND (title mention OR shared source).
- **Medium** (propose to user): tag overlap ≥ 2 OR (title mention AND shared source).
- **Weak** (discard): only one signal.

Don't add weak connections. They're noise.

### 4. Add strong connections

For each strong candidate, add inline (preferred) or to `## Connections`:

**Inline (preferred)**: if there's a sentence in page A that mentions page B's topic, replace the literal phrase with `[[B]]`:

```diff
- The Zettelkasten method emphasizes atomic notes.
+ The [[zettelkasten]] method emphasizes [[atomic-notes]].
```

Only do this when the surrounding sentence is genuinely discussing the linked concept. Don't transform a passing mention into a link.

**Connections section**: if no natural inline spot exists, add to `## Connections`:

```markdown
## Connections

- [[zettelkasten]] — note-linking method that inspired this approach
- [[obsidian-graph-view]] — visual interface for the same idea
```

Each link gets a one-line explanation. Empty `[[X]]` bullets without context are forbidden.

### 5. Propose medium connections to user

Output a markdown report with proposed (not applied) medium-strength connections:

```markdown
## Proposed connections (medium confidence)

| Source page | Target page | Signal | Suggested location |
|-------------|-------------|--------|--------------------|
| rag-pattern.md | langchain.md | tag overlap (rag, llm) | inline in §"frameworks" |
```

User reviews and approves before any edit.

### 6. Bump `updated` for any page touched

Every page that received a new link gets `updated:` bumped to today.

### 7. Commit

```bash
TS=$(date -u +%Y%m%d-%H%M%S)
BRANCH="claude/wiki-reflect-$TS"
git checkout -b "$BRANCH"
git add content/wiki/
git commit -m "routine: wiki reflect — N cross-links added across M pages"
git push origin "$BRANCH"
gh pr create --base main \
  --title "routine: wiki reflect — N links added" \
  --body "$(generate_reflect_pr_body)"
```

PR body must include:

- Summary: N strong links added, M medium proposed
- Per-page diff: which links added where
- The "proposed medium connections" table (for human review next round)

### 8. Log

Append to `log.md`:

```
## [YYYY-MM-DD HH:MM] reflect | added X links across Y pages, Z proposed for review
```

## Anti-patterns

| Anti-pattern | Why it's bad | What to do instead |
|--------------|--------------|---------------------|
| Add `[[See also: ...]]` blocks of 5+ links | Forced links pollute graph | Only add when natural |
| Auto-add all medium-confidence links | Garbage links accumulate | Propose to user; don't apply |
| Modify `## Summary` or `## Key Claims` to "weave in" links | Self-corruption — these sections are source-derived | Only edit `## Connections` and inline body |
| Add bidirectional links automatically | Sometimes A→B is natural but B→A isn't | Each direction evaluated independently |
| Re-run reflect on the same page set repeatedly | Drift, link explosion | Run weekly or monthly, not after every ingest |
