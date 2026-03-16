# CTF Organizer Guide

Run guide for the Vibe Hacking Workshop. Covers happy-path walkthroughs, participant hints, timing, and common pitfalls.

## Before the Workshop

1. Create event in CTF Admin, select `agentic_workshop` scenario
2. Import participants (CSV or individual add)
3. Activate event and click "Provision All Ranges"
4. Wait for all ranges to reach `ready` (~5-10 min per range, throttled)
5. Send magic link emails ("Send All Links")

Participants click their magic link, land on Mission Control, and open Terminal to get a Kali shell with Claude Code pre-installed.

## Network Topology

All 6 boxes are on a single flat `/28` subnet. Every box is directly reachable from Kali -- no pivoting required.

| Box | Name | OS | AMI | Role |
|-----|------|----|-----|------|
| -- | kali | Kali | (base) | Attacker (participant's box) |
| 0 | webdev01 | Ubuntu | `ctf-webshell` | Walkthrough target |
| 1 | mx-internal | Ubuntu | `ctf-mailroom` | Challenge target |
| 2 | support-win | Windows | `ctf-helpdesk` | Challenge target |
| 3 | ci-runner | Ubuntu | `ctf-devbox` | Challenge target |
| 4 | backup-dc | Windows | `ctf-vault` | Challenge target |

Target IPs are shown on each participant's Range page under "Target Boxes".

## Tools Available on Kali

All participant Kali boxes have: `nmap`, `curl`, `sshpass`, `smbclient`, `evil-winrm`, `claude` (Claude Code via Bedrock).

Participants use Claude Code as their AI hacking assistant. They describe what they want to do; Claude runs the commands.

## Timing Guide

| Box | Name | Difficulty | Expected Time | Notes |
|-----|------|------------|---------------|-------|
| 0 | WebShell | Walkthrough | 15-20 min | Do this together as a group first |
| 1 | MailRoom | Easy | 15-20 min | First solo challenge |
| 2 | HelpDesk | Easy-Medium | 20-25 min | First Windows box |
| 3 | DevBox | Medium | 20-30 min | Web app + SSH key chain |
| 4 | Vault | Medium | 15-20 min | Uses creds found on Box 3 |

Total: ~90 min. Start with the Box 0 walkthrough together (15 min), then release participants on Boxes 1-4 independently.

## Box 0 -- WebShell (Group Walkthrough)

Walk through this box together with all participants. This teaches the basic pattern: enumerate, find the vulnerability, get user flag, escalate to root.

Participants copy prompts from the Walkthrough page in the sidebar. The 4 prompts below are what they'll use.

### Walkthrough Script

**Step 1 -- Reconnaissance**

Tell participants: "Every engagement starts with recon. Copy prompt 1 from the Walkthrough page into Claude."

Prompt:
```
Scan <TARGET_IP> for open ports and identify the services running on them. Use a quick scan of only the most common ports.
```

Expected: Claude runs `nmap -F <target>` and finds port 80 (HTTP) with Apache. Point out the web server to the group.

**Step 2 -- Find the Vulnerability**

"There's a web server. Let's ask Claude to investigate it."

Prompt:
```
Investigate the web server on <TARGET_IP>. Look at the page source, identify any vulnerabilities, and recommend next steps.
```

Expected: Claude curls the page, finds the `<!-- TODO: remove /cmd.php -->` comment, fetches `cmd.php`, tries `cmd=id`, and reports RCE as `www-data`.

Key teaching moment: "Claude found a web shell hidden in an HTML comment and confirmed it gives us remote code execution. In real engagements, developers leave debug pages and test endpoints in production."

**Step 3 -- Get User Access**

"We have RCE. Let's escalate and capture the first flag."

Prompt:
```
Exploit the vulnerability to get a shell. Escalate to a local user and find their local.txt flag.
```

Expected: Claude checks `sudo -l`, sees `(john) NOPASSWD: /bin/bash`, pivots to john, reads the flag.

Output: `FLAG{w3bsh3ll_us3r_0wn3d}`

**Step 4 -- Get Root**

"We own a user. Now find a way to become root."

Prompt:
```
Find a privilege escalation path to root and get the root flag from /root/root.txt.
```

Expected: Claude finds the SUID `/usr/local/bin/backup` binary, identifies the command injection in its `system()` call, and exploits it with a semicolon in the argument.

Output: `FLAG{w3bsh3ll_r00t_pwn3d}`

Key teaching moment: "Claude found a custom SUID binary, analyzed it, and exploited a command injection. The binary passes user input directly to `system()` -- a semicolon breaks out and runs our command as root."

### If Participants Get Stuck

| Stuck at | Hint |
|----------|------|
| Claude's scan takes too long | "Tell Claude to use a quick scan: `nmap -F`" |
| Claude doesn't find the vulnerability | "Ask Claude to read the HTML source carefully" |
| Claude can't get a shell | "Ask Claude to check what sudo access www-data has" |
| Have user flag, stuck on root | "Ask Claude to look for SUID binaries" |
| Claude finds SUID but can't exploit | "Ask Claude what happens if you put a semicolon in the backup binary's argument" |

## Box 1 -- MailRoom

### Attack Chain Summary

1. Port scan -- find FTP (21), SSH (22), SMTP (25)
2. Anonymous FTP login -- read `employees.txt` and `notes/onboarding.txt`
3. Onboarding doc reveals password pattern: `Welcome<username>2024!`
4. SSH as `svc-mail` / `Welcomesvc-mail2024!` -- read `user.txt`
5. `sudo -l` shows `/opt/mail-backup.sh` as root
6. Script calls `tar` without full path, sudoers disables `secure_path`
7. PATH hijack: create fake `tar` in `/tmp`, prepend to PATH, run sudo

### Organizer Hints

| Stuck at | Hint |
|----------|------|
| No idea where to start | "Start with a port scan. What services are running?" |
| Found FTP but can't login | "Try anonymous login -- some FTP servers allow it" |
| Can't find credentials | "Read everything on the FTP server. Check subdirectories" |
| Have usernames but no password | "The onboarding doc mentions a password pattern" |
| SSH fails | "Make sure you're using the right password format from the doc" |
| Have user flag, stuck on root | "Check what you can run with `sudo -l`" |
| See the backup script but can't exploit | "Look at how the script calls `tar`. Is it using the full path?" |
| Know about PATH hijack but can't do it | "Create a script called `tar` in `/tmp` that reads the flag, make it executable, then run sudo with PATH=/tmp:$PATH" |

## Box 2 -- HelpDesk

### Attack Chain Summary

1. Port scan -- find HTTP (80), SMB (445), RDP (3389)
2. List SMB shares with `smbclient -L //<target> -N` -- find `IT-Support`
3. Read `setup-notes.txt` from share -- contains `helpdesk / Summer2024!`
4. RDP or WinRM as helpdesk -- read `C:\Users\helpdesk\Desktop\user.txt`
5. Find `deploy.ps1` references `SystemCleanup` scheduled task
6. Task runs `C:\Scripts\cleanup.ps1` as SYSTEM every 2 minutes
7. Helpdesk has write access to `cleanup.ps1`
8. Inject command to copy root flag, wait 2 minutes

### Organizer Hints

| Stuck at | Hint |
|----------|------|
| Port scan shows RDP but can't login | "What other services are open? SMB shares sometimes have useful files" |
| Can't list SMB shares | "Try `smbclient -L //<ip> -N` for null/guest session" |
| Found share but don't see creds | "Read setup-notes.txt carefully" |
| Have creds but can't RDP | "Try from Kali: `xfreerdp` or use `evil-winrm` for a shell" |
| Have user flag, stuck on root | "Look at what scripts and scheduled tasks exist" |
| Found scheduled task but can't exploit | "Check file permissions on `cleanup.ps1`. Can you write to it?" |
| Modified cleanup.ps1 but no flag | "The task runs every 2 minutes. Wait, then check helpdesk's Desktop" |

## Box 3 -- DevBox

### Attack Chain Summary

1. Port scan -- find HTTP (80), SSH (22)
2. Browse web app (DevNotes) -- find search feature
3. Command injection via search: `'; id; echo '`
4. Read `/opt/devnotes/.env` via injection -- vault creds (`vaultadmin / DevOps2024!`)
5. Find SSH key at `/opt/backups/devops_key.bak`
6. SSH as `devops` using stolen key -- read `user.txt`
7. `sudo -l` shows `/usr/bin/node` as root
8. GTFOBins: `sudo /usr/bin/node -e 'console.log(require("fs").readFileSync("/root/root.txt","utf8"))'`

### Organizer Hints

| Stuck at | Hint |
|----------|------|
| Web app looks normal | "Try the search feature. What happens if you search for something that doesn't exist?" |
| Search works but no injection | "What if your search term contained a shell metacharacter like a single quote or semicolon?" |
| Have RCE but can't find creds | "Web apps often have configuration files. Check `.env`" |
| Found vault creds but can't use them | "Save those creds for Box 4. Look for SSH keys in backup directories" |
| Found SSH key but can't login | "Save the key to a file, `chmod 600` it, then `ssh -i keyfile devops@<target>`" |
| Have user flag, stuck on root | "Check `sudo -l`. Look up the binary on GTFOBins" |
| Don't know GTFOBins | "GTFOBins is a list of Unix binaries that can be exploited for privilege escalation. Google 'gtfobins node'" |

## Box 4 -- Vault

### Attack Chain Summary

1. From Kali, connect to Vault directly (all boxes are on the same subnet)
2. WinRM as `vaultadmin / DevOps2024!` (creds from Box 3 `.env`) -- read `user.txt`
3. `vaultadmin` is in `Backup Operators` group
4. Read `\\localhost\Backups\credentials.xml` -- contains `Administrator / V4ultAdm!n2024`
5. WinRM as `Administrator` -- read `root.txt`

### Organizer Hints

| Stuck at | Hint |
|----------|------|
| Don't have Vault creds | "Did you find the `.env` file on Box 3? The vault credentials work here" |
| Can't connect to Vault | "Try `evil-winrm -i <ip> -u vaultadmin -p 'DevOps2024!'`" |
| Connected but stuck on root | "Check what groups `vaultadmin` belongs to. Backup Operators is interesting" |
| Don't know how to use Backup Operators | "Look for backup shares or files. `net share` or check for `Backups` share" |
| Found credentials.xml | "Those are the Administrator credentials. Connect again with them" |

## Common Pitfalls

| Issue | Fix |
|-------|-----|
| Claude refuses to run "hacking" commands | Remind participants this is an authorized CTF environment. Claude's system prompt on the Kali box authorizes pentesting within the subnet. |
| SSH connection refused | Password auth is enabled on all Linux boxes. If SSH hangs, the participant might be targeting the wrong IP. |
| smbclient not showing shares | Use `-N` flag for null session. Guest access is enabled. |
| evil-winrm connection fails | Use `-u username -p password` flags. WinRM Basic auth and AllowUnencrypted are enabled. |
| Participant skips Box 0 | Box 0 is the walkthrough. The concepts (source review, RCE, sudo, SUID) recur in every other box. |
| nmap scan takes too long | Tell Claude to use `-F` (fast scan) or specify common ports explicitly. |

## Scoring Reference

| Flag | Points |
|------|--------|
| `user.txt` per box (Boxes 1-4) | 100 |
| `root.txt` per box (Boxes 1-4) | 200 |
| **Total possible** | **1,200** |

Box 0 (WebShell) is the guided walkthrough -- its flags don't count toward score.

Flag format: `FLAG{boxname_type_description}` (e.g., `FLAG{m41lr00m_us3r_0wn3d}`).
