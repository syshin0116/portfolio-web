import path from "node:path"
import { fileURLToPath } from "node:url"
import type { NextConfig } from "next"

const fixtureRoot = path.dirname(fileURLToPath(import.meta.url))
const webRoot = path.resolve(fixtureRoot, "../../..")

const nextConfig: NextConfig = {
  experimental: {
    externalDir: true,
  },
  turbopack: {
    root: webRoot,
  },
}

export default nextConfig
