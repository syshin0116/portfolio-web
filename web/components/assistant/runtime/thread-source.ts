export interface ActiveThreadSource {
  generation: number
  remoteId?: string
}

export interface RuntimeThreadSource {
  generation: number
  threadId?: string
}

export function advanceActiveThreadSource(
  current: ActiveThreadSource,
  remoteId: string | undefined
): ActiveThreadSource {
  const startsNewLocalThread =
    current.remoteId !== remoteId &&
    (remoteId === undefined || current.remoteId !== undefined)
  return {
    generation:
      current.generation + (startsNewLocalThread ? 1 : 0),
    remoteId,
  }
}

export function runtimeSourceIsActive(
  active: ActiveThreadSource,
  source: RuntimeThreadSource
): boolean {
  return (
    source.generation === active.generation &&
    source.threadId === active.remoteId
  )
}
