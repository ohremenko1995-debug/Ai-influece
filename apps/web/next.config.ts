import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // `packages/*` ship TypeScript source, not build output, so Next must compile them.
  transpilePackages: ["@influenceros/ui", "@influenceros/types"],
  typedRoutes: true,
  // Note: Next 16 no longer runs ESLint as part of `next build`, so linting is a
  // separate gate (`pnpm lint`) and there is nothing to opt out of here.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default config;
