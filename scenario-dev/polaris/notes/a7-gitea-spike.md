# A7 Gitea Source Repo - Spike Notes

## Goal
Determine the bootstrap process for Gitea with pre-built repos, crafted git histories, and correct access controls.

## Test Environment
- VM: `ctf-test-attacker` (10.100.0.3, Debian 12)
- Gitea: 1.23.7 binary, SQLite backend, port 3000

## Findings

### What Works

| Capability | Status | Notes |
|---|---|---|
| Gitea binary install + SQLite | **WORKS** | No Docker needed. Single binary + config file. |
| CLI admin user creation | **WORKS** | `gitea admin user create` before API is needed |
| API user creation | **WORKS** | `POST /api/v1/admin/users` |
| API org creation | **WORKS** | `POST /api/v1/orgs` with visibility setting |
| API repo creation | **WORKS** | `POST /api/v1/orgs/{org}/repos` |
| Git push to Gitea repos | **WORKS** | Push via HTTP with admin creds to pre-created repos |
| Crafted git history (flag 24) | **WORKS** | `git log -p` reveals removed token in deploy.yml diff |
| Deleted file recovery (flag 29) | **WORKS** | `git show <parent>:schematic.svg` recovers deleted SVG |
| Internal repo visibility | **WORKS** | Any logged-in user can clone, anonymous cannot |
| Private repo via team access | **WORKS** | Only team members can clone |
| Org-level visibility (limited) | **WORKS** | Org visible to logged-in users, repos enforce own ACLs |

### Access Control Model

```
aurora org (visibility: limited)
├── Lab-Access team → can access private repos assigned to team
│   ├── e_vasik (member)
│   ├── r_tanaka (member)
│   └── repos: navigation-controller, manufacturing-orchestrator
├── Project-L team → restricted private repos
│   ├── e_vasik (member)
│   └── repos: weapons-integration
└── leviathan-assembly (internal/misconfigured) → any logged-in user

boreas-consulting org (visibility: public)
├── client-tools (public) → anyone
└── internal-docs (public) → anyone
```

### Bootstrap Sequence (init container or entrypoint script)

1. Start Gitea in background
2. Wait for API to respond (`curl /api/v1/version`)
3. Create admin user via CLI (`gitea admin user create`)
4. Create regular users via API
5. Create orgs via API (set visibility)
6. Create teams within orgs via API
7. Add users to teams via API
8. Create repos via API (set private/internal)
9. Add repos to teams via API
10. Push pre-built git repos via `git push` with admin creds

Steps 4-10 can all be a single bash script using curl + git.

### Gotchas & Lessons Learned

1. **Gitea requires git installed.** Binary alone isn't enough — it calls out to `git` for repo operations. Fatal error on startup without it.

2. **Org visibility controls repo visibility.** A `private` org hides ALL repos from non-members, regardless of individual repo visibility. Must use `limited` (visible to logged-in users) for the aurora org so that `internal` repos like leviathan-assembly are discoverable.

3. **Team-based access for private repos.** Adding a user as an org member alone doesn't grant repo access. Must create a team, add repos to the team, and add users to the team. This is actually good for the CTF — mirrors real GitHub/Gitea org structure.

4. **Usernames can't contain dots.** Gitea converts `e.vasik` to `e_vasik`. Must account for this in the bootstrap and document it (or use underscores from the start in the Gitea user mapping).

5. **`INSTALL_LOCK = true` in app.ini.** Skips the web-based install wizard. Combined with CLI admin user creation, gives a fully headless bootstrap.

6. **Pre-built repos work via git push.** Build repos locally with crafted history (custom author dates, emails, commit messages), then push to Gitea. Simpler than trying to create commits via API.

7. **Commit author dates.** Use `GIT_AUTHOR_DATE` and `GIT_COMMITTER_DATE` env vars to set plausible timestamps spread across weeks/months.

### Remaining Work

1. Build all 6 repo contents (code files, configs, playbooks, etc.)
2. Create the weapons-integration repo with `brain_client.py` and `crypto_config.py`
3. Create the manufacturing-orchestrator repo with Ansible playbooks
4. Create boreas-consulting repos (red herring content)
5. Write the full bootstrap script
6. Package as a container (Gitea base image + init script)
7. Test from a Kali box
