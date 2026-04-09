# A7: Source Repo Server

**Zone:** Shared (single instance for all participants)
**Type:** Git server (Gitea, GitLab CE, or similar)

## Purpose

Internal source code repository for AURORA's engineering team. Contains the control software for PROJECT LEVIATHAN's subsystems — the code that runs the autonomous navigation, weapons targeting, and manufacturing orchestration. Also contains the full assembly schematic in a repo that was supposed to be access-controlled but has a misconfigured public repo.

## Configuration

- Git web interface (Gitea or similar) on port 3000
- Accessible from Lab zone (reachable after pivoting from Front Office)
- Multiple repositories with different visibility levels
- Some repos require authentication (Lab-Access group from AD)
- One repo is accidentally public/internal-visible

## Repositories

| Repository | Visibility | Owner | Description |
|---|---|---|---|
| `boreas-consulting/client-tools` | Public | m.webb | Legitimate consulting scripts. Red herring. |
| `boreas-consulting/internal-docs` | Public | d.kowalski | Internal IT documentation. Some useful network info. |
| `aurora/navigation-controller` | Private (Lab-Access) | e.vasik | Autonomous navigation AI source code |
| `aurora/weapons-integration` | Private (Project-L) | e.vasik | Targeting and weapons system interface code |
| `aurora/manufacturing-orchestrator` | Private (Lab-Access) | r.tanaka | Build pipeline for the assembly line PLCs |
| `aurora/leviathan-assembly` | Internal (misconfigured) | e.vasik | Full assembly schematic and integration docs |

## Key Repository Content

### aurora/navigation-controller
- Python/C++ codebase for bipedal locomotion AI
- Comments reference "maintaining balance at target height of 120m"
- Config file with Modbus addresses for leg and tail controllers
- Unit tests named `test_bipedal_walk.py`, `test_terrain_adaptation.py`

### aurora/weapons-integration
- Interface code for "primary effector system"
- Config references a "directed energy array" with power draw calculations
- Integration test connects to a mock PLC at addresses matching the Bunker controllers

### aurora/manufacturing-orchestrator
- Deployment scripts that push firmware to PLCs
- Ansible playbooks targeting hosts: `tail-ctrl`, `leg-ctrl`, `arms-ctrl`, `brain-main`
- One playbook is `deploy_combat_ai.yml`

### aurora/leviathan-assembly
- Full system schematic as a multi-page SVG
- Bill of materials cross-referencing every procurement order from A4
- Assembly status tracker matching the one in the Bunker (A8)
- This repo is misconfigured as "Internal" visibility — any authenticated user can clone it

## Flags

### Flag 24 — Source repo — control software
- **Difficulty:** Medium
- **Location:** `aurora/navigation-controller` repo. The README contains no flag — it's a clean project description. The flag is in a CI pipeline config file (`.github/workflows/deploy.yml`) that was committed, then updated in a later commit to remove a hardcoded deploy token. Recovering the token requires examining git diff history (`git log -p` or `git diff HEAD~3`) to find the removed line. The flag is the original deploy token value. Comparable to HTB OpenSource's credential-in-deleted-file pattern — requires basic git history awareness but not deep object-level forensics.
- **Flag:** `FLAG{8a0e3c7f2d5b1946}`
- **Mission:** M2, M4

### Flag 29 — Full Leviathan schematic assembly
- **Difficulty:** Hard
- **Location:** `aurora/leviathan-assembly` repo. The current HEAD contains only a README: "Moved to secure system." The schematic was committed then deleted in a later commit. Standard `git log` shows the deletion commit but `git show` on that commit only shows the removal, not the content. Recovery requires: (1) identifying the parent commit before the deletion via `git log --diff-filter=D -- schematic.svg`, (2) using `git show <parent-commit>:schematic.svg` to extract the deleted file. The SVG renders as a technical diagram, but the flag is in an XML comment in the raw SVG source — not visible when rendered, only when viewing the markup directly. Requires understanding git history navigation and deleted file recovery via `git show`, plus inspecting raw file source rather than just opening it. A single coherent chain, harder than basic `git log`/`git diff` but not requiring git plumbing internals.
- **Flag:** `FLAG{1f9b4e7c0a3d8265}`
- **Mission:** M2
