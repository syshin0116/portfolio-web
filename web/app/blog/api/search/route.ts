import { getAllMarkdownFiles, buildSearchIndex } from "nuartz"
import { CONTENT_DIR } from "@/lib/content"

export const dynamic = "force-static"

export async function GET() {
  const files = await getAllMarkdownFiles(CONTENT_DIR)
  const entries = buildSearchIndex(files)
  return Response.json(entries)
}
