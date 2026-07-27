## Outcome

<!-- What changes for a reader, visitor, operator, or contributor? -->

## Scope

<!-- Name the one coherent change in this PR and anything deliberately deferred. -->

## Validation

| Gate | Command or evidence | Result |
|---|---|---|
| Tests / contracts |  |  |
| Lint / types / build |  |  |
| UI journey (if applicable) |  |  |
| Deploy / rollback (if applicable) |  |  |

## Risk and rollback

<!-- State the failure mode and the smallest safe rollback. Use "N/A" only with a reason. -->

## Repository contract

- [ ] This PR has one coherent scope and does not include generated/build artifacts or secrets.
- [ ] Source posts (`content/**/*.md` outside `content/wiki/`) are unchanged.
- [ ] Any `content/wiki/` change was made through the wiki skill and passes `wiki/verify`.
- [ ] Changes under `web/`, `agent/`, or build/deploy config are on this branch only and will land through this PR.
- [ ] New or changed behavior has regression coverage, or the validation table explains why a test is not applicable.
- [ ] User-visible UI changes include browser evidence for affected desktop/mobile journeys, or explain why UI verification is not applicable.
- [ ] Deploy changes identify the target environment, rollout gate, and rollback path, or explain why deployment is not applicable.
- [ ] A structural or hard-to-reverse choice has a `DECISIONS.md` entry (and an ADR only if already durable), or no such choice was made.
- [ ] Required checks `ci/check`, `protocol/compat`, and `wiki/verify` are green before merge.
