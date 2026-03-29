import path from "node:path"

export const CONTENT_DIR =
  process.env.BLOG_CONTENT_PATH ||
  path.join(process.cwd(), "..", "content")
