# SPA Design System Foundation

Date: 2026-07-03

Issue: [#1299](https://github.com/Brad-Edwards/shifter/issues/1299) (SPA
cutover: design system foundation)

Status: Design artifact for review

Architecture preflight:
[`docs/architecture/spa-design-system-foundation-preflight-1299.md`](../architecture/spa-design-system-foundation-preflight-1299.md)

Reference implementation:
[`docs/design/design-system/`](design-system/) (`tokens.css`,
`components.css`, `index.html`)

## Purpose

This document is the design-system foundation for the SPA cutover. It defines
the reusable visual language (tokens), the component contract (inventory plus
state matrix), the accessibility baseline, the ownership model, the plan for
coexisting with legacy Django templates during phased migration, and the map
from today's static CSS to the new system.

It is a **contract**, not an implementation of product screens. It is
**stack-neutral**: it does not choose the SPA framework or router. That decision
belongs to the SPA architecture issue
([#1300](https://github.com/Brad-Edwards/shifter/issues/1300)); this foundation
is written so it stays valid whatever #1300 selects. Component code in a chosen
framework, and the per-surface migrations, are later issues (for example the
Risk Register workspace, #1301 / #1302).

### Why start over

The current portal is a server-rendered Django MPA whose styling grew ad hoc:
42 per-page CSS files (~124 KB) with 402 hardcoded hex literals, an "interim"
token layer (`static/css/theme.css`) that carries redundant aliases, a second
competing token namespace in `sidebar.css`, no spacing/type/radius scales, five
near-duplicate `base.html` shells, and a dark-only theme hardwired with
`class="theme-dark"`. Accessibility is the weakest axis: no skip link, sparse
and inconsistent ARIA, and no focus-trap utility. There is no coherent system to
preserve, so this foundation is defined fresh. What is kept is the product
*tone* and the healthy backend: the versioned `/api/v1/` DRF surface with a
standardized error envelope.

## Design principles

1. **Operational, dense, utilitarian.** Range health, event progress, scenario
   readiness, and risk status must be scannable. Decoration is minimal; density
   is high; monospace carries technical values. This preserves the current
   product tone (per `docs/design/ux-002-oss-visual-identity-preflight.md`).
2. **One system, shared by both worlds.** The token layer is a single source of
   truth consumed by the SPA and by legacy Django templates. No SPA-only
   palette, no duplicate component library, no second token namespace.
3. **Semantic first, reskinnable.** Components consume semantic role tokens, not
   raw color ramps or literals. The final visual identity is deliberately open
   (ux-002 deferred it); a later identity pass reskins by editing token values
   in one file without touching components.
4. **Accessible by construction.** WCAG 2.1 AA contrast is built into the token
   pairs; visible focus, keyboard operability, reduced-motion, and
   screen-reader names are baseline requirements, not add-ons.
5. **UI state is not domain status, and not authorization.** Tokens express
   generic UI intents (success/warning/danger/info/neutral); domain statuses map
   onto them. A disabled or hidden control is a presentation state only;
   services and endpoints remain the authoritative permission boundary.

## Token inventory

Tokens are CSS custom properties in
[`design-system/tokens.css`](design-system/tokens.css), which is the source of
truth for values. They are layered: primitive raw scales feed semantic role
tokens; components consume only the semantic layer.

```
primitive (raw scales)  ->  semantic (role tokens)  ->  component (.ds-*)
```

### Color

Raw ramps: `--ds-neutral-0..1000` (cool gray), `--ds-blue-50..900` (accent /
info), `--ds-green-*` (success), `--ds-amber-*` (warning), `--ds-red-*`
(danger). These are never consumed directly.

Semantic color roles (each mapped per theme):

| Group | Tokens | Role |
| --- | --- | --- |
| Surfaces | `--ds-color-bg`, `-bg-subtle`, `-surface`, `-surface-raised`, `-surface-sunken`, `-surface-hover`, `-surface-selected`, `-overlay` | App canvas through raised menus, input wells, row hover/selection, and modal scrim. |
| Text | `--ds-color-fg`, `-fg-muted`, `-fg-subtle`, `-fg-on-accent`, `-fg-link`, `-fg-link-hover` | Primary/secondary/tertiary text, text on accent fills, links. |
| Borders | `--ds-color-border-subtle`, `-border`, `-border-strong`, `-border-input` | Dividers of increasing weight; `-border-input` is the form-control outline and meets 3:1 (WCAG 1.4.11). |
| Accent | `--ds-color-accent`, `-accent-hover`, `-accent-active`, `-accent-subtle`, `-accent-fg` | Primary action fill and states, tinted background, accent text. |
| Focus / selection | `--ds-color-focus-ring`, `-selection-bg`, `-selection-fg` | Visible focus ring and text selection. |
| Status | `--ds-color-{success,warning,danger,info,neutral}-{fg,bg,border,solid,on-solid}` | Subtle (fg/bg/border) and solid (solid/on-solid) treatments per intent. |

### Typography

System font stacks (no web-font dependency, zero contributor friction):
`--ds-font-sans`, `--ds-font-mono`.

Scale (root 16px): `--ds-font-size-3xs` (11px) through `-3xl` (30px); default
body is `-sm` (14px), dense body is `-xs` (13px). Weights
`--ds-font-weight-{regular,medium,semibold,bold}`; line heights
`--ds-line-height-{tight,snug,normal}`; letter spacing
`--ds-letter-spacing-{tight,normal,wide}` (wide is for uppercase eyebrow
labels). Role classes in `components.css`: `.ds-page-title`, `.ds-section-title`,
`.ds-eyebrow`, `.ds-code`, `.ds-codeblock`.

### Spacing, radius, borders

Spacing is a 4px grid: `--ds-space-0`, `-px`, `-1` (4px) through `-16` (64px).
Radius: `--ds-radius-{none,sm,md,lg,xl,pill,circle}` (control default is `md`,
5px). Border widths: `--ds-border-width-{thin,thick}`.

### Elevation

`--ds-shadow-{xs,sm,md,lg,xl}`, tuned per theme (deeper in dark, softer in
light).

### Focus rings

Geometry: `--ds-focus-ring-width` (2px), `--ds-focus-ring-offset` (2px); color
is the semantic `--ds-color-focus-ring`. Applied as an `outline` on
`:focus-visible` so it never disappears without a replacement.

### Motion

`--ds-duration-{fast,base,slow}` (`120ms` / `180ms` / `260ms`) with
`--ds-ease-{standard,out,in}`. All durations collapse to `0ms` under
`@media (prefers-reduced-motion: reduce)`, and looping animations (spinner,
skeleton) stop.

### Z-index

A named scale so overlays compose predictably:
`--ds-z-{base,raised,sticky,dropdown,overlay,modal,popover,toast,tooltip}`.

### Layout

Logical, RTL-safe: `--ds-nav-width-collapsed`, `--ds-nav-width-expanded`,
`--ds-topbar-height`, `--ds-content-max-width`.

### Theming

`:root` is the dark (operational default) theme. `[data-theme="light"]` selects
light explicitly; `prefers-color-scheme: light` auto-applies light when no
theme is pinned (`:root:not([data-theme])`). Both light and dark are
first-class (satisfies UX-017). Token names carry no physical direction, so RTL
(UX-061) is supported by construction when components use logical properties.

### Semantic status colors and the domain mapping

The token layer stays generic. Domain statuses map onto the intents rather than
introducing their own colors:

| Domain concept | UI intent |
| --- | --- |
| Range: ready | success |
| Range: provisioning / draining | info |
| Range: degraded | warning |
| Range: failed | danger |
| Range: destroyed / stopped | neutral |
| Risk severity: critical | danger (solid) |
| Risk severity: high | warning (solid) |
| Risk severity: medium | info (solid) |
| Risk severity: low | neutral (solid) |
| Event / scenario: active, valid | success |
| Event / scenario: scheduled, pending validation | info |
| Event / scenario: draft, disabled | neutral |

Status is always conveyed by more than color (an icon, a dot plus a text label,
or a badge with text), so it is legible to color-blind users and in monochrome.

## Component inventory

Primitives live in [`design-system/components.css`](design-system/components.css)
as `.ds-*` classes and are rendered in every state in
[`design-system/index.html`](design-system/index.html). Ownership is either a
**shared primitive** (the design-system boundary) or a **shell/frame primitive**
(the shared platform navigation contract, per ADR-013). Feature modules compose
these; they do not fork them.

| Group | Components | Ownership |
| --- | --- | --- |
| App shell / frame | app shell grid, global top bar, role-aware side nav, nav group label, page header + primary actions, mode indicator, skip link | Shell (shared platform nav contract, ADR-013) |
| Navigation | breadcrumbs, tabs / contextual subnav | Shell / shared |
| Actions | button (primary / secondary / tertiary / destructive), sizes, icon-only, button group | Shared primitive |
| Forms | text input, textarea, select, checkbox, radio, switch, field wrapper (label / required / help / error) | Shared primitive |
| Data display | table (sortable header, hover, selected, zebra), card (header / body / footer), key-value detail panel, code / mono block | Shared primitive |
| Signals | badge (subtle + solid, per intent), tag (removable), status indicator (dot + label) | Shared primitive |
| Feedback | alert / banner (per intent), toast | Shared primitive |
| Overlays | dialog (confirm + destructive), drawer, dropdown menu, popover, tooltip | Shared primitive |
| States | empty state, skeleton, spinner, progress | Shared primitive |

The inventory covers the surfaces enumerated in the IA
(`docs/design/ux-003-information-architecture-sitemap.md`): CTF, Mission
Control, Scenario Editor, Risk Register, and Documentation, in both participant
and organizer modes. The shell components realize the ux-003 navigation model
(global frame, mode switching, side nav, top nav, breadcrumbs, contextual
subnav, and modals for confirmatory actions).

## State matrix

Every interactive component defines these states. `focus` is always a visible
ring (`:focus-visible`); `disabled` uses reduced opacity plus
`cursor: not-allowed` and removes pointer events; `loading` sets `aria-busy` and
shows a spinner; `error` pairs with `aria-invalid`; `permission-denied` renders
as disabled with an explanatory name or tooltip (never a silent hide, and never
a substitute for a server-side check).

| Component | default | hover | focus | active | disabled | loading | error | success | destructive-confirm | permission-denied | component-specific |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Button | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | — | ✓ (destructive variant) | ✓ | block, icon-only, sizes |
| Input / textarea / select | ✓ | ✓ | ✓ | — | ✓ | — | ✓ | — | — | ✓ (read-only) | placeholder |
| Checkbox / radio | ✓ | ✓ | ✓ | — | ✓ | — | ✓ | — | — | ✓ | checked, indeterminate |
| Switch | ✓ | ✓ | ✓ | — | ✓ | — | — | — | — | ✓ | checked |
| Table row | ✓ | ✓ | ✓ | — | — | ✓ (skeleton rows) | — | — | — | — | selected, sortable header |
| Tab | ✓ | ✓ | ✓ | — | ✓ | — | — | — | — | ✓ | selected (current) |
| Nav item | ✓ | ✓ | ✓ | — | — | — | — | — | — | ✓ (hidden or disabled) | current (`aria-current`) |
| Menu item | ✓ | ✓ | ✓ | — | ✓ | — | — | — | ✓ (danger variant) | ✓ | separator |
| Badge / status | ✓ | — | — | — | — | — | ✓ (danger) | ✓ | — | — | subtle vs solid, per intent |
| Alert / toast | ✓ | — | — | — | — | — | ✓ (danger) | ✓ | — | — | dismissible |
| Dialog | ✓ | — | ✓ (trapped) | — | — | ✓ | — | — | ✓ | — | destructive footer |

## Accessibility baseline

This is the minimum every component and surface must meet. It preserves the
current i18n strength (78 of 80 templates already use `{% trans %}`) and fixes
the current a11y gaps.

- **Keyboard navigation.** Everything interactive is reachable and operable by
  keyboard, in a logical tab order. Composite widgets (tabs, menus, the side
  nav, toolbars) use roving `tabindex` per the WAI-ARIA Authoring Practices.
  `Esc` closes overlays; arrow keys move within menus and tab lists;
  `Enter`/`Space` activate.
- **Visible focus.** A consistent focus ring on `:focus-visible` (tokenized);
  `outline: none` is never used without an equivalent replacement. Meets WCAG
  2.4.7 (focus visible), 2.4.11 (focus not obscured), and 2.4.13 (focus
  appearance). A **skip-to-content** link is the first tabbable element in the
  shell (the current portal has none).
- **Color contrast.** Text meets AA 4.5:1 (large text and UI component
  boundaries 3:1). The token pairs are verified (see Verification). Status is
  never color-only.
- **Reduced motion.** `prefers-reduced-motion` is honored via the motion tokens;
  looping animations stop.
- **Screen-reader names and structure.** Landmarks (`banner`, `nav`, `main`,
  `contentinfo`); every control has an accessible name (icon-only buttons
  require `aria-label`); a `.ds-visually-hidden` utility supplies names without
  visual noise; toasts and async status use `aria-live` (`role="status"` /
  `role="alert"`).
- **Form validation.** Errors are programmatically associated
  (`aria-describedby`), the field is marked `aria-invalid`, messages are text
  (not color-only), and focus moves to the first error on submit.
- **Per-component ARIA.** Follow the WAI-ARIA APG pattern for each widget:
  `dialog` (`role="dialog"`, `aria-modal`, focus trap, return focus on close),
  tabs (`tablist` / `tab` / `tabpanel`), menu (`menu` / `menuitem`), disclosure,
  `alert`, `switch`, `progressbar`.

## Component-ownership model (migration-safe)

- **Shared primitives** (buttons, inputs, table, badge, alert, dialog, and the
  rest of the inventory) are owned at the design-system boundary. They are the
  only place these shapes are defined.
- **Shell / navigation** is the shared, role-aware platform navigation contract
  (ADR-013). It is owned once, centrally, not re-implemented per app. The
  minimum side-nav item contract from ux-003 (`surface`, `audience`,
  `route_name`, `permission_policy`, `owner_app`, `purpose`) carries forward.
- **Feature modules** (a Risk Register table, a CTF scoreboard, a Scenario
  editor) **compose** primitives and shell slots. They may add surface-specific
  layout, but they do not introduce a new palette, a parallel component, or a
  second navigation system. This is the rule that keeps a half-migrated product
  from looking like two products.

## Django coexistence during phased migration

The SPA and Django templates will coexist while surfaces migrate one at a time.
The design guarantees visual continuity through the token layer and defers the
shell-hosting mechanics to #1300.

- **Shared token stylesheet is the contract.** `tokens.css` is published once
  and consumed by both worlds: the SPA build imports it, and the Django base
  templates link it via `{% static %}` through the existing WhiteNoise /
  manifest pipeline. A surface looks consistent regardless of which world
  renders it, because both read the same tokens.
- **Rationalize, do not fork.** The current `theme.css` interim tokens and the
  `sidebar.css` `--nav-*` namespace collapse into the semantic tokens here (see
  the migration map). There is exactly one token system afterward.
- **Shell-hosting options (decision owned by #1300).** Three viable models: (a)
  Django renders the shared shell and the SPA mounts into a content region per
  migrated route; (b) the SPA renders the shell and legacy routes load as
  full-page Django views under a shared header; (c) a hard route split where
  some paths are SPA and others Django, unified by the shared token stylesheet
  and a shared header contract. This foundation is compatible with all three;
  the binding choice, plus route ownership and retirement criteria, is #1300's
  scope. The token contract is what makes the choice low-risk either way.
- **Auth and API boundaries are unchanged.** Browser calls stay on Django
  session auth with CSRF; the SPA consumes the canonical `/api/v1/` surface and
  the `shared.api.errors` envelope. No frontend-held bearer tokens for browser
  sessions, no CSRF exemptions, no domain logic or validation duplicated in the
  frontend. Detailed API-client conventions (retries, polling, pagination) are
  #1300's scope.
- **Preserve existing checks.** i18n (`{% trans %}`), `collectstatic`, stylelint,
  ESLint, Jest, import boundaries, and ADR guard must not be weakened. Do not
  reintroduce inline styles or template-local `<style>` blocks.

## Migration map (current static CSS/templates to the new system)

| Current pattern | Location | New system target | Notes |
| --- | --- | --- | --- |
| Interim `:root` tokens with redundant aliases (`--theme-bg`/`--theme-background`, `--theme-primary`/`--theme-brand`/`--theme-on-background`) | `static/css/theme.css` | Semantic tokens in `tokens.css` (`--ds-color-bg`, `--ds-color-accent`, ...) | Collapse each alias set to one semantic token. |
| Second token namespace (`--nav-*`, its own `--spacing-*`, `--border-radius-xs`) | `static/css/sidebar.css` | Shell tokens + `--ds-space-*` / `--ds-radius-*` | Remove the competing namespace; side nav consumes shared tokens. |
| Five near-duplicate shells | `templates/{mission_control,ctf,scenario_editor,risk_register,documentation}/base.html` | One app shell + top bar + side nav (shell primitives) | Single frame, role-aware. |
| Icon sidebar partial | `templates/partials/icon_sidebar.html` | Side navigation component (role-aware) | Realizes the ux-003 side-nav contract. |
| Per-page stylesheets with hardcoded hex (402 literals) | `static/css/mc-*.css`, `ctf-*.css`, `ngfw-*.css`, ... | Shared primitives (table, card, form, badge) + thin surface CSS; all colors via semantic tokens | Decompose repeated shapes into primitives; replace literals with tokens. |
| Ad hoc status badges | `templates/ctf/includes/*`, page CSS | `.ds-badge` / `.ds-status` with intent variants | Map domain status to UI intent. |
| Confirm dialogs / modals | scattered page CSS + JS | `.ds-dialog` with `.ds-overlay`, focus trap | Confirmatory + destructive patterns. |
| Hardcoded spacing / radius literals (`padding: 24px`, `border-radius: 4px`) | across `static/css/**` | `--ds-space-*`, `--ds-radius-*` | 4px grid + radius scale. |
| Dark-only theme (`class="theme-dark"`) | every base template | `[data-theme]` + light/dark tokens | Adds light mode; keeps dark default. |
| No skip link, sparse ARIA, no focus trap | templates + JS | Accessibility baseline above | Skip link, landmarks, `:focus-visible` ring, dialog focus trap. |

## Verification

- **Contrast (WCAG AA).** All 50 semantic text-on-surface and UI-boundary pairs
  across both themes were checked against WCAG 2.1 (4.5:1 for text, 3:1 for
  large text / UI components) and pass. The check is a small relative-luminance
  script over the token values; re-run it after any token-value change (and
  after a reskin) before claiming AA.
- **Rendering.** `design-system/index.html` renders every token and every
  component in both themes with no build step; the theme toggle switches
  `data-theme`. It was verified rendering correctly in light and dark.
- **Repo gates.** `python3 scripts/adr_guard/adr_guard.py --all --level ci` and
  `git diff --check` pass. The new CSS is written to satisfy
  `stylelint-config-standard`. This change is docs/design only: it does not
  touch the shipping portal templates, static CSS/JS, i18n, `collectstatic`, or
  the import boundaries.

## Relationship to #1300 and open items

This foundation intentionally leaves the following to the SPA architecture issue
(#1300): the frontend stack and build/deploy integration, the shell-hosting
model and route ownership, the API-client conventions (retries, polling,
pagination, form-validation wiring to the envelope), websocket / Guacamole /
upload / download / long-running-action handling, the module migration order and
route-retirement criteria, and any new CI checks (for example an automated a11y
gate, which the current CI lacks). When #1300 lands, component code in the chosen
framework adopts these token and class contracts unchanged.

## Maintenance rule

When a new shared UI shape or token is introduced:

1. Add or extend the token in `tokens.css` at the correct layer (raw ramp vs
   semantic role); components consume the semantic token only.
2. Add the primitive to `components.css` and render it, in all its states, in
   `index.html`.
3. Update the component inventory, state matrix, and (if the shape has a domain
   meaning) the domain-status mapping in this document.
4. Re-run the contrast check for any new or changed color pair.
5. Keep this document, the IA (ux-003), and the taxonomy in sync when a new
   surface or cross-cutting concept appears.
