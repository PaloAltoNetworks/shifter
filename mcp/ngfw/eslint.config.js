import security from "eslint-plugin-security";

export default [
  {
    files: ["**/*.js"],
    ignores: ["node_modules/**"],
    plugins: { security },
    rules: {
      ...security.configs.recommended.rules,
      // Keys are zod-validated enums (dev/prod) or internal iteration — not user input
      "security/detect-object-injection": "off",
    },
  },
];
