# node-forge (local no-op replacement)

`gcip-cloud-functions` declares `node-forge` as a transitive dependency but never
imports it at runtime (`package/lib/**` contains no `require('node-forge')`), and
this function does not use it either. The Identity Platform blocking-event JWT is
verified through `jsonwebtoken` (Node's built-in `crypto`), not node-forge.

The published node-forge (`<= 1.4.0`, currently the latest) has an unpatched HIGH
advisory, CVE-2026-85393 / GHSA-86w9-cpqp-85rv (an incomplete fix for
CVE-2026-33894), with no fixed release available (upstream PR
`digitalbazaar/forge#1152` is unmerged). To avoid shipping dormant vulnerable
crypto, the unused implementation is replaced with this empty module.

## How it is wired

`package.json` declares a direct dependency:

```json
"dependencies": { "node-forge": "file:./vendor/node-forge" }
```

npm installs this local copy and, because its version satisfies the SDK's
`node-forge@^1.3.1` range, dedupes to this single copy, so no published
(vulnerable) node-forge enters the dependency tree or the committed lockfile.

## Version rationale

The version is `1.4.1` deliberately: it is the first version past the affected
range (`<= 1.4.0`) while still satisfying `^1.3.1`, so npm resolves to this local
copy and the advisory does not match. It is **not** the upstream 1.4.1 release
(none exists yet); it is an empty local shim.

## Removal path

When upstream publishes a fixed node-forge release (expected `1.4.1`, via
`digitalbazaar/forge#1152`), delete this folder and the `node-forge` entry in
`package.json`; `gcip-cloud-functions` will then pull the fixed release directly.
If a future `gcip-cloud-functions` version starts importing node-forge, this shim
will fail loudly and must be removed in favour of the real dependency.
