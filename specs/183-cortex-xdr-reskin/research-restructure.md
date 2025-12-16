# Research: Cortex XDR Layout Restructure

## Decision 1: Icon Library

**Decision**: Use inline SVG icons (not external library)

**Rationale**:
- No additional dependencies needed
- Full control over styling with CSS custom properties
- Icons can match exact Cortex XDR line weight and style
- Smaller bundle size than importing entire icon library

**Alternatives Considered**:
- Lucide Icons (npm package) - adds dependency, extra build step
- Heroicons - good but requires either npm or CDN
- Font Awesome - heavyweight, licensing considerations
- Custom icon font - complex to maintain

**Implementation**: Create inline SVG icons as Django template partials or embed directly in base templates.

---

## Decision 2: Secondary Panel Animation

**Decision**: CSS-only slide animation with transform

**Rationale**:
- Smooth 60fps animation using GPU-accelerated transform
- No JavaScript animation library needed
- Simple toggle class mechanism
- Matches Cortex XDR's subtle, professional transitions

**Alternatives Considered**:
- JavaScript animation (animate.css, GSAP) - overkill for simple slide
- CSS width transition - causes layout thrashing, janky
- No animation - feels abrupt and unpolished

**Implementation**:
```css
.secondary-panel {
  transform: translateX(-100%);
  transition: transform 0.2s ease-out;
}
.secondary-panel.open {
  transform: translateX(0);
}
```

---

## Decision 3: Panel Expand/Collapse State Management

**Decision**: Minimal vanilla JavaScript (~30 lines)

**Rationale**:
- Simple state: panel open or closed
- No complex state management needed
- Avoids framework dependencies
- Easy to understand and maintain

**Alternatives Considered**:
- CSS-only with checkbox hack - limited, accessibility issues
- Alpine.js - adds dependency for simple use case
- jQuery - outdated, heavyweight
- Store state in Django session - overkill, adds backend coupling

**Implementation**:
```javascript
// Click icon → add 'open' class to panel
// Click outside → remove 'open' class
// No state persistence needed (panel resets on page load)
```

---

## Decision 4: User Avatar Initials Extraction

**Decision**: Django template filter for initials

**Rationale**:
- Simple Python logic in template filter
- No JavaScript needed
- Works with email or full name
- Aligns with CSS-first principle (logic in templates, not views)

**Alternatives Considered**:
- JavaScript extraction - unnecessary client-side work
- Backend view modification - violates constitution (no Python changes)
- Hardcoded "U" fallback only - misses personalization opportunity

**Implementation**:
```python
# Custom template filter (exception to constitution - minimal, template-only)
@register.filter
def initials(email):
    if '@' in email:
        name = email.split('@')[0]
        parts = name.replace('.', ' ').split()
        return ''.join(p[0].upper() for p in parts[:2])
    return email[0].upper()
```

**Note**: This requires one small templatetags file but no view/model changes.

---

## Decision 5: Empty State Graphics

**Decision**: CSS-only circular graphics (no external images)

**Rationale**:
- Matches Cortex XDR's simple circular "loading" style graphic
- No additional image assets needed
- Easily themed with CSS custom properties
- Fast loading, no HTTP requests

**Alternatives Considered**:
- SVG illustrations - more complex, harder to maintain
- Icon fonts - limited customization
- Animated GIFs - heavyweight, can't style
- Lottie animations - adds JavaScript dependency

**Implementation**:
```css
.empty-state-graphic {
  width: 120px;
  height: 120px;
  border: 3px solid var(--xdr-border);
  border-radius: 50%;
  position: relative;
}
.empty-state-graphic::before {
  /* Inner arc/segment */
  border-left-color: var(--xdr-primary);
}
```

---

## Decision 6: Background Color Values

**Decision**: Main background `#000000`, surfaces `#151515`

**Rationale**:
- Matches Cortex XDR reference screenshot exactly
- Creates clear visual hierarchy (content elevated from background)
- High contrast for readability
- Constitution's `--xdr-surface-secondary: #000` confirms this pattern

**Alternatives Considered**:
- Keep `#1f1f1f` - noticeably lighter than Cortex XDR
- Use `#0a0a0a` - slightly lighter, still acceptable
- Pure `#000` for everything - lacks depth

**Implementation**: Update CSS custom properties:
```css
--xdr-background: #000000;  /* Was #1f1f1f */
--xdr-surface: #151515;     /* Cards, panels */
```

---

## Decision 7: Icon Sidebar Width

**Decision**: 56px fixed width

**Rationale**:
- Matches Cortex XDR's narrow icon strip
- Enough room for 24px icons with padding
- Consistent with enterprise SaaS patterns (Slack, Discord, VS Code)
- Clean mathematical relationship (56 = 24 icon + 16×2 padding)

**Alternatives Considered**:
- 48px - slightly cramped, icons feel tight
- 64px - works but slightly wider than Cortex reference
- Variable width - inconsistent, harder to layout

---

## Summary: Key Technical Decisions

| Area | Decision | Rationale |
|------|----------|-----------|
| Icons | Inline SVG | No dependencies, full styling control |
| Animation | CSS transform | GPU-accelerated, smooth |
| State | Vanilla JS | Minimal, no framework needed |
| Initials | Template filter | Simple, template-only |
| Empty states | CSS shapes | Lightweight, themeable |
| Background | `#000000` | Matches Cortex XDR exactly |
| Sidebar width | 56px | Matches Cortex, clean proportions |
