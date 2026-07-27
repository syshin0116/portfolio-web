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
  renameAttempts: number
  responses: Array<{
    interrupt_id?: unknown
    namespace?: unknown
    response?: unknown
  }>
  revision: string
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
const revision =
  process.env.GITHUB_SHA?.trim() ||
  process.env.TEST_REVISION?.trim() ||
  "local"

async function resetFixture(
  page: Page,
  scenario: "default" | "load-error" = "default"
): Promise<void> {
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
    body: await page.screenshot({ fullPage: true }),
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
      nodes: violation.nodes.map((node) => node.target),
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
    ).toBeVisible()
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
      {
        namespace: ["nested_subgraph:browser-task"],
        interrupt_id: "browser-interrupt-1",
        response: "approve",
      },
    ])

    await approve.click()
    await expect(
      page.getByText("브라우저 fixture 응답이 완료되었습니다.")
    ).toBeVisible()
    expect((await fixtureState(page)).responses).toEqual([
      {
        namespace: ["nested_subgraph:browser-task"],
        interrupt_id: "browser-interrupt-1",
        response: "approve",
      },
      {
        namespace: ["nested_subgraph:browser-task"],
        interrupt_id: "browser-interrupt-1",
        response: "approve",
      },
    ])
    expect((await fixtureState(page)).streamSubscriptions).toEqual([
      ...initialState.streamSubscriptions,
      ...initialState.streamSubscriptions,
      ...initialState.streamSubscriptions,
    ])

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
})

test("has no horizontal overflow at supported widths and honors reduced motion", async ({
  browser,
}, testInfo) => {
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
    await page
      .getByRole("button", { name: /브라우저 테스트 대화/ })
      .click()
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
    const newThread = page.getByRole("button", { name: "새 대화" })
    expect(
      await newThread.evaluate(
        (element) => getComputedStyle(element).transitionDuration
      )
    ).toBe("0s")
    await expectA11yClean(page)
    await expectNoBrowserErrors(page, diagnostics)
    await testInfo.attach(`responsive-${width}-${revision}.png`, {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    })
    await context.close()
  }
})
