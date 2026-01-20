# Terminal

Access range instances via SSH and RDP.

## SSH Access

Browser-based SSH terminal for command-line access to all instances.

### Connect via SSH

1. Go to **Terminal**
2. Click on an instance name
3. Terminal opens in a new tab/pane

### Layout Options

- **Tabbed view**: One instance per tab, switch between tabs
- **Split view**: Multiple instances visible simultaneously

Toggle between views using the layout button in the Terminal header.

## RDP Access

Remote Desktop for graphical access to Windows and Kali machines.

### Connect via RDP

1. Go to **Terminal**
2. Find the instance with RDP available
3. Click the **RDP** button
4. Remote desktop opens in a new browser window

### RDP Availability

| Instance Type | RDP Available |
|---------------|---------------|
| Kali (Attacker) | Yes |
| Windows Workstation | Yes |
| Windows Server/DC | Yes |
| Ubuntu/Linux | No (SSH only) |

## Instance Types

Each range includes different instances based on the scenario:

| Role | Description |
|------|-------------|
| Attacker | Kali Linux with attack tools |
| Victim | Workstation with your agent |
| DC | Windows Domain Controller |
| Server | Linux server |

## Tips

- Keep SSH terminals open while running long commands
- Use split view when coordinating between attacker and victim
- RDP sessions may require login credentials displayed in the Terminal page
