import { describe, expect, test } from "bun:test"
import { parseMarkdownIntoBlocks } from "./markdown"

describe("parseMarkdownIntoBlocks", () => {
  test("keeps heading separators as standalone raw blocks without losing source", () => {
    const source = "# Heading\n\nFollowing paragraph"

    const blocks = parseMarkdownIntoBlocks(source)

    expect(blocks).toEqual(["# Heading", "\n\n", "Following paragraph"])
    expect(blocks.join("")).toBe(source)
  })

  test("keeps trailing blank lines out of GFM table blocks without losing source", () => {
    const source = [
      "| Method | Recall |",
      "| --- | ---: |",
      "| BM25 | 13 |",
      "",
      "",
    ].join("\n")

    const blocks = parseMarkdownIntoBlocks(source)

    expect(blocks).toEqual([
      "| Method | Recall |\n| --- | ---: |\n| BM25 | 13 |",
      "\n\n",
    ])
    expect(blocks.join("")).toBe(source)
  })
})
