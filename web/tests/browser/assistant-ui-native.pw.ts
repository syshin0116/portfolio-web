import AxeBuilder from "@axe-core/playwright"
import {
  expect,
  test,
  type Page,
  type TestInfo,
} from "@playwright/test"

interface FixtureState {
  cancellations: Array<{ runId: string; threadId: string }>
  commands: Array<{
    method?: unknown
    params?: unknown
  }>
  errors: string[]
  messageIdMappings: Array<{
    clientId: string
    projectedId: string
    storedId: string
  }>
  reconnectDisconnects: number
  renameAttempts: number
  responses: Array<{
    interrupt_id?: unknown
    metadata?: unknown
    namespace?: unknown
    response?: unknown
  }>
  revision: string
  stateRequests: Array<{
    authorization: boolean
    interrupted: boolean
    threadId: string
  }>
  staleSourceDeliveries: number
  streamSubscriptions: Array<{
    authorization: boolean
    body: Record<string, unknown>
    threadId: string
  }>
}

interface BrowserDiagnostics {
  consoleIssues: string[]
  pageErrors: string[]
}

const fixtureOrigin = "http://127.0.0.1:3130"
const fixtureWebOrigin = "http://127.0.0.1:3128"
const fixtureOwnerCookie = "fixture-owner-session"
const revision =
  process.env.GITHUB_SHA?.trim() ||
  process.env.TEST_REVISION?.trim() ||
  "local"

async function resetFixture(
  page: Page,
  scenario:
    | "cancel-auth-failure"
    | "default"
    | "delayed-replay"
    | "load-error"
    | "public-root-state-fallback"
    | "reconnect"
    | "stale-source" = "default",
  access: "anonymous" | "owner" = "owner"
): Promise<void> {
  await page.context().clearCookies()
  if (access === "owner") {
    await page.context().addCookies([
      {
        name: fixtureOwnerCookie,
        value: "1",
        url: fixtureWebOrigin,
      },
    ])
  }
  const response = await page.request.post(
    `${fixtureOrigin}/__fixture/reset`,
    { data: { scenario } }
  )
  expect(response.ok()).toBe(true)
}

async function fixtureState(page: Page): Promise<FixtureState> {
  const response = await page.request.get(
    `${fixtureOrigin}/__fixture/state`
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as FixtureState
}

async function attachEvidence(
  page: Page,
  testInfo: TestInfo,
  name: string
): Promise<void> {
  await testInfo.attach(`${name}-${revision}.png`, {
    body: await page.screenshot(),
    contentType: "image/png",
  })
  await testInfo.attach(`${name}-${revision}.json`, {
    body: Buffer.from(
      JSON.stringify(
        {
          fixture: await fixtureState(page),
          revision,
          viewport: page.viewportSize(),
        },
        null,
        2
      )
    ),
    contentType: "application/json",
  })
}

async function expectNoBrowserErrors(
  page: Page,
  diagnostics: BrowserDiagnostics
): Promise<void> {
  const unhandled = await page.evaluate(
    () =>
      (
        window as typeof window & {
          __browserUnhandledRejections?: string[]
        }
      ).__browserUnhandledRejections ?? []
  )
  expect(diagnostics.consoleIssues).toEqual([])
  expect(diagnostics.pageErrors).toEqual([])
  expect(unhandled).toEqual([])
}

async function expectA11yClean(page: Page): Promise<void> {
  const result = await new AxeBuilder({ page }).analyze()
  expect(
    result.violations.map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      nodes: violation.nodes.map((node) => ({
        failureSummary: node.failureSummary,
        html: node.html,
        target: node.target,
      })),
    }))
  ).toEqual([])
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const browserWindow = window as typeof window & {
      __browserUnhandledRejections?: string[]
    }
    browserWindow.__browserUnhandledRejections = []
    window.addEventListener("unhandledrejection", (event) => {
      const reason = event.reason as unknown
      browserWindow.__browserUnhandledRejections?.push(
        reason instanceof Error ? reason.message : String(reason)
      )
    })
  })
})

function collectDiagnostics(page: Page): BrowserDiagnostics {
  const diagnostics: BrowserDiagnostics = {
    consoleIssues: [],
    pageErrors: [],
  }
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      diagnostics.consoleIssues.push(message.text())
    }
  })
  page.on("pageerror", (error) => {
    diagnostics.pageErrors.push(error.message)
  })
  return diagnostics
}

test.describe.serial("native assistant-ui production journey", () => {
  test("keeps remote thread-list and composer notifications live under StrictMode", async ({
    page,
  }, testInfo) => {
    const diagnostics = collectDiagnostics(page)
    await resetFixture(page)
    await page.goto("/")
    await expect(
      page.getByTestId("production-native-runtime-fixture")
    ).toBeVisible()

    const fixtureThread = page.getByRole("button", {
      name: /브라우저 테스트 대화/,
    })
    await expect(fixtureThread).toBeVisible()
    await fixtureThread.click()

    const composer = page.getByRole("textbox", {
      name: "AI에게 보낼 메시지",
    })
    await expect(composer).toBeEnabled()
    await composer.fill("StrictMode 알림 회귀 검증")
    await expect(composer).toHaveValue("StrictMode 알림 회귀 검증")
    await expect
      .poll(async () => (await fixtureState(page)).commands.length)
      .toBe(0)

    await attachEvidence(page, testInfo, "strict-mode-notifications")
    await expectNoBrowserErrors(page, diagnostics)
  })

  test("uses exact APv2 filters and survives nested HITL rejection/retry", async ({
    page,
  }, testInfo) => {
    const diagnostics = collectDiagnostics(page)
    await resetFixture(page)
    await page.goto("/")
    await expect(
      page.getByTestId("production-native-runtime-fixture")
    ).toBeVisible()
    await page
      .getByRole("button", { name: /브라우저 테스트 대화/ })
      .click()

    const composer = page.getByRole("textbox", {
      name: "AI에게 보낼 메시지",
    })
    await expect(composer).toBeEnabled()
    await composer.fill("첫째 줄")
    await composer.press("Shift+Enter")
    await composer.type("둘째 줄")
    await expect(composer).toHaveValue("첫째 줄\n둘째 줄")
    await expect
      .poll(async () => (await fixtureState(page)).commands.length)
      .toBe(0)
    await composer.dispatchEvent("compositionstart")
    await composer.fill("한글 조합 중 Enter")
    await composer.press("Enter")
    await expect
      .poll(async () => (await fixtureState(page)).commands.length)
      .toBe(0)
    await composer.dispatchEvent("compositionend")
    await composer.press("Enter")

    await expect(
      page.getByText("브라우저 fixture 검색을 계속할까요?")
    ).toBeVisible({ timeout: 12_000 })
    const initialState = await fixtureState(page)
    expect(initialState.errors).toEqual([])
    expect(initialState.commands).toHaveLength(1)
    expect(initialState.streamSubscriptions).toEqual([
      {
        authorization: true,
        body: {
          channels: [
            "messages",
            "lifecycle",
            "input",
            "tools",
            "custom",
          ],
          namespaces: [[]],
          depth: 0,
        },
        threadId: "browser-thread-1",
      },
      {
        authorization: true,
        body: {
          channels: ["lifecycle", "input"],
        },
        threadId: "browser-thread-1",
      },
    ])
    expect(
      JSON.stringify(initialState.streamSubscriptions)
    ).not.toContain('"values"')
    expect(
      JSON.stringify(initialState.streamSubscriptions)
    ).not.toContain('"updates"')

    const approve = page.getByRole("button", {
      name: "승인",
      exact: true,
    })
    await approve.click()
    await expect(
      page.getByText(
        "응답을 보내지 못했습니다. 승인 요청은 유지되었습니다. 다시 시도해 주세요."
      )
    ).toBeVisible()
    await expect(page.locator("body")).not.toContainText(
      /postgres:\/\/|fixture-secret|db\.internal/
    )
    await expect(
      page.getByText("브라우저 fixture 검색을 계속할까요?")
    ).toBeVisible()
    await expect(composer).toBeFocused()
    expect((await fixtureState(page)).responses).toEqual([
      expect.objectContaining({
        namespace: ["nested_subgraph:browser-task"],
        interrupt_id: "browser-interrupt-1",
        response: "approve",
        metadata: expect.objectContaining({
          syshin_ui_submit_nonce: expect.any(String),
        }),
      }),
    ])

    await approve.click()
    await expect(
      page.getByText("브라우저 fixture 응답이 완료되었습니다.")
    ).toBeVisible()
    expect((await fixtureState(page)).responses).toEqual([
      expect.objectContaining({
        namespace: ["nested_subgraph:browser-task"],
        interrupt_id: "browser-interrupt-1",
        response: "approve",
        metadata: expect.objectContaining({
          syshin_ui_submit_nonce: expect.any(String),
        }),
      }),
      expect.objectContaining({
        namespace: ["nested_subgraph:browser-task"],
        interrupt_id: "browser-interrupt-1",
        response: "approve",
        metadata: expect.objectContaining({
          syshin_ui_submit_nonce: expect.any(String),
        }),
      }),
    ])
    expect((await fixtureState(page)).streamSubscriptions).toEqual([
      ...initialState.streamSubscriptions,
      ...initialState.streamSubscriptions,
    ])
    await expect(
      page.getByText("중첩 작업이 끝났습니다.")
    ).toBeVisible()

    await page.reload()
    await page
      .getByRole("button", { name: /브라우저 테스트 대화/ })
      .click()
    await expect(
      page.getByText("브라우저 fixture 응답이 완료되었습니다.")
    ).toBeVisible()

    await expectA11yClean(page)
    await expectNoBrowserErrors(page, diagnostics)
    await attachEvidence(page, testInfo, "native-hitl-wire")
  })

  test("keeps rename rejection inline and cancels one exact active run", async ({
    page,
  }, testInfo) => {
    const diagnostics = collectDiagnostics(page)
    await resetFixture(page)
    await page.goto("/")
    await page
      .getByRole("button", { name: /브라우저 테스트 대화/ })
      .click()

    await page.getByRole("button", { name: "대화 제목 변경" }).click()
    const title = page.getByRole("textbox", { name: "대화 제목" })
    await title.fill("안전한 새 제목")
    await title.press("Enter")
    await expect(
      page.getByText(
        "대화 제목을 바꾸지 못했습니다. 잠시 후 다시 시도해 주세요."
      )
    ).toBeVisible()
    await expect(title).toBeFocused()
    await title.press("Enter")
    await expect(
      page.getByText("안전한 새 제목", { exact: true })
    ).toBeVisible()
    expect((await fixtureState(page)).renameAttempts).toBe(2)

    const composer = page.getByRole("textbox", {
      name: "AI에게 보낼 메시지",
    })
    await composer.fill("취소 테스트")
    await composer.press("Enter")
    const stop = page.getByRole("button", { name: "응답 중지" })
    await expect(stop).toBeVisible()
    await expect
      .poll(async () => (await fixtureState(page)).commands.length)
      .toBe(1)
    await stop.click()
    await expect(stop).toBeHidden()
    await expect
      .poll(async () => (await fixtureState(page)).cancellations)
      .toEqual([
        {
          runId: "browser-run-1",
          threadId: "browser-thread-1",
        },
      ])

    await expectNoBrowserErrors(page, diagnostics)
    await attachEvidence(page, testInfo, "rename-cancel")
  })

  test("routes a thread-load rejection without leaking or rejecting globally", async ({
    page,
  }) => {
    const diagnostics = collectDiagnostics(page)
    await resetFixture(page, "load-error")
    await page.goto("/")
    await page
      .getByRole("button", { name: /브라우저 테스트 대화/ })
      .click()
    await expect(
      page.getByText(
        "에이전트 실행을 완료하지 못했습니다. 같은 대화에서 다시 시도해 주세요."
      )
    ).toBeVisible()
    await expect(page.getByText(/fixture_secret/)).toHaveCount(0)
    await expectNoBrowserErrors(page, diagnostics)
  })

  test("shows a redacted error after one cancellation credential refresh", async ({
    page,
  }) => {
    const diagnostics = collectDiagnostics(page)
    await resetFixture(page, "cancel-auth-failure")
    await page.goto("/")
    await page
      .getByRole("button", { name: /브라우저 테스트 대화/ })
      .click()
    const composer = page.getByRole("textbox", {
      name: "AI에게 보낼 메시지",
    })
    await composer.fill("취소 인증 갱신 실패 검증")
    await composer.press("Enter")
    const stop = page.getByRole("button", { name: "응답 중지" })
    await expect(stop).toBeVisible()
    await expect
      .poll(async () => (await fixtureState(page)).commands.length)
      .toBe(1)
    await stop.click()

    await expect
      .poll(async () => (await fixtureState(page)).cancellations.length)
      .toBe(2)
    await expect(
      page.getByText(
        "로그인 세션이 만료되었습니다. 다시 로그인해 주세요."
      )
    ).toBeVisible()
    await expect(page.locator("body")).not.toContainText(
      "PRIVATE_CANCEL_AUTH_BODY_MUST_NOT_RENDER"
    )
    expect(diagnostics.consoleIssues).toEqual([
      expect.stringContaining("401 (Unauthorized)"),
      expect.stringContaining("401 (Unauthorized)"),
    ])
    diagnostics.consoleIssues.length = 0
    await expectNoBrowserErrors(page, diagnostics)
  })

  test("reconnects the native APv2 content stream without duplicating the nested lifecycle", async ({
    page,
  }, testInfo) => {
    const diagnostics = collectDiagnostics(page)
    await resetFixture(page, "reconnect")
    await page.goto("/")
    await page
      .getByRole("button", { name: /브라우저 테스트 대화/ })
      .click()
    const composer = page.getByRole("textbox", {
      name: "AI에게 보낼 메시지",
    })
    await composer.fill("재연결 검증")
    await composer.press("Enter")

    await expect(
      page.getByText("브라우저 fixture 검색을 계속할까요?")
    ).toBeVisible({ timeout: 12_000 })
    await expect
      .poll(async () => (await fixtureState(page)).reconnectDisconnects)
      .toBe(1)
    await expect
      .poll(
        async () =>
          (await fixtureState(page)).streamSubscriptions.length
      )
      .toBeGreaterThanOrEqual(3)
    await expect(
      page.getByText("중첩 작업이 입력을 기다립니다.")
    ).toHaveCount(1)
    expect(diagnostics.consoleIssues).toEqual([
      expect.stringContaining(
        "503 (Service Unavailable)"
      ),
    ])
    diagnostics.consoleIssues.length = 0
    await expectNoBrowserErrors(page, diagnostics)
    await attachEvidence(page, testInfo, "native-reconnect")
  })

  test("never projects delayed history from a different nonce-resolved run", async ({
    page,
  }) => {
    const diagnostics = collectDiagnostics(page)
    await resetFixture(page, "delayed-replay")
    await page.goto("/")
    await page
      .getByRole("button", { name: /브라우저 테스트 대화/ })
      .click()
    const composer = page.getByRole("textbox", {
      name: "AI에게 보낼 메시지",
    })
    await composer.fill("지연 replay 상관관계 검증")
    await composer.press("Enter")

    await expect(
      page.getByText("브라우저 fixture 검색을 계속할까요?")
    ).toBeVisible({ timeout: 12_000 })
    await expect(page.locator("body")).not.toContainText(
      "STALE_BROWSER_HISTORY_MUST_NOT_RENDER"
    )
    await expectNoBrowserErrors(page, diagnostics)
  })

  test("keeps old nested activity and errors out of a new empty thread", async ({
    page,
  }) => {
    const diagnostics = collectDiagnostics(page)
    await resetFixture(page, "stale-source")
    await page.goto("/")
    await page
      .getByRole("button", { name: /브라우저 테스트 대화/ })
      .click()
    const composer = page.getByRole("textbox", {
      name: "AI에게 보낼 메시지",
    })
    await composer.fill("새 대화 source 격리 검증")
    await composer.press("Enter")
    await expect
      .poll(async () => (await fixtureState(page)).commands.length)
      .toBe(1)

    await page.getByRole("button", { name: "새 대화" }).click()
    await expect(
      page.getByRole("heading", {
        name: /블로그를 아는 AI가 아니라/,
      })
    ).toBeVisible()
    await expect
      .poll(async () => (await fixtureState(page)).staleSourceDeliveries)
      .toBeGreaterThanOrEqual(2)
    await expect(
      page.getByText("중첩 작업을 실행 중입니다.")
    ).toHaveCount(0)
    await expect(
      page.getByText(
        "에이전트 실행을 완료하지 못했습니다. 같은 대화에서 다시 시도해 주세요."
      )
    ).toHaveCount(0)
    await expect(page.locator("body")).not.toContainText(
      "PRIVATE_STALE_SOURCE_ERROR"
    )
    await expectNoBrowserErrors(page, diagnostics)
  })

  test("blocks an over-byte composer submission before it reaches APv2", async ({
    page,
  }) => {
    const diagnostics = collectDiagnostics(page)
    await resetFixture(page)
    await page.goto("/")
    await page
      .getByRole("button", { name: /브라우저 테스트 대화/ })
      .click()
    const composer = page.getByRole("textbox", {
      name: "AI에게 보낼 메시지",
    })
    await composer.fill("가".repeat(6_000))
    await page.getByRole("button", { name: "메시지 보내기" }).click()
    await expect(
      page.getByText("메시지가 너무 깁니다. 16KB 이하로 줄여 주세요.")
    ).toBeVisible()
    expect((await fixtureState(page)).commands).toEqual([])
    await expectNoBrowserErrors(page, diagnostics)
  })
})

test("bootstraps and resumes the public anonymous journey with the native runtime", async ({
  page,
}, testInfo) => {
  const diagnostics = collectDiagnostics(page)
  const tokenRequests: Array<{
    body: string | null
    intent: string | null
  }> = []
  await page.setViewportSize({ width: 390, height: 820 })
  await resetFixture(
    page,
    "public-root-state-fallback",
    "anonymous"
  )
  page.on("request", (request) => {
    if (
      new URL(request.url()).pathname ===
      "/api/anonymous-agent-token"
    ) {
      tokenRequests.push({
        body: request.postData(),
        intent: request.headers()["x-agent-token-intent"] ?? null,
      })
    }
  })

  await page.goto("/anonymous")
  await expect(
    page.getByTestId("public-anonymous-runtime-fixture")
  ).toBeVisible()
  await expect(
    page.getByRole("textbox", { name: "AI에게 보낼 메시지" })
  ).toBeVisible({ timeout: 12_000 })
  expect(tokenRequests).toEqual([
    { body: null, intent: "anonymous" },
    { body: null, intent: "anonymous" },
  ])

  await page.getByRole("button", { name: "대화 목록 열기" }).click()
  await page
    .getByRole("button", { name: /브라우저 테스트 대화/ })
    .click()
  await page.getByRole("button", { name: "Close" }).click()
  const composer = page.getByRole("textbox", {
    name: "AI에게 보낼 메시지",
  })
  const publicQuestion = "공개 익명 경로에서 한글 질문"
  const publicQuestionBubble = page.getByText(publicQuestion, {
    exact: true,
  })
  await composer.fill(publicQuestion)
  await composer.press("Enter")
  await expect(
    page.getByText("공개 fixture 검색을 계속할까요?")
  ).toBeVisible({ timeout: 12_000 })
  await expect(publicQuestionBubble).toHaveCount(1)
  const interruptedState = await fixtureState(page)
  expect(interruptedState.messageIdMappings).toHaveLength(1)
  const messageIdMapping = interruptedState.messageIdMappings[0]
  expect(messageIdMapping).toBeDefined()
  if (!messageIdMapping) {
    throw new Error("fixture did not record the guest message ID mapping")
  }
  expect(messageIdMapping.projectedId).toBe(messageIdMapping.clientId)
  expect(messageIdMapping.storedId).not.toBe(messageIdMapping.clientId)
  expect(messageIdMapping.storedId).toBe(
    `guest-user:${messageIdMapping.clientId}:00000000000000000000000000000001`
  )
  expect(interruptedState.stateRequests).toEqual(
    expect.arrayContaining([
      {
        authorization: true,
        interrupted: true,
        threadId: "browser-thread-1",
      },
    ])
  )

  await page.getByRole("button", { name: "승인", exact: true }).click()
  await expect(
    page.getByText("브라우저 fixture 응답이 완료되었습니다.")
  ).toBeVisible({ timeout: 12_000 })
  await expect(publicQuestionBubble).toHaveCount(1)
  const resumedState = await fixtureState(page)
  expect(resumedState.errors).toEqual([])
  expect(resumedState.responses).toEqual([
    expect.objectContaining({
      namespace: [],
      interrupt_id: "0123456789abcdef0123456789abcdef",
      response: "approve",
      metadata: expect.objectContaining({
        syshin_ui_submit_nonce: expect.any(String),
      }),
    }),
  ])

  await page.reload()
  await expect(
    page.getByRole("textbox", { name: "AI에게 보낼 메시지" })
  ).toBeVisible({ timeout: 12_000 })
  await page.getByRole("button", { name: "대화 목록 열기" }).click()
  await page
    .getByRole("button", { name: /브라우저 테스트 대화/ })
    .click()
  await page.getByRole("button", { name: "Close" }).click()
  await expect(publicQuestionBubble).toHaveCount(1)
  await expect(
    page.getByText("브라우저 fixture 응답이 완료되었습니다.")
  ).toBeVisible()
  expect(tokenRequests).toEqual([
    { body: null, intent: "anonymous" },
    { body: null, intent: "anonymous" },
    { body: null, intent: "anonymous" },
  ])
  await expectA11yClean(page)
  await expectNoBrowserErrors(page, diagnostics)
  await attachEvidence(page, testInfo, "public-anonymous-bootstrap")
})

test("retries the public anonymous bootstrap without a challenge", async ({
  page,
}, testInfo) => {
  const diagnostics = collectDiagnostics(page)
  const tokenRequests: Array<string | null> = []
  const externalChallengeRequests: string[] = []
  let rejectFirstBootstrap = true
  await page.setViewportSize({ width: 390, height: 820 })
  await resetFixture(page, "default", "anonymous")
  page.on("request", (request) => {
    if (request.url().includes("challenges.cloudflare.com")) {
      externalChallengeRequests.push(request.url())
    }
  })
  await page.route("**/api/anonymous-agent-token", async (route) => {
    tokenRequests.push(route.request().postData())
    if (rejectFirstBootstrap) {
      rejectFirstBootstrap = false
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "cache-control": "no-store" },
        body: JSON.stringify({ error: "fixture unavailable" }),
      })
      return
    }
    await route.fallback()
  })

  await page.goto("/anonymous")
  await expect(
    page.getByRole("heading", {
      name: "공개 체험에 연결하지 못했습니다",
    })
  ).toBeVisible()
  expect(tokenRequests).toEqual([null])

  await page.getByRole("button", { name: "다시 연결" }).click()
  await expect(
    page.getByRole("textbox", { name: "AI에게 보낼 메시지" })
  ).toBeVisible({ timeout: 12_000 })
  await expect.poll(() => tokenRequests.length).toBe(3)
  expect(tokenRequests).toEqual([null, null, null])
  expect(externalChallengeRequests).toEqual([])

  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(
    dimensions.clientWidth
  )
  await expectA11yClean(page)
  await expectNoBrowserErrors(page, diagnostics)
  await attachEvidence(page, testInfo, "public-anonymous-retry")
})

test("has no horizontal overflow at supported widths and honors reduced motion", async ({
  browser,
}, testInfo) => {
  test.setTimeout(60_000)
  for (const width of [320, 390, 768, 1440]) {
    const context = await browser.newContext({
      reducedMotion: "reduce",
      viewport: { width, height: 820 },
    })
    const page = await context.newPage()
    const diagnostics = collectDiagnostics(page)
    await resetFixture(page)
    await page.goto("/")
    await expect(
      page.getByTestId("production-native-runtime-fixture")
    ).toBeVisible()
    if (width < 768) {
      await page
        .getByRole("button", { name: "대화 목록 열기" })
        .click()
    }
    await page
      .getByRole("button", { name: /브라우저 테스트 대화/ })
      .click()
    if (width < 768) {
      await page.getByRole("button", { name: "Close" }).click()
    }
    const composer = page.getByRole("textbox", {
      name: "AI에게 보낼 메시지",
    })
    await composer.fill(`반응형 ${width}px 검증`)
    await composer.press("Enter")
    await expect(
      page.getByText("브라우저 fixture 검색을 계속할까요?")
    ).toBeVisible()
    const dimensions = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }))
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(
      dimensions.clientWidth
    )
    const reducedMotionControl =
      width < 768
        ? page.getByRole("button", { name: "대화 목록 열기" })
        : page.getByRole("button", { name: "새 대화" })
    expect(
      await reducedMotionControl.evaluate(
        (element) => getComputedStyle(element).transitionProperty
      )
    ).toBe("none")
    await expectA11yClean(page)
    await expectNoBrowserErrors(page, diagnostics)
    await testInfo.attach(`responsive-${width}-${revision}.png`, {
      body: await page.screenshot(),
      contentType: "image/png",
    })
    await context.close()
  }
})
