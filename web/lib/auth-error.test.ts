import { describe, expect, test } from "bun:test"
import { authErrorMessage } from "./auth-error"

describe("authErrorMessage", () => {
  test("explains safe cross-provider account linking", () => {
    expect(authErrorMessage("OAuthAccountNotLinked")).toContain(
      "처음 사용한 Google 또는 GitHub"
    )
  })

  test.each([null, "Unknown", ""])(
    "uses one safe fallback for %s",
    (error) => {
      expect(authErrorMessage(error)).toBe(
        "로그인을 완료하지 못했습니다. 잠시 뒤 다시 시도해 주세요."
      )
    }
  )
})
