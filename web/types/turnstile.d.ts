export {}

declare global {
  interface TurnstileRenderOptions {
    action: string
    callback: (token: string) => void
    "error-callback": (errorCode: string) => boolean
    "expired-callback": () => void
    "refresh-expired": "never"
    "response-field": false
    retry: "never"
    sitekey: string
    size: "flexible"
    theme: "auto"
    "timeout-callback": () => void
  }

  interface TurnstileApi {
    remove(widgetId: string): void
    render(
      container: HTMLElement | string,
      options: TurnstileRenderOptions
    ): string
    reset(widgetId: string): void
  }

  interface Window {
    turnstile?: TurnstileApi
  }
}
