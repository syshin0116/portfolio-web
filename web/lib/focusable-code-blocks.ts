const RAW_TEXT_ELEMENTS = new Set([
  "iframe",
  "noembed",
  "noframes",
  "plaintext",
  "script",
  "style",
  "textarea",
  "title",
  "xmp",
])

interface StartTag {
  name: string
  nameEnd: number
  selfClosing: boolean
}

function findTagEnd(html: string, tagStart: number): number {
  let quote: '"' | "'" | null = null

  for (let index = tagStart + 1; index < html.length; index += 1) {
    const character = html[index]
    if (quote) {
      if (character === quote) quote = null
      continue
    }
    if (character === '"' || character === "'") {
      quote = character
    } else if (character === ">") {
      return index
    }
  }

  return -1
}

function readStartTag(html: string, tagStart: number, tagEnd: number): StartTag | null {
  let cursor = tagStart + 1
  while (/\s/.test(html[cursor] ?? "")) cursor += 1
  if (html[cursor] === "/" || html[cursor] === "!" || html[cursor] === "?") {
    return null
  }

  const nameStart = cursor
  while (/[A-Za-z0-9:-]/.test(html[cursor] ?? "")) cursor += 1
  if (cursor === nameStart) return null

  return {
    name: html.slice(nameStart, cursor).toLowerCase(),
    nameEnd: cursor,
    selfClosing: html.slice(tagStart, tagEnd).trimEnd().endsWith("/"),
  }
}

function hasAttribute(
  html: string,
  nameEnd: number,
  tagEnd: number,
  expectedName: string
): boolean {
  let cursor = nameEnd

  while (cursor < tagEnd) {
    while (/\s/.test(html[cursor] ?? "")) cursor += 1
    if (cursor >= tagEnd || html[cursor] === "/") return false

    const attributeStart = cursor
    while (!/[\s=/>]/.test(html[cursor] ?? ">")) cursor += 1
    const attributeName = html.slice(attributeStart, cursor).toLowerCase()
    if (attributeName === expectedName) return true

    while (/\s/.test(html[cursor] ?? "")) cursor += 1
    if (html[cursor] !== "=") continue

    cursor += 1
    while (/\s/.test(html[cursor] ?? "")) cursor += 1
    const quote = html[cursor]
    if (quote === '"' || quote === "'") {
      cursor += 1
      while (cursor < tagEnd && html[cursor] !== quote) cursor += 1
      if (html[cursor] === quote) cursor += 1
    } else {
      while (!/[\s>]/.test(html[cursor] ?? ">")) cursor += 1
    }
  }

  return false
}

function matchesAsciiCaseInsensitive(
  html: string,
  start: number,
  expectedLowercase: string
): boolean {
  if (start + expectedLowercase.length > html.length) return false

  for (let offset = 0; offset < expectedLowercase.length; offset += 1) {
    let code = html.charCodeAt(start + offset)
    if (code >= 65 && code <= 90) code += 32
    if (code !== expectedLowercase.charCodeAt(offset)) return false
  }

  return true
}

function findRawTextClose(html: string, start: number, name: string): number {
  if (name === "plaintext") return -1

  const needle = `</${name}`
  let match = html.indexOf("<", start)
  while (match !== -1) {
    const boundary = html[match + needle.length]
    if (
      matchesAsciiCaseInsensitive(html, match, needle) &&
      (boundary === undefined || /[\s/>]/.test(boundary))
    ) {
      return match
    }
    match = html.indexOf("<", match + 1)
  }

  return -1
}

/**
 * Nuartz already adds a keyboard stop to highlighted code blocks, but plain
 * fenced blocks are emitted as bare `<pre>` elements. Add the attribute while
 * the generated HTML is still on the server so accessibility does not depend
 * on hydration winning a race with keyboard navigation or Axe.
 *
 * This transformer follows tag and quoted-attribute boundaries and skips HTML
 * raw-text elements. It intentionally does not use a broad regular expression:
 * source posts may contain executable examples such as `"<pre>"` in scripts.
 */
export function makeGeneratedCodeBlocksFocusable(html: string): string {
  const output: string[] = []
  let cursor = 0
  let rawTextElement: string | null = null

  while (cursor < html.length) {
    if (rawTextElement) {
      const closeStart = findRawTextClose(html, cursor, rawTextElement)
      if (closeStart === -1) {
        output.push(html.slice(cursor))
        break
      }
      output.push(html.slice(cursor, closeStart))
      cursor = closeStart
      rawTextElement = null
    }

    const tagStart = html.indexOf("<", cursor)
    if (tagStart === -1) {
      output.push(html.slice(cursor))
      break
    }
    output.push(html.slice(cursor, tagStart))

    if (html.startsWith("<!--", tagStart)) {
      const commentEnd = html.indexOf("-->", tagStart + 4)
      if (commentEnd === -1) {
        output.push(html.slice(tagStart))
        break
      }
      output.push(html.slice(tagStart, commentEnd + 3))
      cursor = commentEnd + 3
      continue
    }

    if (html.startsWith("<![CDATA[", tagStart)) {
      const cdataEnd = html.indexOf("]]>", tagStart + 9)
      if (cdataEnd === -1) {
        output.push(html.slice(tagStart))
        break
      }
      output.push(html.slice(tagStart, cdataEnd + 3))
      cursor = cdataEnd + 3
      continue
    }

    const tagEnd = findTagEnd(html, tagStart)
    if (tagEnd === -1) {
      output.push(html.slice(tagStart))
      break
    }

    const startTag = readStartTag(html, tagStart, tagEnd)
    if (!startTag) {
      output.push(html.slice(tagStart, tagEnd + 1))
      cursor = tagEnd + 1
      continue
    }

    if (
      startTag.name === "pre" &&
      !hasAttribute(html, startTag.nameEnd, tagEnd, "tabindex")
    ) {
      output.push(
        html.slice(tagStart, startTag.nameEnd),
        ' tabindex="0"',
        html.slice(startTag.nameEnd, tagEnd + 1)
      )
    } else {
      output.push(html.slice(tagStart, tagEnd + 1))
    }

    if (!startTag.selfClosing && RAW_TEXT_ELEMENTS.has(startTag.name)) {
      rawTextElement = startTag.name
    }
    cursor = tagEnd + 1
  }

  return output.join("")
}
