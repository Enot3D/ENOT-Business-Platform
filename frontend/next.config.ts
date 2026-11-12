import type { NextConfig } from "next";

const config: NextConfig = {
  poweredByHeader: false,
  async rewrites() {
    const origin = new URL(process.env.API_INTERNAL_ORIGIN ?? "http://127.0.0.1:8000");
    if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password
        || origin.pathname !== "/" || origin.search || origin.hash) {
      throw new Error("API_INTERNAL_ORIGIN must be an HTTP(S) origin");
    }
    return [{ source: "/api/v1/:path*", destination: `${origin.origin}/api/v1/:path*` }];
  },
};

export default config;
