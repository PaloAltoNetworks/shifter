# Terminal UI: Toolbar Actions

## Summary

Add a toolbar with common terminal actions: copy, clear, reconnect, and fullscreen. Follows XDR button patterns.

## Problem

Current terminal has no UI for common actions. Users must rely on keyboard shortcuts or browser features for copy/paste, and have no way to manually reconnect or clear output.

## Proposed Solution

### Toolbar Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ Range Terminal                      [Copy] [Clear] [⟳] [⛶]     │
├─────────────────────────────────────────────────────────────────┤
```

Or per-pane toolbar in header:

```
┌─────────────────────────────────────────────────────────────────┐
│ ATTACKER · Kali · 10.1.1.10   ●  [Copy] [Clear] [⟳]            │
├─────────────────────────────────────────────────────────────────┤
```

### Actions

| Button | Icon | Action | Shortcut |
|--------|------|--------|----------|
| Copy | 📋 | Copy selection or last N lines to clipboard | Ctrl+Shift+C |
| Clear | 🗑 | Clear terminal scrollback | Ctrl+L |
| Reconnect | ⟳ | Force reconnect WebSocket | - |
| Fullscreen | ⛶ | Toggle pane fullscreen | F11 |

### Button Styling

Use XDR secondary button pattern:

```css
.terminal-action-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 4px;
    background: transparent;
    border: 1px solid var(--xdr-border);
    color: var(--xdr-text-secondary);
    cursor: pointer;
}

.terminal-action-btn:hover {
    background: var(--xdr-hover);
    color: var(--xdr-text);
}
```

### Copy Behavior

1. If text selected in terminal: copy selection
2. If no selection: copy last 50 lines of output
3. Show toast notification: "Copied to clipboard"

### Reconnect Behavior

1. Close existing WebSocket
2. Reset retry counter
3. Initiate fresh connection
4. Update status indicator

### Fullscreen Behavior

1. Expand single pane to full terminal container
2. Hide other panes and divider
3. Show "Exit Fullscreen" button
4. ESC or button click restores layout

## Files to Modify

- `portal/templates/mission_control/terminal.html` - Add toolbar markup
- `portal/static/js/terminal.js` - Action handlers
- `portal/static/css/terminal.css` - Toolbar styling

## Acceptance Criteria

- [ ] Copy button copies selection or recent output
- [ ] Clear button clears terminal scrollback
- [ ] Reconnect button forces fresh WebSocket connection
- [ ] Fullscreen button expands pane to full container
- [ ] Buttons use XDR styling pattern
- [ ] Toast notification on copy
- [ ] Keyboard shortcuts work

## Labels

`enhancement`, `terminal`, `ux`
