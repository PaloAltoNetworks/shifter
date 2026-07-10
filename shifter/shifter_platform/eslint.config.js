import eslint from '@eslint/js';
import globals from 'globals';
import security from 'eslint-plugin-security';

export default [
  {
    ignores: ['**/*.test.js', 'static/js/vendor/**'],
  },
  eslint.configs.recommended,
  security.configs.recommended,
  {
    files: ['static/js/**/*.js'],
    languageOptions: {
      globals: {
        ...globals.browser,
        // xterm.js globals loaded via script tags
        Terminal: 'readonly',
        FitAddon: 'readonly',
        WebLinksAddon: 'readonly',
      },
    },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^init' }],
    },
  },
  {
    // jest test doubles for the Firebase modular SDK (used only under jest).
    files: ['static/js/__mocks__/**/*.js'],
    languageOptions: {
      globals: {
        ...globals.jest,
      },
    },
  },
];
