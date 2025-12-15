# Cortex XDR Style Guide

Extracted from actual Cortex XDR production CSS (`assets/styles/login.css` and `assets/Cases - Cortex XDR_files/`).

---

## 1. Color System

### Primary Colors
| Variable | Value | Usage |
|----------|-------|-------|
| `--xdr-background` | `#1f1f1f` | Main page background |
| `--xdr-surface` | `#151515` | Cards, panels, sidebar |
| `--xdr-surface-secondary` | `#000` | Deepest layer (behind content) |
| `--xdr-surface-primary` | `#333` | Elevated interactive elements |
| `--xdr-tertiary-bg` | `#1f1f1f` | Same as background |
| `--xdr-background-primary` | `#1a1a1a` | Alternative background layer |

### Text Colors
| Variable | Value | Usage |
|----------|-------|-------|
| `--xdr-on-background` | `#eaebeb` | Primary text |
| `--xdr-on-background-secondary` | `#b8b8b8` | Secondary/muted text |
| `--xdr-disabled-text` | `#707070` | Disabled state text |
| `--xdr-placeholder` | `#929191` | Input placeholders |

### Border Colors
| Variable | Value | Usage |
|----------|-------|-------|
| `--xdr-border` | `#484848` | Standard borders |
| `--xdr-border-extra-soft` | `#333` | Subtle dividers |
| `--xdr-border-medium` | `#575757` | Medium emphasis borders |
| `--xdr-border-strong` | `#707070` | High emphasis borders |

### Interactive States
| Variable | Value | Usage |
|----------|-------|-------|
| `--xdr-hover` | `#333` | Hover state background |
| `--xdr-selected` | `#484848` | Selected state background |
| `--xdr-locked-bg` | `#484848` | Locked/pinned state |

### Accent Colors
| Variable | Value | Usage |
|----------|-------|-------|
| `--xdr-primary` | `#128df3` | Links ONLY (not UI elements) |
| `--xdr-link` | `#128df3` | Text links |
| Brand Green | `#0c6` / `#00cc66` | Logo, progress bars, accents |

### Semantic Colors
| Variable | Value | Usage |
|----------|-------|-------|
| Success | `#0C6` | Positive states |
| Warning | `#FFB300` | Warning states |
| Error | `#FF5252` | Error states |
| Orange | `#FA582D` | Alert/attention |

---

## 2. Shadows & Depth

### Shadow Variables
```css
--xdr-surface-box-shadow: #000;
--xdr-surface-box-shadow-dark: #000;
--xdr-surface-box-shadow-floating-object: rgba(0, 0, 0, 0.7);
--xdr-surface-box-shadow-secondary: #000;
```

### Shadow Patterns
| Element | Shadow |
|---------|--------|
| Floating panels | `box-shadow: 0 0 12px var(--xdr-surface-box-shadow-floating-object)` |
| Cards | `box-shadow: 0 0 12px rgba(0, 0, 0, 0.7)` |
| Dropdowns | `box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5)` |

---

## 3. Gradients

### Border Fade
```css
--xdr-border-fade: linear-gradient(90deg, #484848 46.3%, rgba(31, 31, 31, 0) 100%);
```
Used for fading dividers and borders.

### Selected Background Fade
```css
--xdr-selected-bg-fade: linear-gradient(90deg, #000 34.62%, rgba(0, 0, 0, 0) 88.57%);
```
Used for selected row backgrounds that fade out.

### Green Accent Gradients
```css
/* Left fade */
background: linear-gradient(270deg, #0C6 2.89%, rgba(255, 255, 255, 0) 96.58%);

/* Right fade */
background: linear-gradient(90deg, #0C6 2.89%, rgba(255, 255, 255, 0) 96.58%);
```
Used for decorative accent lines.

---

## 4. Typography

### Font Stack
```css
font-family: Lato, "Assistant", sans-serif;
```

### Font Weights
| Weight | Usage |
|--------|-------|
| 400 | Body text |
| 600 | Labels, buttons |
| 700 | Headings, bold text |

### Font Sizes
| Size | Usage |
|------|-------|
| 12px | Small text, links, button text |
| 14px | Body text, labels |
| 16px | Card titles |
| 20px | Section headings |
| 24px | Page titles |

---

## 5. Layout Structure

### Left Navigation (56px collapsed)
```
┌──────────────────────────────────────────────────────┐
│ [Logo]                                               │
│ 56px                                                 │
│ ┌────┐  ┌─────────────────────────────────────────┐ │
│ │Icon│  │ Main Content Area                       │ │
│ │Nav │  │ Background: #1f1f1f                     │ │
│ │    │  │                                         │ │
│ │#151│  │ ┌─────────────────────────────────────┐ │ │
│ │515 │  │ │ Card                                │ │ │
│ │    │  │ │ Background: #151515                 │ │ │
│ │    │  │ │ Border: 1px solid #333              │ │ │
│ │    │  │ │ Shadow: 0 0 12px rgba(0,0,0,0.7)    │ │ │
│ │    │  │ └─────────────────────────────────────┘ │ │
│ │    │  │                                         │ │
│ └────┘  └─────────────────────────────────────────┘ │
│ [User]                                               │
└──────────────────────────────────────────────────────┘
```

### Color Layering (Light to Dark)
1. `#1f1f1f` - Page background (lightest dark)
2. `#1a1a1a` - Secondary panels
3. `#151515` - Cards, sidebar, elevated surfaces
4. `#000` - Deepest shadows, secondary surface

---

## 6. Component Patterns

### User Avatar
```css
.user-avatar {
    width: 32px;
    height: 32px;
    background: #333; /* NOT green, NOT blue */
    color: #eaebeb;
    border-radius: 4px; /* Rounded rectangle, NOT circle */
    font-size: 12px;
    font-weight: 600;
}
```

### Sidebar Item (Active)
```css
.sidebar-item.active {
    background: rgba(255, 255, 255, 0.05);
    color: #eaebeb;
}
.sidebar-item.active::before {
    /* Left indicator bar */
    width: 3px;
    background: #0c6; /* Green accent */
}
```

### Card
```css
.card {
    background: #151515;
    border: 1px solid #333;
    border-radius: 4px;
    box-shadow: 0 0 12px rgba(0, 0, 0, 0.7);
}
```

### Buttons
```css
.btn-primary {
    background: #fff;
    color: #000;
    border-radius: 20px; /* Pill shape */
    height: 28px;
    font-size: 12px;
    font-weight: 600;
}
```

### Input Fields
```css
.input {
    background: #1f1f1f;
    border: 0;
    border-bottom: 1px solid #575757;
    color: #eaebeb;
}
.input:focus {
    border-color: #eaebeb;
}
```

---

## 7. Key Differences from Current Implementation

| Current | Should Be |
|---------|-----------|
| Background: `#000` | Background: `#1f1f1f` |
| User avatar: green circle | User avatar: gray (#333) rounded rectangle |
| Flat backgrounds | Layered surfaces with shadows |
| Missing border-fade gradients | Add gradient borders |
| Missing row selection fade | Add `--xdr-selected-bg-fade` |

---

## 8. Implementation Checklist

- [ ] Update `--xdr-background` to `#1f1f1f`
- [ ] Add `--xdr-border-fade` gradient variable
- [ ] Add `--xdr-selected-bg-fade` gradient variable
- [ ] User avatar: `border-radius: 4px`, `background: #333`
- [ ] Cards: `box-shadow: 0 0 12px rgba(0, 0, 0, 0.7)`
- [ ] Active sidebar items: green (#0c6) left indicator bar
- [ ] All UI accents: gray/white (no blue except links)
