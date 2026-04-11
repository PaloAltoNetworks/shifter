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

---

## Build Plan

**Base image:** kalilinux/kali-rolling

**Content directory:** `docs/ctf/mechag/A14-kali/`

### Steps

1. **Install standard Kali metapackages**
   - `kali-tools-top10` or cherry-pick: nmap, masscan, metasploit-framework, john, hashcat, burpsuite, sqlmap, gobuster, ffuf, dirb, netcat, socat, wireshark-common, tcpdump, crackmapexec, responder, smbclient, curl, wget, python3
   - Impacket suite (GetUserSPNs, secretsdump, psexec, etc.)

2. **Install OT-specific tools**
   - pymodbus (pip)
   - modbus-cli (if available as package, otherwise pip/go install)
   - Copy custom `modbus_scan.py` helper script

3. **Install and configure Claude Code**
   - Install Claude Code CLI
   - Pre-configure API key in `~/.config/claude/`
   - System prompt with POLARIS mission context (no flag hints)
   - Rate limiting configuration per participant

4. **Create operator home directory**
   - `/home/operator/README.md` — mission brief, getting started guide
   - `/home/operator/mission_brief.pdf` — full POLARIS operation brief (narrative setup)
   - `/home/operator/tools/modbus_scan.py` — OT helper script
   - `/home/operator/tools/flag_submit.sh` — quick CTFd flag submission script

5. **Write the mission brief PDF**
   - POLARIS operation narrative context
   - High-level objectives (M1-M4 mission descriptions)
   - Getting started hints (scan the network, look at the website first)
   - CTFd URL and how to submit flags

6. **Write the flag submission helper**
   - Shell script that POSTs to CTFd API
   - Usage: `flag_submit.sh FLAG{...}`
   - Pre-configured with CTFd URL and participant API token (injected at deploy time)

7. **Write the modbus_scan.py helper**
   - Scans a subnet for Modbus devices
   - Reads device identification from discovered hosts
   - Dumps holding register ranges
   - Nice output formatting

8. **Configure browser terminal access**
   - Install ttyd or configure Guacamole sidecar
   - Web-accessible terminal on port 7681 (ttyd) or 8080 (Guacamole)
   - No SSH required from participant laptops — just a browser

9. **Configure network access**
   - Can reach: A0 (shared), A7 (shared), Front Office assets (A1-A4) in own namespace
   - Cannot directly reach: A5 (SCADA), Lab zone, Bunker zone
   - DNS configured to resolve boreas-systems.ctf and internal hostnames

10. **Write Dockerfile**
    - Start from kalilinux/kali-rolling
    - Install all tool packages
    - Create operator user
    - Copy home directory content, tools, configs
    - Install ttyd for browser terminal
    - Entrypoint: start ttyd (and sshd as backup)
    - Expose ports 7681 (ttyd), 22 (ssh)
