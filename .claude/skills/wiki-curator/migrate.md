# wiki-curator: migrate

Restructure folders, types, and tag vocabulary to reflect emergent patterns. Read [SKILL.md](./SKILL.md) and [conventions.md](./conventions.md) first.

## When to run

- When `lint` reports significant drift (orphan pages, parallel tag synonyms, mismatched types).
- After a backfill or large ingest batch (50+ new pages).
- Periodically (monthly), to consolidate accumulated mess.
- **Never** in the same routine session as ingest — they have conflicting goals (ingest preserves; migrate restructures).

## What migrate may do

migrate has broad authority over the wiki's shape:

- **Introduce sub-folders** when 5+ pages of the same kind have accumulated.
- **Move pages** between folders.
- **Rename folders** to better reflect their contents.
- **Remove folders** that no longer hold a coherent group.
- **Consolidate `type:` vocabulary** (e.g., `tool` + `tooling` + `utility` → `tool`).
- **Consolidate tag vocabulary** (e.g., `note-taking` + `notes` → `note-taking`).
- **Update `summary:` fields** if frontmatter and body have drifted (rare; ingest should keep them in sync).
- **Fix broken `[[wikilinks]]`** when slugs change.
- **Remove empty/litter sections** in pages.

## What migrate must NOT do

- **Modify source-derived body content** (`## Key Claims`, code examples, footnotes). migrate touches metadata + location only.
- **Delete pages.** Move to `content/wiki/.orphaned/<slug>.md` if truly unwanted; user recovers if needed.
- **Run when sources have changed since last ingest.** Run ingest first.

## Workflow

### 1. Sanity check — no pending source changes

```bash
LAST_INGEST=$(git log --grep "^routine: wiki ingest" -1 --format=%H 2>/dev/null)
[ -z "$LAST_INGEST" ] && LAST_INGEST=$(git rev-list --max-parents=0 HEAD)

if git diff --name-only "$LAST_INGEST" HEAD -- 'content/*.md' \
     ':(exclude)content/wiki/' ':(exclude)content/Untitled.md' | grep -q .; then
  echo "Source posts changed since last ingest — run ingest first"
  exit 0
fi
```

### 2. Build the current shape inventory

For every page in `content/wiki/`, collect:

```
- slug (filename without .md)
- folder (parent dir relative to content/wiki/, "" if root)
- type (frontmatter)
- tags (frontmatter)
- summary (frontmatter, first 80 chars)
- sources count
- updated date
- outgoing wikilinks (from body)
- incoming wikilinks (from other pages' bodies)
```

Save to `.wiki-cache/inventory.tsv` for later inspection. This is the input to all decisions below.

### 3. Detect drift signals

#### a. Folder candidates

Group pages by `type:`. If a type has 5+ pages and they're all at root → candidate folder.

```
type=concept   12 pages at root  → propose concepts/
type=pattern    8 pages at root  → propose patterns/
type=tool       6 pages at root  → propose tools/
type=reference  3 pages at root  → not enough, leave at root
type=experiment 2 pages at root  → not enough
```

If a type already has a folder but contains <3 pages → propose dissolving (move back to root).

If a folder exists but pages with that type are scattered (some in folder, some at root) → propose consolidating.

#### b. Type vocabulary drift

Count types in use. Detect parallel forms:

```bash
grep -h "^type:" content/wiki/**/*.md | awk '{print $2}' | sort | uniq -c | sort -rn
```

If close synonyms appear (`tool`+`tooling`, `concept`+`idea`, etc.) → propose consolidation. Keep the more common form.

#### c. Tag vocabulary drift

Same idea, tags:

```bash
awk '/^tags:/{f=1; next} /^[a-z]/{f=0} f && /^  - /{print $2}' content/wiki/**/*.md \
  | sort | uniq -c | sort -rn
```

Detect parallel forms (`note-taking` + `notes`, `pkm` + `personal-knowledge-management`).
Detect tags used only once (often typos or one-offs).

#### d. Stale slugs

Pages whose `title:` no longer matches their slug (after edits). Optional rename, but only if backlinks are migrated atomically.

#### e. Coverage tier mismatches

`coverage` should match `sources` length. If many pages have stale `coverage` values → propose recompute.

(coverage is derived in index.md now per the new conventions, so this check may be moot. If old pages still have a `coverage:` field, remove it.)

### 4. Propose a migration plan

Write the plan to `.wiki-cache/migration-plan.md`:

```markdown
# Migration plan — YYYY-MM-DD HH:MM UTC

## Folder restructuring

Introduce:
- `concepts/` (12 pages): zettelkasten, knowledge-graph, atomic-notes, ...
- `patterns/` (8 pages): rag-pattern, llm-text-to-sql, ...

Reasoning: 12 concept-type pages have accumulated at root. Grouping them
makes the file tree legible without breaking links (slugs unchanged).

## Type consolidation

Merge:
- `tool` (5) ← `tooling` (1), `utility` (1)
- `concept` (12) ← `idea` (2)

## Tag consolidation

Merge:
- `note-taking` (8) ← `notes` (3)
- `pkm` (5) ← `personal-knowledge-management` (1)

## Pages to move

| From | To |
|------|----|
| zettelkasten.md | concepts/zettelkasten.md |
| ...

## Backlinks to fix

None. Slugs unchanged, Nuartz/Obsidian resolve by filename.
```

### 5. Apply the plan

Execute the proposals in this order (so partial failure leaves wiki in a consistent state):

1. **Tag consolidation** — rewrite `tags:` lists across all affected pages.
2. **Type consolidation** — rewrite `type:` field across all affected pages.
3. **File moves** — `git mv content/wiki/<slug>.md content/wiki/<folder>/<slug>.md` (slugs unchanged so wikilinks still resolve by basename).
4. **Cleanup** — remove the now-empty old `coverage:` fields, remove empty `## Connections` sections, etc.
5. **Rebuild `index.md`** — reflects new structure.
6. **Verify wikilinks** — same check as ingest.

If any step fails → halt. Do not commit a half-applied migration.

### 6. log.md

Append:

```
## [YYYY-MM-DD HH:MM UTC] migrate | introduced concepts/ patterns/ tools/, moved 26 pages, consolidated 3 tags + 2 types
```

### 7. Commit & PR

```bash
TS=$(date -u +%Y%m%d-%H%M%S)
BRANCH="claude/wiki-migrate-$TS"
git checkout -b "$BRANCH"
git add content/wiki/
git commit -m "routine: wiki migrate — <one-line summary>"
git push origin "$BRANCH"
gh pr create --base main \
  --title "routine: wiki migrate — <one-line summary>" \
  --body "$(generate_migrate_pr_body)"
```

PR body must include the full migration plan (from step 4) plus actual results (in case anything diverged during application). The reasoning matters more than the diff — humans reviewing should be able to judge whether the structure makes sense, not just whether the moves are correct.

## Anti-patterns specific to migrate

- **Moves without a pattern.** A folder needs ≥5 pages of the same kind to be worth introducing. Single-page folders are noise.
- **Rewriting bodies.** That's ingest's job; this op touches metadata + location only.
- **Inventing new types/tags.** Only consolidate existing vocabulary; don't enrich on top.
- **Piecemeal commits.** One PR per migrate run, all-or-nothing — easier to roll back.

## Gotchas

- **Slug rename = backlink break.** Renaming a slug requires updating every `[[old-slug]]` reference in the same operation. The verify-wikilinks script catches misses.
- **Wikilinks resolve by basename.** Folder moves are safe; the script confirms.
- **`git mv` preserves history.** Use it for moves; don't `rm` + `add`.
- **Tag/type consolidation is one-way.** No undo via re-running migrate. Keep the migration plan reviewable.
