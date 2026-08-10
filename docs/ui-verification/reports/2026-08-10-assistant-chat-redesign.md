# Assistant chat redesign verification

## Candidate

- Revision: `ee601b79a817c03490edc58fb82718fb06bad7db`
- Environment: local Chromium against the isolated APv2 fixture
- Runtime identity: expected and served revision matched
- Authority: authoritative for the committed UI candidate, not the Vercel deployment

## Result

Passed. The chat now uses a conversation-first layout built from the installed assistant-ui primitives and the existing Geist font. Conversation history and execution details open on demand instead of occupying permanent columns.

## Journeys

- Owner flow: empty thread, history sheet, execution-detail sheet, typing, tool activity, HITL response, rename, reconnect, and restored composer focus
- Anonymous flow: empty thread, IME composition, generated `aui-` thread, HITL response, completed answer, generated title, and transcript reload
- Responsive flow: 320, 390, 768, 1280, and 1440 pixel viewports
- Accessibility flow: keyboard labels, focus restoration, mobile sheet behavior, and automated WCAG checks

## Checks

- `bun test`: 490 passed
- `bun run lint`: passed
- `bunx tsc --noEmit --incremental false`: passed
- `bun run build`: passed, 1,241 pages generated and 335 pages indexed
- Native assistant browser suite: 12 passed
- Site browser suite: 5 passed, 7 intentionally skipped by viewport
- Independent API and visual reviews: no blocking findings

## Evidence

- Playwright report: `web/playwright-report/ee601b79a817c03490edc58fb82718fb06bad7db/index.html`
- Persistent local evidence: `docs/ui-verification/evidence/2026-08-10-assistant-chat-redesign/`
- State inventory: 17 screenshot attachments, 16 unique PNG payloads after content-addressed deduplication, 0 missing states, 0 redacted states

The evidence directory is local-only because generated browser artifacts are not committed. The report generator embeds those images in a self-contained HTML file inside that directory.

### Representative captures

| State | Evidence |
| --- | --- |
| Desktop empty thread | `997e5dcaf9992d5bbd02486e060d2755e3e86aa5.png` |
| Desktop conversation history | `8d54c06d744ae8962bda7b3150d0cc1c24560786.png` |
| Desktop execution details | `f5d0496e234fba39cc7f950848b58f6296ccb470.png` |
| Desktop composer input | `634805083e6e1001fdd92d14965a31260125d21b.png` |
| Desktop HITL response | `1e6d452a8602aae7f17072aa5a151dd5643a874d.png` |
| Tablet HITL response | `f5d9a40efe4c168caa7bce2bb826f6cdaefa86b8.png` |
| 320 pixel HITL response | `749c055b85ec4e8fad316308ee8cf8c2436df626.png` |

## Remaining risk

The exact Vercel preview is outside this local verification boundary. Its deployment and checks are verified separately by the PR pipeline.
