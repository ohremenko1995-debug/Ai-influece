// Shared ESLint rules for every workspace package.
//
// Deliberately small. The rules here encode decisions that were argued about
// once — everything else is left to TypeScript, which already catches it.
import js from "@eslint/js";
import tseslint from "typescript-eslint";

/** @type {import("eslint").Linter.Config[]} */
export const baseConfig = [
  {
    ignores: [
      "**/node_modules/**",
      "**/.next/**",
      "**/dist/**",
      "**/coverage/**",
      "**/playwright-report/**",
      "**/test-results/**",
      "**/src/generated/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      // An unused variable is either a mistake or a rename away from being one.
      // `_`-prefixed names opt out, for deliberately ignored callback arguments.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "all" },
      ],
      // `any` erases the reason this project runs in strict mode.
      "@typescript-eslint/no-explicit-any": "error",
      // Console output in a browser bundle is either debugging left behind or
      // data leaking into a place users can read.
      "no-console": ["error", { allow: ["warn", "error"] }],
      eqeqeq: ["error", "always", { null: "ignore" }],
      "prefer-const": "error",
      "no-var": "error",
    },
  },
];

export default baseConfig;
