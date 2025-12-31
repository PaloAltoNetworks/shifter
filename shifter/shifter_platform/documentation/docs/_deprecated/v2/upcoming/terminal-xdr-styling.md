# Terminal UI: XDR Styling Consistency

## Summary

Update terminal CSS to fully align with Cortex XDR design system. Fix missing variables, standardize patterns, and improve visual consistency.

## Problem

Current terminal styling has:
- Hardcoded colors instead of CSS variables
- Missing status color variables (`--xdr-success`, `--xdr-warning`, `--xdr-error`)
- Inconsistent border-radius (8px vs XDR standard 4px)
- Non-standard component patterns

## Proposed Changes

### 1. Add Missing CSS Variables

Add to `xdr-theme.css`:

```css
:root {
    /* Existing vars... */

    /* Status colors */
    --xdr-success: #00d26a;
    --xdr-warning: #f5a623;
    --xdr-error: #ff4d4f;
    --xdr-primary: #128df3;

    /* Terminal specific */
    --xdr-terminal-bg: #0d0d0d;
    --xdr-text-muted: #707070;
    --xdr-surface-hover: rgba(255, 255, 255, 0.05);
}
```

### 2. Replace Hardcoded Values

In `terminal.css`:

| Current | Replace With |
|---------|--------------|
| `#0d0d0d` | `var(--xdr-terminal-bg)` |
| `border-radius: 8px` | `border-radius: 4px` |

In `terminal.js` xterm theme:

| Current | Replace With |
|---------|--------------|
| `background: '#0d0d0d'` | Read from CSS variable |
| `cursor: '#128df3'` | `var(--xdr-primary)` |

### 3. Role Badges

Add uppercase role labels matching XDR table header style:

```css
.role-badge {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--xdr-text-secondary);
}

.role-badge.attacker {
    color: var(--xdr-error);
}

.role-badge.target {
    color: var(--xdr-primary);
}
```

### 4. Pane Header Update

Align with XDR card header pattern:

- Role badge left-aligned
- Instance name/alias as title
- IP address as subtitle
- Status indicator right-aligned

### 5. Divider Styling

Match XDR table row border pattern:

```css
.terminal-divider {
    width: 1px;
    background: var(--xdr-border);
}

.terminal-divider:hover {
    width: 3px;
    background: var(--xdr-primary);
}
```

## Files to Modify

- `portal/static/css/xdr-theme.css` - Add missing variables
- `portal/static/css/terminal.css` - Replace hardcoded values, add role badges
- `portal/static/js/terminal.js` - Read theme from CSS variables

## Acceptance Criteria

- [ ] All status colors use CSS variables
- [ ] Terminal background uses `--xdr-terminal-bg` variable
- [ ] Border-radius matches XDR standard (4px)
- [ ] Role badges display for ATTACKER/TARGET
- [ ] Divider matches XDR border pattern
- [ ] No hardcoded color values in terminal.css

## Labels

`enhancement`, `terminal`, `design-system`
