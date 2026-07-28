export const COMPOSER_ACCESSIBLE_NAME = "AI에게 보낼 메시지"

interface FocusTarget {
  focus(): void
}

interface QueryRoot {
  querySelector(selector: string): FocusTarget | null
}

type Scheduler = (callback: () => void) => void

function browserScheduler(callback: () => void): void {
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(callback)
  } else {
    queueMicrotask(callback)
  }
}

export function restoreComposerFocus(
  root: QueryRoot = document,
  schedule: Scheduler = browserScheduler
): void {
  schedule(() => {
    root
      .querySelector(
        `textarea[aria-label="${COMPOSER_ACCESSIBLE_NAME}"]`
      )
      ?.focus()
  })
}
