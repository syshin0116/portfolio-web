export interface ServerSentEvent {
  id?: string
  event?: string
  data: string
  retry?: number
}

interface PendingEvent {
  id?: string
  event?: string
  data: string[]
  retry?: number
}

function createPendingEvent(): PendingEvent {
  return { data: [] }
}

function consumeLine(
  rawLine: string,
  pending: PendingEvent,
  isFirstLine: boolean
): ServerSentEvent | undefined {
  const line =
    isFirstLine && rawLine.charCodeAt(0) === 0xfeff
      ? rawLine.slice(1)
      : rawLine

  if (line === "") {
    if (pending.data.length === 0) return undefined
    return {
      ...(pending.id === undefined ? {} : { id: pending.id }),
      ...(pending.event === undefined ? {} : { event: pending.event }),
      data: pending.data.join("\n"),
      ...(pending.retry === undefined ? {} : { retry: pending.retry }),
    }
  }
  if (line.startsWith(":")) return undefined

  const colon = line.indexOf(":")
  const field = colon === -1 ? line : line.slice(0, colon)
  let value = colon === -1 ? "" : line.slice(colon + 1)
  if (value.startsWith(" ")) value = value.slice(1)

  switch (field) {
    case "data":
      pending.data.push(value)
      break
    case "event":
      pending.event = value
      break
    case "id":
      if (!value.includes("\0")) pending.id = value
      break
    case "retry": {
      if (/^\d+$/.test(value)) pending.retry = Number(value)
      break
    }
    default:
      // Unknown SSE fields are explicitly forward-compatible.
      break
  }
  return undefined
}

/**
 * Incrementally parses the EventSource wire format.
 *
 * It accepts LF, CRLF, and CR delimiters, preserves multiline `data:` with
 * newline joins, ignores heartbeat comments, and dispatches a final frame at
 * EOF even when the server omitted the trailing blank line.
 */
export async function* parseServerSentEvents(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal
): AsyncGenerator<ServerSentEvent> {
  signal?.throwIfAborted()
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let pending = createPendingEvent()
  let firstLine = true

  const onAbort = () => {
    void reader.cancel(signal?.reason).catch(() => undefined)
  }
  signal?.addEventListener("abort", onAbort, { once: true })

  const processBufferedLines = function* (
    atEnd: boolean
  ): Generator<ServerSentEvent> {
    while (true) {
      const match = /\r\n|\r|\n/.exec(buffer)
      if (!match) break
      // A CR at the end of a network chunk may be the first half of CRLF.
      if (
        !atEnd &&
        match[0] === "\r" &&
        match.index === buffer.length - 1
      ) {
        break
      }
      const line = buffer.slice(0, match.index)
      buffer = buffer.slice(match.index + match[0].length)
      const frame = consumeLine(line, pending, firstLine)
      firstLine = false
      if (frame) {
        yield frame
        pending = createPendingEvent()
      } else if (line === "") {
        pending = createPendingEvent()
      }
    }

    if (atEnd && buffer.length > 0) {
      const frame = consumeLine(buffer, pending, firstLine)
      firstLine = false
      buffer = ""
      if (frame) {
        yield frame
        pending = createPendingEvent()
      }
    }
    if (atEnd && pending.data.length > 0) {
      yield {
        ...(pending.id === undefined ? {} : { id: pending.id }),
        ...(pending.event === undefined ? {} : { event: pending.event }),
        data: pending.data.join("\n"),
        ...(pending.retry === undefined ? {} : { retry: pending.retry }),
      }
      pending = createPendingEvent()
    }
  }

  try {
    while (true) {
      signal?.throwIfAborted()
      const { value, done } = await reader.read()
      signal?.throwIfAborted()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      yield* processBufferedLines(false)
    }
    buffer += decoder.decode()
    yield* processBufferedLines(true)
  } finally {
    signal?.removeEventListener("abort", onAbort)
    reader.releaseLock()
  }
}
