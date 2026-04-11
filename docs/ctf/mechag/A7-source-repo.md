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

---

## Build Plan

**Base image:** gitea/gitea:latest (official Gitea image)
**Spike notes:** `temp/a7-gitea-spike.md`
**Content directory:** `docs/ctf/mechag/A7-source-repo/`

### Spike Results

- Gitea 1.23.7 with SQLite works out of the box
- Git push of pre-built repos with crafted history: **confirmed working**
- Flag 24 (token in deleted git diff): **confirmed recoverable via `git log -p`**
- Flag 29 (deleted SVG in history): **confirmed recoverable via `git show <parent>:file`**
- Access control via org visibility (limited) + team-based repo access: **confirmed working**
- Usernames: Gitea doesn't allow dots — use `e_vasik` not `e.vasik`

### Access Control Model (verified)

```
aurora org (visibility: limited)
├── Lab-Access team → private repos
│   ├��─ members: e_vasik, r_tanaka, p_nielsen, k_yamamoto, f_okoye
│   └── repos: navigation-controller, manufacturing-orchestrator
├── Project-L team → highly restricted
│   ├── members: e_vasik
│   └── repos: weapons-integration
└── leviathan-assembly (internal visibility = the misconfiguration)

boreas-consulting org (visibility: public)
├── client-tools (public)
└── internal-docs (public)
```

### Bootstrap Sequence (init script)

1. Start Gitea, wait for API (`/api/v1/version`)
2. Create admin user via CLI (`gitea admin user create`)
3. Create users via API (`POST /admin/users`)
4. Create orgs via API (boreas-consulting: public, aurora: limited)
5. Create teams in aurora (Lab-Access, Project-L) via API
6. Add users to teams via API
7. Create repos in orgs via API (set private/internal)
8. Add repos to teams via API
9. Push pre-built git repos via `git push` with admin creds

### Remaining Work

1. **Build all 6 repo contents as local git repos with crafted history**
   - `boreas-consulting/client-tools` — red herring scripts
   - `boreas-consulting/internal-docs` — IT docs, hostnames
   - `aurora/navigation-controller` — locomotion AI code + config with `BRAIN_AUTH_TOKEN` + flag 24 git history
   - `aurora/weapons-integration` — `brain_client.py` (A13 protocol) + `crypto_config.py` (A6 GPG passphrase)
   - `aurora/manufacturing-orchestrator` — Ansible playbooks with A10/A11 unlock hints
   - `aurora/leviathan-assembly` — schematic SVG (flag 29) + BOM + status tracker
2. **Write the full bootstrap script** (bash, ~100 lines of curl + git commands)
3. **Write Dockerfile** (gitea base + bootstrap script + pre-built repo archives)
4. **Test from Kali box**
