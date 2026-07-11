# wiki-curator: lint

Health check for `content/wiki/`. Read [SKILL.md](./SKILL.md) and [conventions.md](./conventions.md) first.

Lint is **read-only**. It surfaces issues in a report. It does not auto-fix. Human (or a follow-up `ingest`) decides what to do.

## Checks

Run all checks every time. Group findings by severity.

### 1. Broken wikilinks (severity: red)

```bash
grep -roE '\[\[[^]]+\]\]' content/wiki/ \
  | sed 's/^\([^:]*\):.*\[\[\([^]|#]*\).*/\1\t\2/' > /tmp/links.tsv

ls content/wiki/*.md \
  | xargs -n1 basename \
  | sed 's/\.md$//' \
  | sort -u > /tmp/pages.txt

awk -F'\t' '{print $2}' /tmp/links.tsv | sort -u > /tmp/link-targets.txt
comm -23 /tmp/link-targets.txt /tmp/pages.txt
```

For each broken link, report which pages contain it.

### 2. Orphan pages (severity: yellow)

A page is orphan if no other wiki page links to it.

```bash
for page in content/wiki/*.md; do
  slug=$(basename "$page" .md)
  count=$(grep -roE "\[\[$slug" content/wiki/ | grep -v "^${page}:" | wc -l)
  if [ "$count" -eq 0 ]; then
    echo "$page"
  fi
done
```

A few orphans is normal (the index, top-level concepts). Many orphans = wiki isn't connected.

### 3. Missing sources (severity: red)

Every wiki page must have `sources:` with at least one entry.

```bash
for page in content/wiki/*.md; do
  if ! grep -q "^sources:" "$page" || \
     awk '/^sources:/{flag=1; next} /^[a-z]/{flag=0} flag && /^  - /' "$page" | head -1 | grep -q .; then
    : # has at least one source
  else
    echo "$page (no sources)"
  fi
done
```

### 4. Invalid sources (severity: red)

```bash
bun .claude/skills/wiki-curator/scripts/verify.ts
```

Report every `source-invalid` failure. Repo-local sources must be existing files inside the repository; remote sources must be syntactically valid absolute HTTPS URLs. The verifier validates URL syntax without fetching the URL.

### 5. Stale claims (severity: yellow)

Pages whose `updated` is more than **18 months** ago.

```bash
CUTOFF=$(date -u -v-18m +%Y-%m-%d 2>/dev/null || date -u -d '18 months ago' +%Y-%m-%d)

for page in content/wiki/*.md; do
  updated=$(awk '/^updated:/{print $2}' "$page" | tr -d '"')
  if [ -n "$updated" ] && [ "$updated" \< "$CUTOFF" ]; then
    echo "$page (updated: $updated)"
  fi
done
```

For technical content (LLM, frameworks, tools) consider 12 months instead.

### 6. Contradictions (severity: blue, informational)

List every page that has a `## Contradictions` section. These are intentional, not bugs - but worth reviewing periodically.

```bash
grep -l "^## Contradictions" content/wiki/*.md
```

### 7. Legacy `coverage` field (severity: yellow)

`coverage:` is deprecated - derived in index.md, not stored. Flag pages that still carry it; migrate removes them.

```bash
grep -l "^coverage:" content/wiki/**/*.md 2>/dev/null
```

### 8. Tag vocabulary drift (severity: blue)

List all tags in use, sorted by frequency. Surface tags used only once - likely typos or candidates for consolidation.

```bash
grep -h "^  - " content/wiki/*.md \
  | grep -v "^  - content/" \
  | sed 's/^  - //' \
  | sort | uniq -c | sort -n
```

### 9. Forbidden modifications (severity: red)

The wiki's `raw/` (= every `.md` outside `content/wiki/`) must be untouched by the routine. Confirm:

```bash
LAST=$(git log --grep "^routine:" -1 --format=%H 2>/dev/null)
[ -z "$LAST" ] && exit 0

git diff --name-only "$LAST" HEAD -- 'content/*.md' ':(exclude)content/wiki/'
```

If any output → routine illegally modified source material. Report and roll back.

### 10. Mandatory section presence (severity: yellow)

Every page must have `## Key Claims`. Body `## Summary` is forbidden — summary lives in frontmatter; `verify.ts` enforces this.

```bash
for page in content/wiki/*.md; do
  grep -q "^## Key Claims" "$page" || echo "$page (no Key Claims)"
done
```

## Report format

Output a single markdown report:

```markdown
# Wiki lint report - YYYY-MM-DD HH:MM

## Summary

- Pages scanned: N
- Red issues: X
- Yellow issues: Y
- Blue (informational): Z

## Red - fix before next ingest

### Broken wikilinks (N)
| Page | Broken target |
|------|---------------|
| zettelkasten.md | [[atomic-notes]] |

### Missing sources (N)
- ...

### Source files missing (N)
- ...

### Forbidden raw/ modifications
- (any output here = serious bug; halt routine)

## Yellow - review when convenient

### Orphan pages (N)
- ...

### Stale pages (>18 months)
- ...

### Coverage mismatches
- ...

### Pages missing mandatory sections
- ...

## Blue - informational

### Pages with contradictions
- ...

### Tag vocabulary
- Single-use tags (consolidation candidates):
  - ...
```

Append a one-liner to `log.md`:
```
## [YYYY-MM-DD HH:MM] lint | red:X yellow:Y blue:Z
```

## When to run

- After every ingest (smoke test).
- Weekly on its own (catches drift).
- Before any major operation (e.g., reflect, backfill).

## What lint does NOT do

- Does not modify any file.
- Does not delete pages.
- Does not auto-fix broken links (a page might genuinely need a new wiki page created - that's an ingest decision, not a lint decision).
- Does not re-ingest stale content (that's a human decision).
