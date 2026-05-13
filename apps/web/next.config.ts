import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // "standalone" copies a minimal set of node_modules + a server.js launcher
  // into .next/standalone. Required for the production Dockerfile, which
  // ships only that subset (image ~150 MB instead of ~1 GB).
  output: "standalone",
  experimental: {
    serverActions: { bodySizeLimit: "2mb" },
  },
};

export default nextConfig;
