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
 * No replacement is coming. ADR-0011 dropped automated accessibility testing as
 * a requirement, so nothing enforces accessible markup here statically or at
 * runtime — the one `jest-axe` assertion in `tests/components/noticeList.test.ts`
 * is an example, not a rule. Accessible names, roles and focus management are
 * held in place by review alone. Worth knowing before assuming a lint failure
 * would have caught something.
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
