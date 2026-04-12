# Terminal UI: Tabbed Layout with Optional Split

## Summary

Replace the current fixed 2-pane terminal layout with a tabbed interface that scales to N instances. Users can view a single terminal tab or optionally split to view two side-by-side.

## Problem

Current terminal UI is hardcoded to 2 panes (Kali + Victim). Ranges may have multiple targets (Windows, Ubuntu, Exchange, etc.) with no way to access them.

## Proposed Solution

### Tab Bar

Add a tab bar above the terminal container:

```
┌───────────────────────────────────────────────────────────┐
│ [⚔ Kali ●] [TARGET: Win ●] [TARGET: Ubuntu ○] [+] [Split] │
├───────────────────────────────────────────────────────────┤
│                                                           │
│   (Terminal content - single tab or split view)           │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

### Tab States

- **Active tab**: White bottom border, `--xdr-surface` background
- **Inactive tab**: Transparent background, `--xdr-text-secondary` text
- **Status dot**: Green (connected), yellow pulsing (connecting), red (error), gray (not connected)

### Split Mode

- Toggle button enables 2-pane split (reuses current divider logic)
- User selects which two tabs to display
- Split preference persisted in localStorage

### Tab Content

Each tab displays:
- Role badge: `ATTACKER` or `TARGET` (uppercase, 12px)
- Instance name/alias if available (e.g., "EXCHANGE", "BOB")
- IP address in monospace
- Connection status

## Technical Approach

1. Refactor `terminal.js` TerminalManager to support N terminals
2. Lazy-connect WebSocket on tab activation (don't connect all at once)
3. Keep xterm.js instances alive when tab hidden (preserve scrollback)
4. Tab bar component with click handlers and keyboard navigation
5. Split mode reuses existing `.terminal-divider` and resize logic

## Files to Modify

- `portal/templates/mission_control/terminal.html` - Add tab bar markup
- `portal/static/js/terminal.js` - Multi-terminal management
- `portal/static/css/terminal.css` - Tab bar styling
- `portal/mission_control/views.py` - Pass all instances to template

## Acceptance Criteria

- [ ] Tab bar renders with one tab per range instance
- [ ] Clicking tab switches visible terminal
- [ ] Status indicator shows connection state per tab
- [ ] Split button toggles 2-pane view
- [ ] Keyboard navigation: Ctrl+Tab cycles tabs
- [ ] Mobile: Tabs scroll horizontally or collapse to dropdown
- [ ] WebSocket connects on first tab activation (lazy)
- [ ] Terminal scrollback preserved when switching tabs

## Dependencies

None - can be built incrementally on current implementation.

## Labels

`enhancement`, `terminal`, `ux`
