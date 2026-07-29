const AUTH_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  AccessDenied:
    "로그인이 허용되지 않았습니다. 허용된 소유자 계정인지 확인해 주세요.",
  Configuration:
    "로그인 설정을 확인하는 중 문제가 발생했습니다. 잠시 뒤 다시 시도해 주세요.",
  OAuthAccountNotLinked:
    "이 이메일은 다른 로그인 방식에 이미 연결되어 있습니다. 처음 사용한 Google 또는 GitHub로 로그인해 주세요.",
  Verification:
    "인증 링크가 만료되었거나 이미 사용되었습니다.",
}

const DEFAULT_AUTH_ERROR_MESSAGE =
  "로그인을 완료하지 못했습니다. 잠시 뒤 다시 시도해 주세요."

export function authErrorMessage(error: string | null): string {
  return error === null
    ? DEFAULT_AUTH_ERROR_MESSAGE
    : (AUTH_ERROR_MESSAGES[error] ?? DEFAULT_AUTH_ERROR_MESSAGE)
}
