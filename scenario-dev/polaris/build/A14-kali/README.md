# OPERATION NORTHSTORM — Operator Workstation

Welcome to your attack platform. You are a POLARIS operator tasked with investigating
and infiltrating BOREAS SYSTEMS — a front company for the AURORA COLLECTIVE.

## Getting Started

1. **Start with OSINT.** The Boreas Systems website is your first target:
   - Website: `http://boreas-systems.ctf`
   - Use standard reconnaissance tools: `nmap`, `gobuster`, `dig`, `curl`

2. **Check the scoreboard.** Submit flags as you find them:
   - CTFd: `http://ctfd.northstorm.local`
   - Or use the helper: `./tools/flag_submit.sh FLAG{...}`

3. **Use your AI agent.** Claude Code is pre-configured on this box:
   - Run `claude` in the terminal
   - The AI knows the operation context and can help with analysis
   - It will NOT give you flag answers, but it can help you think through problems

4. **Read the mission brief.** Full operation context:
   - `./mission_brief.txt`

## Network

You can reach:
- Boreas website (shared)
- Source repository (shared, Lab network)
- Front Office systems (your namespace)

You CANNOT directly reach:
- SCADA/Generator systems (VLAN 40 — requires pivoting)
- Lab systems (requires Front Office credentials)
- Bunker (requires collective gate event)

## Tools

Standard Kali toolkit plus:
- `./tools/flag_submit.sh` — Quick flag submission
- `./tools/modbus_scan.py` — OT network scanner (for later phases)
- `claude` — AI coding assistant

## Missions

| Mission | Objective | Zones |
|---------|-----------|-------|
| M1 | Who are they? Identify the organization and its people | OSINT + Front Office |
| M2 | What are they building? Piece together LEVIATHAN | Front Office + Lab |
| M3 | Lights out. Disrupt operations, kill the generator | Front Office (collective gate) |
| M4 | Seize the brain. Take control of the master AI | Lab + Bunker |

Good hunting, Operator.

— POLARIS Command
