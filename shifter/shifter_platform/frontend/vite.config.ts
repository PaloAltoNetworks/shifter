import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The SPA is served by Django/WhiteNoise from STATIC_ROOT under /static/spa/.
// Vite emits a content-hashed single bundle plus a build manifest; the Django
// SPA host view resolves the entry through the
// WhiteNoise staticfiles manifest. See docs/architecture/spa-cutover-architecture-1300.md.
export default defineConfig({
  base: "/static/spa/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: fileURLToPath(new URL("../static/spa", import.meta.url)),
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: fileURLToPath(new URL("./src/main.tsx", import.meta.url)),
      // Single bundle: avoids WhiteNoise re-hashing breaking split-chunk URLs
      // that are hard-coded inside the JS (the entry+css are resolved via the
      // manifest; there are no other asset references to rewrite).
      output: { inlineDynamicImports: true },
    },
  },
  server: {
    // Dev-only: proxy the API to the Django/Daphne backend so cookies and CSRF
    // behave same-origin during `npm run dev`. SPA-owned page paths are
    // client-routed by Vite's SPA fallback and must
    // NOT be proxied, or the client router never resolves them in dev (#1369).
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    coverage: {
      provider: "v8",
      reportsDirectory: "./coverage",
      reporter: ["text", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      // Only tests, test support, and the generated OpenAPI projection are
      // excluded. The first-party entrypoint (main.tsx) and composition root
      // stay measured (#1526).
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/api/schema.d.ts"],
      // Absolute non-regression floors, each one point under the measured
      // baseline to absorb run-to-run variance (the #1529 convention in
      // docs/dev/testing.md). Floors only stay level or rise; the SonarCloud
      // `raes-strict` gate owns the complementary 80% changed-code ratchet.
      thresholds: {
        statements: 79,
        branches: 70,
        functions: 74,
        lines: 81,
      },
    },
  },
});
