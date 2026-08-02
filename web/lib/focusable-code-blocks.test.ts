import { describe, expect, test } from "bun:test"

import { makeGeneratedCodeBlocksFocusable } from "./focusable-code-blocks"

describe("makeGeneratedCodeBlocksFocusable", () => {
  test("adds a keyboard stop to plain preformatted blocks", () => {
    const html = "<p>before</p><pre><code>wide output</code></pre><p>after</p>"

    expect(makeGeneratedCodeBlocksFocusable(html)).toBe(
      '<p>before</p><pre tabindex="0"><code>wide output</code></pre><p>after</p>'
    )
  })

  test("preserves attributes and an existing tabindex", () => {
    const html =
      '<pre class="plain"><code>plain</code></pre>' +
      '<pre data-note=">" tabindex="-1"><code>script</code></pre>'

    expect(makeGeneratedCodeBlocksFocusable(html)).toBe(
      '<pre tabindex="0" class="plain"><code>plain</code></pre>' +
        '<pre data-note=">" tabindex="-1"><code>script</code></pre>'
    )
  })

  test("does not rewrite pre-like text in raw-text elements or comments", () => {
    const html =
      '<script>const example = "<pre>"</script>' +
      "<style>.example::before { content: '<pre>'; }</style>" +
      "<textarea><pre></textarea>" +
      "<!-- <pre> -->" +
      "<pre><code>actual block</code></pre>"

    expect(makeGeneratedCodeBlocksFocusable(html)).toBe(
      '<script>const example = "<pre>"</script>' +
        "<style>.example::before { content: '<pre>'; }</style>" +
        "<textarea><pre></textarea>" +
        "<!-- <pre> -->" +
        '<pre tabindex="0"><code>actual block</code></pre>'
    )
  })

  test("keeps raw-text positions stable across expanding Unicode case folds", () => {
    const html =
      `<SCRIPT>${"İ".repeat(10)}<pre></ScRiPt>` +
      "<pre><code>first</code></pre><pre><code>second</code></pre>"

    expect(makeGeneratedCodeBlocksFocusable(html)).toBe(
      `<SCRIPT>${"İ".repeat(10)}<pre></ScRiPt>` +
        '<pre tabindex="0"><code>first</code></pre>' +
        '<pre tabindex="0"><code>second</code></pre>'
    )
  })
})
