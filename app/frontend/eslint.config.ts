import eslintConfigPrettier from 'eslint-config-prettier'
import pluginVue from 'eslint-plugin-vue'
import pluginVueA11y from 'eslint-plugin-vuejs-accessibility'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', 'coverage/**'],
  },
  // Order matters: typescript-eslint's recommended config applies to every
  // file (no `files` restriction) and would otherwise clobber Vue's
  // file-scoped parser assignment; loading it first means the later,
  // more-specific `**/*.vue` config from `pluginVue` wins for template files.
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
      },
    },
  },
  {
    files: ['**/*.vue', '**/*.ts'],
    plugins: {
      'vuejs-accessibility': pluginVueA11y,
    },
    rules: {
      ...pluginVueA11y.configs.recommended.rules,
      // The plugin's default requires EVERY strategy (both nesting the
      // control AND a for/id pair) to accept a label. This codebase uses
      // either strategy correctly on its own (BaseToggle nests its
      // checkbox; BaseField uses for/id) — requiring only one still
      // guarantees a real accessible name/control association.
      'vuejs-accessibility/label-has-for': ['error', { required: { some: ['nesting', 'id'] } }],
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'vue/multi-word-component-names': 'off',
      'vue/no-unused-properties': 'error',
    },
  },
  eslintConfigPrettier,
)
