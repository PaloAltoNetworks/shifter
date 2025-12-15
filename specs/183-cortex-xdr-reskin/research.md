# Research: Cortex XDR Portal Reskin

**Feature**: 183-cortex-xdr-reskin
**Date**: 2025-12-14

## CSS Architecture

### Decision: Single Unified Stylesheet

**Choice**: Create one `xdr-theme.css` file containing all Cortex XDR styles.

**Rationale**:
- Current templates use inline `<style>` blocks with duplicated CSS
- A single file enables consistent updates and easier maintenance
- CSS custom properties (variables) provide theming flexibility
- Reduces page weight by eliminating duplicate declarations

**Alternatives Considered**:
- **Per-template CSS files**: Rejected - creates maintenance burden, duplication
- **CSS-in-JS**: Rejected - not applicable to Django templates
- **Inline style updates only**: Rejected - doesn't address duplication issue

### Decision: CSS Custom Properties

**Choice**: Use CSS custom properties (variables) for all colors, spacing, and typography.

**Rationale**:
- Cortex reference CSS already uses this pattern (`.xdr-dark-theme` class)
- Enables easy color palette changes if needed
- Better maintainability than hardcoded hex values
- Modern browser support is universal

**Alternatives Considered**:
- **Sass/LESS variables**: Rejected - adds build complexity for no benefit
- **Hardcoded values**: Rejected - poor maintainability

## Typography

### Decision: Lato Font Family

**Choice**: Load Lato from Google Fonts with weights 100, 400, 600, 700.

**Rationale**:
- Cortex XSIAM uses Lato as primary font (per `assets/styles/login.css`)
- Current portal uses Roboto - must be replaced
- Google Fonts provides reliable CDN delivery

**Implementation**:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lato:wght@100;400;600;700&display=swap" rel="stylesheet">
```

## Component Patterns

### Decision: Pill-Shaped Primary Buttons

**Choice**: Primary buttons use `border-radius: 20px` with white background.

**Rationale**:
- Direct match to Cortex XDR button styling
- Distinguishes primary actions clearly
- Height 28px, padding 0 18px per reference

**Current State**:
- Existing buttons use `border-radius: 4px` with neon green background
- Change is purely visual, no behavioral impact

### Decision: Bottom-Border Form Inputs

**Choice**: Form inputs use bottom-border-only styling instead of full borders.

**Rationale**:
- Matches Cortex XDR input pattern
- Cleaner visual appearance
- Focus state changes bottom border color

**Current State**:
- Existing inputs have full borders with rounded corners
- HTML structure unchanged, only CSS styling

### Decision: Severity Badge Colors

**Choice**: Maintain semantic meaning while using Cortex-compatible styling.

**Mapping**:
| Severity | Current | New |
|----------|---------|-----|
| Critical | `#FF4444` (red) | `#FF5252` (XDR error) |
| High | `#FF8C00` (orange) | `#FFB300` (XDR warning) |
| Medium | `#FFD700` (yellow) | `#FFB300` with 50% opacity |
| Low | `#39FF14` (neon green) | `#0C6` (XDR success) |

**Rationale**:
- Preserves visual hierarchy for risk assessment
- Uses Cortex color tokens where possible
- Maintains accessibility contrast requirements

## Template Strategy

### Decision: Minimal HTML Changes

**Choice**: Preserve existing HTML structure; add/modify classes only.

**Rationale**:
- Per constitution principle III (CSS-First Implementation)
- Reduces risk of breaking functionality
- Easier to review changes (CSS-only diffs)

**Approach**:
1. Keep existing class names where they don't conflict
2. Add new classes for Cortex-specific styling
3. Remove inline styles, move to stylesheet
4. Add `xdr-dark-theme` class to root element

## Browser Support

### Decision: Modern Browsers Only

**Choice**: Target Chrome, Firefox, Safari, Edge (latest versions).

**Rationale**:
- Per constitution (no IE11 support required)
- Enables use of CSS Grid, Flexbox, custom properties
- Demo audience uses modern browsers

**Features Used**:
- CSS Custom Properties (variables)
- CSS Grid and Flexbox
- `calc()` for responsive typography
- `:focus-visible` for keyboard navigation
