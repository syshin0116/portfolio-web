import { createVercelProductionRevisionResponse } from "@/lib/vercel-production-revision"

export const dynamic = "force-dynamic"
export const revalidate = 0
export const runtime = "nodejs"

export function GET(request: Request): Response {
  return createVercelProductionRevisionResponse(request.url)
}
