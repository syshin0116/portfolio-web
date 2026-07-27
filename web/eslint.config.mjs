import { fixupConfigRules } from "@eslint/compat"
import { defineConfig, globalIgnores } from "eslint/config"
import nextVitals from "eslint-config-next/core-web-vitals"
import nextTypescript from "eslint-config-next/typescript"

// The pinned Next flat config bundles plugins that call RuleContext methods removed in ESLint 10.
export default defineConfig([
  ...fixupConfigRules(nextVitals),
  ...fixupConfigRules(nextTypescript),
  {
    rules: {
      "react-hooks/purity": "off",
      "react-hooks/refs": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },
  globalIgnores([
    ".next/**",
    ".generated/**",
    "tests/browser/fixture/.next/**",
    "test-results/**",
    "playwright-report/**",
    "out/**",
    "build/**",
    "public/pagefind/**",
    "next-env.d.ts",
  ]),
])
