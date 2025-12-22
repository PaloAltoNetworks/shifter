# Design System

Cortex XDR theme. Dark UI matching PANW product family.

## CSS Files

| File | Purpose |
|------|---------|
| `xdr-theme.css` | Base theme, colors, typography, components |
| `xdr-sidebar.css` | Left navigation |
| `xdr-dropdown.css` | Dropdown menus |
| `terminal.css` | Terminal page layout |

## Colors

From `xdr-theme.css`:

| Variable | Value | Usage |
|----------|-------|-------|
| `--xdr-background` | `#1f1f1f` | Page background |
| `--xdr-surface` | `#151515` | Cards, panels |
| `--xdr-text` | `#eaebeb` | Primary text |
| `--xdr-text-secondary` | `#b8b8b8` | Secondary text |
| `--xdr-border` | `#333` | Borders |
| `--xdr-hover` | `rgba(255,255,255,0.08)` | Hover states |

Status colors:
- Online/success: `#00d26a`
- Offline: `#707070`
- Error: `#ff4d4f`
- Links: `#128df3`

## Typography

Font: Lato, Assistant, sans-serif

| Element | Size | Weight |
|---------|------|--------|
| Page title | 20px | 600 |
| Card title | 14px | 600 |
| Body | 14px | 400 |
| Table headers | 12px | 600, uppercase |
| Buttons | 12px | 600 |

## Components

### Buttons

White pill style (Cortex XDR pattern):

- Height: 28px
- Border-radius: 20px
- Primary: white background, black text
- Secondary: transparent, border

### Cards

- Background: `--xdr-surface`
- Border: 1px solid `--xdr-border`
- Border-radius: 4px
- Padding: 16px

### Status Indicators

8px dot with color:
- `.status-online` - green
- `.status-offline` - gray
- `.status-error` - red

## Layout

- Min width: 1024px
- Left nav: 56px (collapsed)
- Main content padding: 24px
