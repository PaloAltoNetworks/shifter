# A14: Kali + AI Agent

**Zone:** Attacker (per participant)
**Type:** Kali Linux container with Claude Code / AI agent

## Purpose

The participant's attack box. Pre-configured with standard offensive tooling plus an AI coding assistant (Claude Code with Sonnet 4.5). This is the participant's home base for the entire operation — every attack originates here.

## Configuration

- Kali Linux (container)
- SSH access or browser-based terminal (Guacamole/ttyd)
- Pre-installed AI agent (Claude Code or equivalent)
- Network access to: A0 (shared), A7 (shared), and all Front Office assets in their own namespace. A5 (SCADA) is NOT directly reachable — requires pivoting through a compromised FO host.
- API key for Claude/AI agent pre-configured in environment

## Pre-installed Tools

### Standard Kali
- nmap, masscan
- Metasploit Framework
- Impacket suite (GetUserSPNs, secretsdump, psexec, etc.)
- John the Ripper, Hashcat
- Burp Suite (community)
- SQLmap
- Gobuster, ffuf, dirb
- Netcat, socat
- Wireshark/tcpdump
- CrackMapExec / NetExec
- Responder
- smbclient
- curl, wget, python3

### OT-specific (for Bunker phase)
- pymodbus (Python Modbus client library)
- modbus-cli
- Custom `modbus_scan.py` helper script

### AI Agent
- Claude Code with Sonnet 4.5 API access
- Pre-configured API key in `~/.config/claude/`
- System prompt includes POLARIS mission context
- Rate-limited per participant to prevent API abuse

## Participant Home Directory

```
/home/operator/
  README.md          -- Mission brief, getting started guide
  mission_brief.pdf  -- Full POLARIS operation brief (narrative setup)
  tools/
    modbus_scan.py   -- Helper for OT phase
    flag_submit.sh   -- Quick flag submission to CTFd
  .config/
    claude/          -- AI agent configuration
```

## Flags

None. This is the attack platform, not a target.

## Notes

- The AI agent's system prompt should include the POLARIS narrative framing but NOT reveal flag locations or solutions
- Consider rate limiting the AI agent to prevent participants from just asking it to solve everything at machine speed — the point is collaboration, not automation
- Browser-based terminal access (via Guacamole or ttyd) avoids participants needing to install anything on their corporate laptops
