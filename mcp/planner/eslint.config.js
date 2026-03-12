import security from "eslint-plugin-security";

export default [
  {
    files: ["**/*.js"],
    ignores: ["node_modules/**"],
    plugins: { security },
    rules: {
      ...security.configs.recommended.rules,
      // Plan/phase/step IDs are internally generated short UUIDs, not user input
      "security/detect-object-injection": "off",
    },
  },
];
