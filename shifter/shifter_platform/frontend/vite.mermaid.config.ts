import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vite";

// Standalone build for the documentation Mermaid renderer (#1520, ADR-036).
//
// Kept separate from the SPA build (vite.config.ts) because that build inlines
// all dynamic imports into a single entry, which cannot coexist with a second
// rollup input. Mermaid lazily imports ~23 diagram chunks; `inlineDynamicImports`
// folds them into one self-contained, content-hashed module so WhiteNoise can
// fingerprint it without breaking hard-coded split-chunk URLs. Output lands in
// <static>/spa/mermaid so collectstatic + WhiteNoise serve it same-origin, which
// lets ADR-036's CSP drop public package CDNs as script authorities.
//
// Build order matters: the SPA build (emptyOutDir over <static>/spa) MUST run
// before this one, which writes the <static>/spa/mermaid subtree.
export default defineConfig({
  base: "/static/spa/mermaid/",
  build: {
    outDir: fileURLToPath(new URL("../static/spa/mermaid", import.meta.url)),
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: fileURLToPath(new URL("./src/mermaid-entry.ts", import.meta.url)),
      output: { inlineDynamicImports: true },
    },
  },
});
