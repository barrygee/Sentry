import eslintConfigPrettier from 'eslint-config-prettier'
import tseslint from 'typescript-eslint'

/**
 * Lint config for the static TypeScript UI.
 *
 * `eslint-plugin-vue` and `eslint-plugin-vuejs-accessibility` are gone with the
 * Vue SPA. Losing the second one is a real reduction in cover: it caught
 * missing labels, unlabelled controls and handlers on static elements
 * *statically*, and it only ever worked on `.vue` templates — no equivalent
 * rule set exists for markup built imperatively with `core/dom.ts`.
 *
 * The replacement is runtime rather than static: axe, run against the rendered
 * DOM. Component suites under `tests/` do this per component (see
 * `tests/components/noticeList.test.ts`); a Playwright pass over the assembled
 * app is still owed. Anything that relied on a lint rule to stay accessible has
 * to be asserted there instead, which is why those suites are not optional.
 */
export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', 'coverage/**', '.legacy-vue/**'],
  },
  ...tseslint.configs.recommended,
  {
    files: ['**/*.ts'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      // Single-letter identifiers are banned project-wide: a name has to state
      // the thing's role, including loop counters, lambda parameters and catch
      // bindings.
      'id-length': ['error', { min: 2, properties: 'never' }],
    },
  },
  eslintConfigPrettier,
)
