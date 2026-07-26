import { describe, expect, test } from "bun:test"

import { parseServerSentEvents } from "./sse"

function chunkedStream(chunks: readonly string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

describe("parseServerSentEvents", () => {
  test("handles comments, CRLF, chunk boundaries, and multiline data", async () => {
    const stream = chunkedStream([
      "\uFEFF: keepalive\r\nid: 7\r",
      "\nevent: input.requested\r\ndata: {\"type\":\"event\",\r\n",
      "data: \"seq\":7}\r\nretry: 1500\r\n\r\n",
      ": ignored\n\ndata: tail",
    ])

    const frames = []
    for await (const frame of parseServerSentEvents(stream)) {
      frames.push(frame)
    }

    expect(frames).toEqual([
      {
        id: "7",
        event: "input.requested",
        data: '{"type":"event",\n"seq":7}',
        retry: 1500,
      },
      { data: "tail" },
    ])
  })

  test("honors an already-aborted signal", async () => {
    const reason = new DOMException("stopped", "AbortError")
    const controller = new AbortController()
    controller.abort(reason)

    const consume = async () =>
      parseServerSentEvents(
        chunkedStream(["data: ignored\n\n"]),
        controller.signal
      )
        .next()
        .then(() => undefined)

    await expect(consume()).rejects.toBe(reason)
  })
})
