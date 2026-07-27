export interface ImeEnterState {
  key: string
  shiftKey?: boolean
  nativeIsComposing: boolean
  compositionActive: boolean
}

export interface ImeKeyboardEvent {
  key: string
  shiftKey?: boolean
  nativeEvent: {
    isComposing?: boolean
  }
  preventDefault(): void
  stopPropagation(): void
}

export function shouldGuardImeEnter(state: ImeEnterState): boolean {
  return (
    state.key === "Enter" &&
    state.shiftKey !== true &&
    (state.nativeIsComposing || state.compositionActive)
  )
}

/**
 * React's native `isComposing` can flip to false before the final Korean
 * composition event reaches controlled inputs. Keep the explicit ref as the
 * second signal so either browser ordering is safe.
 */
export function createImeEnterGuard(
  isCompositionActive: () => boolean
): (event: ImeKeyboardEvent) => void {
  return (event) => {
    if (
      !shouldGuardImeEnter({
        key: event.key,
        shiftKey: event.shiftKey,
        nativeIsComposing: event.nativeEvent.isComposing === true,
        compositionActive: isCompositionActive(),
      })
    ) {
      return
    }
    event.preventDefault()
    event.stopPropagation()
  }
}
