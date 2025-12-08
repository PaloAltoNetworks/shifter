# Design System

Visual language for the Shifter portal. Cyberpunk/hacker aesthetic inspired by sci-fi interfaces.

## Colors

| Name | Hex | Usage |
|------|-----|-------|
| Neon Pink | `#FF1B6B` | Primary accent, CTAs, active states |
| Cyan | `#00FFFF` | Secondary accent, links, highlights |
| Purple | `#7F00FF` | Tertiary accent, gradients |
| Deep Blue | `#0A0A1A` | Background |
| White | `#FFFFFF` | Primary text |

### Color Application

- **Backgrounds**: Deep blue with subtle radial gradients (purple/pink at low opacity)
- **Text**: White for primary, cyan for secondary/links
- **Borders**: Neon pink or cyan at 50% opacity
- **Buttons**: Neon pink fill, white text
- **Status indicators**: Cyan (active), neon pink (warning), purple (paused)

## Typography

| Font | Weight | Usage |
|------|--------|-------|
| Orbitron | 700, 900 | Headings, wordmark, buttons |
| Share Tech Mono | 400 | Body text, labels, data |

### Font Loading

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
```

## Effects

### Scanlines

Subtle CRT-style scanlines overlay on entire viewport:

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
        rgba(0, 0, 0, 0.015) 0px,
        rgba(0, 0, 0, 0.015) 1px,
        transparent 1px,
        transparent 3px
    );
}
```

### Noise Texture

Subtle noise overlay for texture:

```css
.noise {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    opacity: 0.03;
    pointer-events: none;
    z-index: 1;
    background-image: url("data:image/svg+xml,..."); /* SVG noise filter */
}
```

### Glow Pulse

Animated glow effect for logos and important elements:

```css
@keyframes glowPulse {
    0%, 100% {
        filter: drop-shadow(0 0 25px rgba(255, 27, 107, 0.4));
    }
    50% {
        filter: drop-shadow(0 0 40px rgba(255, 27, 107, 0.6))
                drop-shadow(0 0 60px rgba(127, 0, 255, 0.3));
    }
}
```

### Glitch Text

CSS-only glitch effect for headings (used sparingly):

```css
.glitch::before,
.glitch::after {
    content: attr(data-text);
    position: absolute;
    top: 0;
    left: 0;
    opacity: 0;
}

.glitch::before {
    color: var(--neon-pink);
    animation: glitch-1 4s infinite;
    clip-path: polygon(0 0, 100% 0, 100% 35%, 0 35%);
}

.glitch::after {
    color: var(--purple);
    animation: glitch-2 4s infinite;
    clip-path: polygon(0 65%, 100% 65%, 100% 100%, 0 100%);
}
```

### Terminal Cursor

Blinking cursor for terminal-style text:

```css
.cursor {
    display: inline-block;
    width: 8px;
    height: 1em;
    background: var(--cyan);
    animation: blink 1s infinite;
}

@keyframes blink {
    0%, 50% { opacity: 1; }
    51%, 100% { opacity: 0; }
}
```

## Components

### Buttons

**Primary (Launch, Submit):**
- Background: Neon pink
- Text: White, Orbitron 700
- Border: None
- Hover: Brighter glow, slight scale

**Secondary (Cancel, Back):**
- Background: Transparent
- Text: Cyan
- Border: 1px cyan at 50% opacity
- Hover: Border brightens

**Danger (Destroy, Delete):**
- Background: Transparent
- Text: Neon pink
- Border: 1px neon pink at 50% opacity
- Hover: Fill with pink at 20% opacity

### Cards

Container for grouped content (range status, agent list items):

- Background: Deep blue with slight transparency
- Border: 1px white at 10% opacity
- Border-radius: 4px
- Padding: 1.5rem
- Hover: Border brightens to 20%

### Status Indicators

Dot + label for range/system status:

- Active: Cyan dot, pulsing glow
- Paused: Purple dot, static
- Provisioning: Neon pink dot, spinning animation
- Error: Neon pink dot, static

### Form Inputs

- Background: Deep blue darker shade
- Border: 1px white at 20% opacity
- Text: White, Share Tech Mono
- Focus: Border cyan, subtle glow
- Placeholder: White at 40% opacity

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

## Cursor

Custom crosshair cursor for the cyberpunk aesthetic:

```css
body {
    cursor: crosshair;
}
```

Interactive elements use pointer cursor.
