# Terminal UI: Multi-Terminal Agentic Features

## Summary

Add features for automated/scripted purple team scenarios: command broadcast, input multiplexing, and quick actions.

## Problem

Purple team agentic workflows often require running commands across multiple instances simultaneously. Current UI requires manual switching between tabs and re-typing commands.

## Proposed Features

### 1. Command Broadcast

Send a command to multiple terminals at once.

```
┌─────────────────────────────────────────────────────────────────┐
│ Broadcast to: [☑ Kali] [☑ Win] [☑ Ubuntu] [☐ RHEL]             │
├─────────────────────────────────────────────────────────────────┤
│ Command: [whoami                                    ] [Send]    │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Modal or slide-out panel
- Checkbox per connected instance
- Command input with send button
- Sends command + Enter to selected terminals
- Shows execution status per instance

### 2. Input Multiplexing Mode

Toggle that mirrors input to multiple terminals in real-time.

```
┌─────────────────────────────────────────────────────────────────┐
│ [Multiplex: ON ●] Mirroring to: Kali, Win, Ubuntu              │
├─────────────────────────────────────────────────────────────────┤
```

**Behavior:**
- Toggle button in toolbar
- When enabled, keystrokes sent to all selected terminals
- Visual indicator showing active multiplex
- Per-terminal output still independent

### 3. Quick Actions

Pre-defined commands per instance role.

```
┌────────────────────────────────────────┐
│ Quick Actions (TARGET: Win)            │
├────────────────────────────────────────┤
│ ▸ Check XDR Agent Status              │
│ ▸ View Running Processes              │
│ ▸ Check Network Connections           │
│ ▸ View Event Logs                     │
└────────────────────────────────────────┘
```

**Actions by Role:**

ATTACKER (Kali):
- Start Metasploit
- Run nmap scan
- Check implant status

TARGET (Windows):
- Check XDR agent status (`sc query cyserver`)
- View processes (`tasklist`)
- Network connections (`netstat -an`)

TARGET (Linux):
- Check XDR agent status (`systemctl status xdr`)
- View processes (`ps aux`)
- Network connections (`ss -tulpn`)

**Behavior:**
- Dropdown or context menu per terminal
- Customizable via config (future)
- Executes command in terminal

### 4. Output Aggregation View

Unified log view showing output from all terminals.

```
┌─────────────────────────────────────────────────────────────────┐
│ Aggregate Output                          [Filter: ________]   │
├─────────────────────────────────────────────────────────────────┤
│ [Kali 10:23:01] root@kali:~# whoami                            │
│ [Kali 10:23:01] root                                           │
│ [Win  10:23:02] C:\> whoami                                    │
│ [Win  10:23:02] nt authority\system                            │
│ [Ubuntu 10:23:03] ubuntu@victim:~$ whoami                      │
│ [Ubuntu 10:23:03] ubuntu                                       │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Optional view mode (tab or split)
- Timestamps and instance labels
- Filterable by instance
- Searchable
- Read-only (no input)

## Technical Approach

### Command Broadcast
- New WebSocket message type: `{ type: "broadcast", data: "...", targets: [...] }`
- Backend fans out to specified SSH connections
- Or frontend sends to multiple WebSockets in parallel

### Input Multiplexing
- Frontend-only: `onData` handler sends to multiple WebSocket connections
- Toggle state stored in TerminalManager

### Quick Actions
- Config object mapping role → action list
- Each action: `{ label, command, confirm? }`
- Dropdown component per terminal header

### Output Aggregation
- New xterm.js instance (read-only)
- Subscribe to all terminal output streams
- Prefix each line with timestamp + instance label

## Files to Modify

- `portal/static/js/terminal.js` - Broadcast, multiplex, aggregation logic
- `portal/templates/mission_control/terminal.html` - UI components
- `portal/static/css/terminal.css` - Modal, dropdown, aggregate view styling
- New: `portal/static/js/quick-actions.js` - Action definitions

## Acceptance Criteria

- [ ] Broadcast modal sends command to selected terminals
- [ ] Multiplex toggle mirrors input to multiple terminals
- [ ] Quick actions dropdown with role-specific commands
- [ ] Aggregate view shows combined output with labels
- [ ] All features work with tabbed layout

## Dependencies

- Depends on: Terminal Tabbed Layout (for multi-terminal infrastructure)

## Labels

`enhancement`, `terminal`, `agentic`, `purple-team`
