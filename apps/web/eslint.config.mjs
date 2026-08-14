import { baseConfig } from "@influenceros/config/eslint";
// eslint-config-next 16 default-exports a flat-config array, not a factory.
import nextConfigs from "eslint-config-next";

/** @type {import("eslint").Linter.Config[]} */
const config = [
  ...baseConfig,
  ...nextConfigs,
  {
    files: ["**/*.{ts,tsx}"],
    rules: {
      // Next's own <Image> is not useful here: the app renders asset previews from
      // presigned S3 URLs whose dimensions are unknown until the asset is read.
      "@next/next/no-img-element": "off",
    },
  },
  {
    files: ["src/test/**", "**/*.test.{ts,tsx}", "e2e/**"],
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "no-console": "off",
    },
  },
];

export default config;
