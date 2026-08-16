import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vitest/config'

/**
 * The test harness for the static console.
 *
 * There is no `vite.config.ts` to merge with any more — the app is emitted by
 * `tsc` as browser-native ES modules — so Vite appears here only as Vitest's
 * own transform pipeline, never in a build. It resolves the `.js` specifiers
 * that `src/` is required to write (see `tsconfig.json`) back to their `.ts`
 * sources, which is why the suite can import the app's modules unmodified.
 *
 * `coverage.include` is deliberately narrow. The 100% gate is a promise about
 * the code this suite actually covers, and a repo-wide 100% threshold on a
 * codebase whose test pass has only just started would fail on day one and be
 * turned off by the second day. Files join the list as tests for them land.
 */
export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    root: fileURLToPath(new URL('./', import.meta.url)),
    include: ['tests/**/*.test.ts'],
    exclude: ['node_modules', 'dist'],
    setupFiles: ['tests/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      include: [
        'src/components/sdrs/noticeList.ts',
        'src/state/sdrsStore.ts',
        'src/utils/locationValidation.ts',
        'src/state/locationStore.ts',
        'src/components/location/locationPanel.ts',
        'src/state/wiredStore.ts',
      ],
      thresholds: {
        'src/components/sdrs/noticeList.ts': {
          lines: 100,
          statements: 100,
          functions: 100,
          branches: 100,
        },
        // The Sentry Location trio joins the gate whole: all three landed with
        // their tests, so unlike `sdrsStore.ts` there is no untested half whose
        // absence a threshold would be measuring.
        'src/utils/locationValidation.ts': {
          lines: 100,
          statements: 100,
          functions: 100,
          branches: 100,
        },
        'src/state/locationStore.ts': {
          lines: 100,
          statements: 100,
          functions: 100,
          branches: 100,
        },
        'src/components/location/locationPanel.ts': {
          lines: 100,
          statements: 100,
          functions: 100,
          branches: 100,
        },
        // Wired sharing's store (ADR-0014). Whole-file 100%, because every
        // branch in it is one an operator can reach: each error code, each of
        // the three lease-read outcomes, and each mutation's success and
        // failure path.
        'src/state/wiredStore.ts': {
          lines: 100,
          statements: 100,
          functions: 100,
          branches: 100,
        },
        // The store is covered here only for its notice log — `applyNotice`,
        // `dismissNotice` and `deviceLabel`. Its device, port, hotspot and
        // patch paths have no tests yet, so a whole-file threshold would
        // measure their absence rather than this suite's completeness.
        'src/state/sdrsStore.ts': {
          lines: 0,
          statements: 0,
          functions: 0,
          branches: 0,
        },
      },
    },
  },
})
