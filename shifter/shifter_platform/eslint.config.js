import eslint from '@eslint/js';
import globals from 'globals';

export default [
  {
    ignores: ['**/*.test.js'],
  },
  eslint.configs.recommended,
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
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
];
