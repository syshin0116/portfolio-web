import { describe, expect, test } from "bun:test"

import {
  advanceActiveThreadSource,
  runtimeSourceIsActive,
} from "./thread-source"

describe("runtime thread source isolation", () => {
  test("rejects old activity and errors while a new local thread has no remote id", () => {
    const previous = {
      generation: 7,
      remoteId: "thread-old",
    }
    const blank = advanceActiveThreadSource(previous, undefined)
    const staleSource = {
      generation: previous.generation,
      threadId: previous.remoteId,
    }

    expect(blank).toEqual({
      generation: 8,
      remoteId: undefined,
    })
    expect(runtimeSourceIsActive(blank, staleSource)).toBe(false)
  })

  test("matches an undefined remote id only with an explicit local generation", () => {
    const blank = {
      generation: 8,
      remoteId: undefined,
    }

    expect(
      runtimeSourceIsActive(blank, {
        generation: 7,
        threadId: undefined,
      })
    ).toBe(false)
    expect(
      runtimeSourceIsActive(blank, {
        generation: 8,
        threadId: undefined,
      })
    ).toBe(true)
  })

  test("does not advance the same blank local thread twice", () => {
    expect(
      advanceActiveThreadSource(
        { generation: 8, remoteId: undefined },
        undefined
      )
    ).toEqual({
      generation: 8,
      remoteId: undefined,
    })
  })

  test("keeps one generation while an optimistic thread receives its remote id", () => {
    const blank = {
      generation: 8,
      remoteId: undefined,
    }
    const initialized = advanceActiveThreadSource(blank, "thread-new")

    expect(initialized).toEqual({
      generation: 8,
      remoteId: "thread-new",
    })
    expect(
      runtimeSourceIsActive(initialized, {
        generation: 8,
        threadId: "thread-new",
      })
    ).toBe(true)
  })

  test("increments the generation when switching between settled remote threads", () => {
    expect(
      advanceActiveThreadSource(
        { generation: 8, remoteId: "thread-one" },
        "thread-two"
      )
    ).toEqual({
      generation: 9,
      remoteId: "thread-two",
    })
  })
})
