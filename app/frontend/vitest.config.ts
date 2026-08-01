import { fileURLToPath } from 'node:url'

import { defineConfig, mergeConfig } from 'vitest/config'

import viteConfig from './vite.config.js'

// Test harness only — per the project testing-timing rule, no test files are
// written during feature build. This wires the runner (jsdom + vue-test-utils
// + a 100% coverage gate) so the ship-time test pass can run immediately.
// `viteConfig` already registers `@vitejs/plugin-vue`, so it isn't repeated here.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      root: fileURLToPath(new URL('./', import.meta.url)),
      exclude: ['node_modules', 'dist'],
      coverage: {
        provider: 'v8',
        reporter: ['text', 'html', 'lcov'],
        thresholds: {
          lines: 100,
          statements: 100,
          functions: 100,
          branches: 100,
        },
        exclude: ['src/api/types.ts', 'src/main.ts', '**/*.d.ts'],
      },
    },
  }),
)
