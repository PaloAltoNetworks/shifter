# Shifter Design System: Foundation Artifacts

Framework-neutral foundation for the SPA cutover, produced by issue
[#1299](https://github.com/Brad-Edwards/shifter/issues/1299). The full
contract (token inventory, component inventory, state matrix, accessibility
baseline, Django-coexistence guidance, and the migration map) lives in
[`../spa-design-system-foundation-1299.md`](../spa-design-system-foundation-1299.md).

This directory is the *reference implementation* of that contract: the tokens
and primitive component styles both the SPA and legacy Django templates consume,
plus a living style guide that renders them.

## Files

| File | Purpose |
| --- | --- |
| `tokens.css` | Design tokens as CSS custom properties. Primitive scales → semantic role tokens. Dark default, light via `[data-theme="light"]` / `prefers-color-scheme`, reduced-motion aware. **The single source of truth for the visual language.** |
| `components.css` | Framework-neutral primitive classes (`.ds-*`) that consume only semantic tokens. The class + token contract surfaces build on. |
| `index.html` | Living style guide. Renders every token and component; toggles light/dark. |
| `styleguide.css` | Page scaffold for the style guide only (not product styles). |
| `styleguide.js` | Theme toggle for the style guide (external file, no inline scripts). |

## Viewing the style guide

No build step. Open `index.html` directly, or serve the directory:

```bash
cd docs/design/design-system
python3 -m http.server 8791
# open http://localhost:8791/index.html
```

Use the header toggle to preview light and dark. Tab through the page to see
focus states.

## Consuming the tokens

Load `tokens.css` first, then `components.css`, then app/surface CSS:

```html
<link rel="stylesheet" href="tokens.css" />
<link rel="stylesheet" href="components.css" />
```

Components must reference **semantic** tokens only (for example
`--ds-color-accent`, `--ds-space-4`), never the raw ramps (`--ds-blue-500`,
`--ds-neutral-900`) or
literal values. That indirection is what lets a future visual-identity pass
reskin the product by editing token *values* in one file.

## Reskinning

To change the look without touching components: edit the **semantic** token
values in `tokens.css` (the `:root` dark block and the two light blocks). Keep
the raw ramps if you only want a new mapping; add/replace ramp values for a new
palette. Re-run the contrast check documented in the foundation doc before
claiming AA.

## Status

Stack-neutral foundation. It does not choose the SPA framework (that is issue
[#1300](https://github.com/Brad-Edwards/shifter/issues/1300)) and does not
modify the shipping portal templates or CSS (per-surface migration is later
work). See the foundation doc's migration map for how today's portal CSS maps
onto these tokens.
