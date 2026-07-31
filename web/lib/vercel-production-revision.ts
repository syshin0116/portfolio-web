const CANONICAL_HOST = "syshin0116.vercel.app"
const EXPECTED_PROJECT_ID = "prj_myD2BGgGc5oWtVPbb6rQc9hzfklS"
const FULL_SHA = /^[0-9a-f]{40}$/
const DEPLOYMENT_ID = /^dpl_[A-Za-z0-9]+$/
const VERCEL_HOST =
  /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.vercel\.app$/

type VercelEnvironment = Readonly<Record<string, string | undefined>>

export type VercelProductionRevision = Readonly<{
  schemaVersion: 1
  deploymentId: string
  deploymentUrl: string
  gitSha: string
}>

const EXPECTED_ENVIRONMENT = {
  VERCEL: "1",
  VERCEL_ENV: "production",
  VERCEL_TARGET_ENV: "production",
  VERCEL_PROJECT_ID: EXPECTED_PROJECT_ID,
  VERCEL_GIT_PROVIDER: "github",
  VERCEL_GIT_REPO_OWNER: "syshin0116",
  VERCEL_GIT_REPO_SLUG: "syshin0116.dev",
  VERCEL_GIT_COMMIT_REF: "main",
} as const

function hasExactProductionIdentity(environment: VercelEnvironment): boolean {
  return Object.entries(EXPECTED_ENVIRONMENT).every(
    ([key, expected]) => environment[key] === expected
  )
}

export function readVercelProductionRevision(
  environment: VercelEnvironment
): VercelProductionRevision | null {
  if (!hasExactProductionIdentity(environment)) return null

  const deploymentId = environment.VERCEL_DEPLOYMENT_ID
  const deploymentUrl = environment.VERCEL_URL
  const gitSha = environment.VERCEL_GIT_COMMIT_SHA

  if (!deploymentId || !DEPLOYMENT_ID.test(deploymentId)) return null
  if (!deploymentUrl || !VERCEL_HOST.test(deploymentUrl)) return null
  if (!gitSha || !FULL_SHA.test(gitSha)) return null

  return {
    schemaVersion: 1,
    deploymentId,
    deploymentUrl,
    gitSha,
  }
}

function noStoreHeaders(): HeadersInit {
  return {
    "cache-control": "no-store, max-age=0",
  }
}

export function createVercelProductionRevisionResponse(
  requestUrl: string,
  environment: VercelEnvironment = process.env
): Response {
  let hostname: string
  try {
    hostname = new URL(requestUrl).hostname
  } catch {
    return Response.json(
      { error: "deployment revision unavailable" },
      { status: 503, headers: noStoreHeaders() }
    )
  }

  if (hostname !== CANONICAL_HOST) {
    return Response.json(
      { error: "not found" },
      { status: 404, headers: noStoreHeaders() }
    )
  }

  const revision = readVercelProductionRevision(environment)
  if (!revision) {
    return Response.json(
      { error: "deployment revision unavailable" },
      { status: 503, headers: noStoreHeaders() }
    )
  }

  return Response.json(revision, { headers: noStoreHeaders() })
}
