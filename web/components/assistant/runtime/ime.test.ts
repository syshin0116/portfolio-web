import { describe, expect, test } from "bun:test"

import {
  createImeEnterGuard,
  shouldGuardImeEnter,
} from "./ime"

describe("Korean IME Enter guard", () => {
  test.each([
    ["native composing", true, false],
    ["composition ref", false, true],
    ["both signals", true, true],
  ] as const)(
    "blocks Enter while %s is active",
    (_label, nativeIsComposing, compositionActive) => {
      expect(
        shouldGuardImeEnter({
          key: "Enter",
          nativeIsComposing,
          compositionActive,
        })
      ).toBe(true)
    }
  )

  test("does not block ordinary Enter, Shift+Enter, or non-Enter keys", () => {
    expect(
      shouldGuardImeEnter({
        key: "Enter",
        nativeIsComposing: false,
        compositionActive: false,
      })
    ).toBe(false)
    expect(
      shouldGuardImeEnter({
        key: "Enter",
        shiftKey: true,
        nativeIsComposing: true,
        compositionActive: true,
      })
    ).toBe(false)
    expect(
      shouldGuardImeEnter({
        key: "Process",
        nativeIsComposing: true,
        compositionActive: true,
      })
    ).toBe(false)
  })

  test("the wired handler prevents and stops both native and ref races", () => {
    for (const [nativeIsComposing, compositionActive] of [
      [true, false],
      [false, true],
    ] as const) {
      const calls: string[] = []
      const guard = createImeEnterGuard(() => compositionActive)
      guard({
        key: "Enter",
        shiftKey: false,
        nativeEvent: { isComposing: nativeIsComposing },
        preventDefault: () => calls.push("prevent"),
        stopPropagation: () => calls.push("stop"),
      })
      expect(calls).toEqual(["prevent", "stop"])
    }
  })
})
