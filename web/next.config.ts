import type { NextConfig } from "next";
import { withBotId } from "botid/next/config";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  serverExternalPackages: [
    "@beoe/rehype-graphviz",
    "@beoe/rehype-d2",
    "@beoe/rehype-code-hook",
    "@beoe/rehype-code-hook-img",
    "@hpcc-js/wasm",
    "@node-rs/xxhash",
  ],
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'www.google.com',
        pathname: '/s2/favicons**',
      },
    ],
  },
};

export default withBotId(nextConfig);
