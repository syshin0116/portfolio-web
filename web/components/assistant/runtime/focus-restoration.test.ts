import { describe, expect, test } from "bun:test"

import {
  COMPOSER_ACCESSIBLE_NAME,
  restoreComposerFocus,
} from "./focus-restoration"

describe("restoreComposerFocus", () => {
  test("restores keyboard focus to the labelled composer after HITL resume", () => {
    const calls: string[] = []
    const root = {
      querySelector(selector: string) {
        calls.push(selector)
        return {
          focus() {
            calls.push("focus")
          },
        }
      },
    }

    restoreComposerFocus(root, (callback) => {
      calls.push("schedule")
      callback()
    })

    expect(calls).toEqual([
      "schedule",
      `textarea[aria-label="${COMPOSER_ACCESSIBLE_NAME}"]`,
      "focus",
    ])
  })

  test("is safe when the composer is no longer mounted", () => {
    expect(() =>
      restoreComposerFocus(
        { querySelector: () => null },
        (callback) => callback()
      )
    ).not.toThrow()
  })
})
