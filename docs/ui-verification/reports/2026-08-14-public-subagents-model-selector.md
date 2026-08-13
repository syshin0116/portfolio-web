# Public subagents and model selector verification

## Candidate

- Revision: `e503a8729385ffa501fb8cc72ca4c12d47f40d99`
- Environment: local Chromium against the isolated APv2 fixture
- Authority: authoritative for the committed UI candidate, not the Vercel deployment

## Result

Passed. Anonymous chat remains Luna-fixed with no selector. Signed-in chat exposes the
reviewed Luna, Terra, and Sol choices, snapshots the selection when a run starts, and
sends the exact model key through APv2. Dynamic task activity renders without exposing
child arguments, results, or transcript content.

## Checks

- Web unit suite: 490 passed
- Lint, typecheck, and production build: passed
- Native assistant browser suite: 12 passed
- Supported-width overflow and reduced-motion checks: passed
- Browser console and page errors: none

## Evidence

- Playwright report: `web/playwright-report/e503a8729385ffa501fb8cc72ca4c12d47f40d99/index.html`
- Screenshot attachments: 17

No live provider request, login, cloud mutation, or paid API call was used for this
verification. Vercel Preview and Production are verified separately after CI deployment.
