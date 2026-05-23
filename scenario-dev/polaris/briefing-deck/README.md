# Polaris briefing deck

Static, hand-authored HTML/CSS/JS slide deck used at event briefing time.

- `index.html` — slide content; each slide is one `<section class="slide">`
  with a `data-title` attribute. Add a slide by appending another
  `<section>` in the order it should appear.
- `styles.css` — single sheet scoped to the slide-component class hierarchy
  (`.slide`, `.slide--brief`, `.slide--mission`, `.slide--classification`,
  etc.). Add a new variant by adding a class and styling it under that
  selector; do not split per-slide.
- `deck.js` — keyboard navigation + simple ARIA progress hookup.
- `serve.sh` — `python3 -m http.server` wrapper so you can preview locally.
- `asset-inventory.md`, `script.md` — speaker notes and asset reference.

## Why this is left as a single HTML file

Issue #691 asks that large scenario assets either be **split for review**
or be **explicitly justified as authored/static artifacts**.

The deck is already split at the natural review unit: each `<section
class="slide">` is one slide, scanned independently. Each new slide is one
contiguous edit. CSS variants are scoped to slide-component classes so
adding a new variant touches one place. There is no compose / build step
to insert.

Splitting `index.html` into per-slide partials would require introducing
a template engine and a build target purely to produce the same HTML the
browser already loads in one request. That trade is not justified for a
deck that ships once per event and has no participant-facing dynamic
behavior.

If you find yourself wanting a build step here, that signals a real
component / template stack should appear instead (likely co-evolving with
#620's scenario-expressiveness work). Until then: append a `<section>`,
add a variant class if you need a new look, and re-run `./serve.sh` to
preview.
