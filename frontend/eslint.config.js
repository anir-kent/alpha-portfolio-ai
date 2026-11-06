// @ts-check
import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores(["dist", "src/api/schema.d.ts"]), // build output and generated API types
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      prettier, // formatting belongs to Prettier, not the linter
    ],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    rules: {
      // `_name` marks a binding left unused on purpose, e.g. a field dropped by a rest destructure
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_", ignoreRestSiblings: true }],
      // Fast refresh is a dev convenience: a module that shares a helper with its components only reloads in full
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
  { files: ["src/main.tsx"], rules: { "react-refresh/only-export-components": "off" } }, // the entry point exports nothing
]);
