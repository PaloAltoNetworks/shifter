# Design System

Visual language for the Shifter portal. Cyberpunk/circuit aesthetic aligned with Cortex branding.

## Brand Assets

Located in `assets/images/`:
- `logo-transparent.png` - Icon only (hexagonal S)
- `wordmark-transparent.png` - Text only
- `logo-wordmark-transparent.png` - Combined logo + wordmark
- `shifter-brand-small.png` - Brand reference sheet

## Colors

| Name | Hex | Usage |
|------|-----|-------|
| Neon Green | `#39FF14` | Primary accent, CTAs, active states, logo |
| Palo Orange | `#FA582D` | Secondary accent, warnings, highlights |
| Circuit Dark Blue | `#0A0A2A` | Primary background |
| Circuit Background | `#111122` | Secondary background, cards |
| White | `#FFFFFF` | Primary text |

### CSS Variables

```css
:root {
    --neon-green: #39FF14;
    --palo-orange: #FA582D;
    --circuit-dark: #0A0A2A;
    --circuit-bg: #111122;
    --white: #FFFFFF;
}
```

### Color Application

- **Backgrounds**: Circuit dark blue (`#0A0A2A`) as base, circuit background (`#111122`) for cards/elevated surfaces
- **Text**: White for primary, neon green for emphasis/links
- **Borders**: Neon green at varying opacity (20-50%)
- **Buttons**: Neon green fill with dark text, or outlined with green border
- **Accent elements**: Palo orange for secondary CTAs, notifications, warnings
- **Status indicators**: Neon green (active/success), palo orange (warning/paused), red for errors

## Typography

| Font | Weight | Usage |
|------|--------|-------|
| Shifter Glitch Bold | Bold | Headers, wordmark, buttons |
| Roboto | 400, 500 | Body text, labels, data |

### Font Loading

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500&display=swap" rel="stylesheet">
```

Note: Shifter Glitch Bold is a custom font - use fallback or load from assets.

## Effects

### Circuit Pattern

Subtle circuit board pattern overlay for backgrounds (from logo aesthetic).

### Glow Effect

Neon green glow for interactive elements and logo:

```css
.glow {
    filter: drop-shadow(0 0 10px rgba(57, 255, 20, 0.5));
}

.glow-strong {
    filter: drop-shadow(0 0 20px rgba(57, 255, 20, 0.7))
            drop-shadow(0 0 40px rgba(57, 255, 20, 0.4));
}
```

### Glitch Text

CSS glitch effect for headers (used sparingly):

```css
.glitch {
    position: relative;
}

.glitch::before,
.glitch::after {
    content: attr(data-text);
    position: absolute;
    top: 0;
    left: 0;
    opacity: 0;
}

.glitch::before {
    color: var(--neon-green);
    animation: glitch-1 4s infinite;
    clip-path: polygon(0 0, 100% 0, 100% 35%, 0 35%);
}

.glitch::after {
    color: var(--white);
    animation: glitch-2 4s infinite;
    clip-path: polygon(0 65%, 100% 65%, 100% 100%, 0 100%);
}

@keyframes glitch-1 {
    0%, 88%, 100% { transform: translate(0); opacity: 0; }
    90% { transform: translate(-3px, -1px); opacity: 0.8; }
    92% { transform: translate(3px, 1px); opacity: 0.8; }
}

@keyframes glitch-2 {
    0%, 88%, 100% { transform: translate(0); opacity: 0; }
    89% { transform: translate(3px, 1px); opacity: 0.8; }
    91% { transform: translate(-3px, -1px); opacity: 0.8; }
}
```

### Scanlines (Optional)

Subtle CRT-style scanlines for retro effect:

```css
.scanlines {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    z-index: 100;
    background: repeating-linear-gradient(
        0deg,
        rgba(0, 0, 0, 0.02) 0px,
        rgba(0, 0, 0, 0.02) 1px,
        transparent 1px,
        transparent 3px
    );
}
```

## Components

### Buttons

**Primary (Launch, Submit):**
- Background: Neon green (`#39FF14`)
- Text: Circuit dark blue (`#0A0A2A`), Roboto 500
- Border: None
- Hover: Brighter glow, slight scale

**Secondary (Cancel, Back):**
- Background: Transparent
- Text: White
- Border: 1px white at 30% opacity
- Hover: Border brightens to neon green

**Danger (Destroy, Delete):**
- Background: Transparent
- Text: `#FF4444` (red)
- Border: 1px red at 50% opacity
- Hover: Fill with red at 15% opacity

### Cards

Container for grouped content:

- Background: Circuit background (`#111122`)
- Border: 1px neon green at 15% opacity
- Border-radius: 4px
- Padding: 1.5rem
- Hover: Border brightens to 30%

### Status Indicators

Dot + label for range/system status:

- Active: Neon green dot, pulsing glow
- Paused: Palo orange dot, static
- Provisioning: Neon green dot, spinning animation
- Error: Red (`#FF4444`) dot, static
- Destroyed: Gray (`#666666`) dot, static

### Form Inputs

- Background: Circuit dark blue (`#0A0A2A`)
- Border: 1px white at 20% opacity
- Text: White, Roboto 400
- Focus: Border neon green, subtle glow
- Placeholder: White at 40% opacity

### Navigation

- Background: Circuit background (`#111122`)
- Active item: Neon green left border, green text
- Inactive: White text at 70% opacity
- Hover: White text at 100%

## Spacing

Base unit: 0.5rem (8px)

| Token | Value | Usage |
|-------|-------|-------|
| xs | 0.25rem | Tight spacing |
| sm | 0.5rem | Component internal |
| md | 1rem | Between elements |
| lg | 1.5rem | Section padding |
| xl | 2rem | Page sections |

## Responsive Breakpoints

| Name | Width | Adjustments |
|------|-------|-------------|
| Mobile | < 600px | Stack nav, reduce font sizes |
| Tablet | 600-900px | Collapsed sidebar |
| Desktop | > 900px | Full layout |

## Logo Usage

- Minimum clear space: Height of the "S" icon on all sides
- Dark backgrounds only (dark blue or black)
- Do not alter colors or proportions
- Use transparent PNG versions for flexibility
