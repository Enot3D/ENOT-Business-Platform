import { isIP } from "node:net";
import type { NextConfig } from "next";

const config: NextConfig = {
  poweredByHeader: false,
  async rewrites() {
    const isVercel = process.env.VERCEL === "1" || Boolean(process.env.VERCEL_ENV);
    const apiOrigin = process.env.API_INTERNAL_ORIGIN;
    if (isVercel && !apiOrigin) {
      throw new Error("Set API_INTERNAL_ORIGIN to the public Railway HTTPS origin on Vercel");
    }
    const origin = new URL(apiOrigin ?? "http://127.0.0.1:8000");
    if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password
        || origin.pathname !== "/" || origin.search || origin.hash) {
      throw new Error("API_INTERNAL_ORIGIN must be an HTTP(S) origin");
    }
    const host = origin.hostname.replace(/^\[|\]$/g, "").replace(/\.$/, "");
    if (isVercel && (origin.protocol !== "https:" || !host.includes(".") || isIP(host)
        || /\.(internal|local|localhost)$/.test(host))) {
      throw new Error("API_INTERNAL_ORIGIN must use a public HTTPS hostname on Vercel");
    }
    return [{ source: "/api/v1/:path*", destination: `${origin.origin}/api/v1/:path*` }];
  },
};

export default config;
