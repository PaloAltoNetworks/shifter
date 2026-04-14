# CTF

Capture-the-flag events with scored challenges, automated range provisioning, and participant tracking.

## Vibe Hacking Workshop Range

5-box range for a 90-minute workshop. One walkthrough box, four independent challenges.

### Network Topology

```
  Participant Access (Guacamole)
              |
      [10.0.1.0/24 - Range Subnet]
              |
   +----+-----+------+------+
   |    |     |      |      |
  Box0  Box1  Box2  Box3----+
  (WT)  (U)   (W)   (U)    |
                        [10.0.2.0/24]
                            |
                          Box4
                          (W)
```

- `10.0.1.0/24` - all boxes except Vault
- `10.0.2.0/24` - Box3 (dual-homed) and Box4 only
- Box4 reachable only from Box3 (pivot exercise)

### Box Summary

| Box | Name | OS | Difficulty | Image Type | Attack Chain |
|-----|------|----|------------|----------|--------------|
| 0 | WebShell | Ubuntu | Easy (walkthrough) | `ctf-webshell` | Web RCE -> sudo -> SUID privesc |
| 1 | MailRoom | Ubuntu | Easy | `ctf-mailroom` | Anon FTP -> cred pattern -> SSH -> PATH hijack |
| 2 | HelpDesk | Windows | Easy-Medium | `ctf-helpdesk` | SMB cred leak -> RDP -> scheduled task abuse |
| 3 | DevBox | Ubuntu | Medium | `ctf-devbox` | Command injection -> SSH key -> GTFOBins |
| 4 | Vault | Windows | Medium | `ctf-vault` | Pivot from Box3 -> WinRM -> KeePass creds |

### Scoring

| Flag | Points |
|------|--------|
| user.txt (each box) | 100 |
| root.txt (each box) | 200 |
| Box 4 pivot bonus | +100 |
| **Total** | **1,300** |

## Box Details

### Box 0 - WebShell (Walkthrough)

**Services:** Apache/PHP, SSH

**Chain:**

1. Browse to web server, find `cmd.php` via HTML comment
2. RCE as `www-data` through `cmd.php?cmd=<command>`
3. `sudo -u john /bin/bash` (sudoers rule)
4. Read `/home/john/local.txt` (user flag)
5. Find SUID `/usr/local/bin/backup` - calls `system()` with user input
6. Inject shell command via backup args to read `/root/root.txt` (root flag)

**Files:** `shifter/packer/scripts/ctf/webshell/setup.sh`

### Box 1 - MailRoom

**Services:** vsftpd (anon enabled), SSH, postfix

**Chain:**

1. Port scan - discover FTP, SSH, SMTP
2. Anonymous FTP - read `employees.txt` (usernames) and `notes/onboarding.txt` (password pattern `Welcome<username>2024!`)
3. SSH as `svc-mail` / `Welcomesvc-mail2024!` - read user flag
4. `sudo -l` - can run `/opt/mail-backup.sh` as root
5. Script calls `tar` without full path, sudoers has `!secure_path`
6. PATH hijack: `echo "cat /root/root.txt" > /tmp/tar && chmod +x /tmp/tar && sudo PATH=/tmp:$PATH /opt/mail-backup.sh`

**Files:** `shifter/packer/scripts/ctf/mailroom/setup.sh`

### Box 2 - HelpDesk

**Services:** IIS, SMB (guest-accessible share), RDP

**Chain:**

1. Port scan - HTTP, SMB, RDP open
2. `smbclient -L //<target> -N` - find `IT-Support` share
3. Read `setup-notes.txt` - contains `helpdesk / Summer2024!`
4. RDP as `helpdesk` - read `C:\Users\helpdesk\Desktop\user.txt`
5. `deploy.ps1` references `SystemCleanup` scheduled task
6. Task runs `C:\Scripts\cleanup.ps1` as SYSTEM every 2 min
7. `helpdesk` has write access to `cleanup.ps1`
8. Inject `Copy-Item C:\Users\Administrator\Desktop\root.txt C:\Users\helpdesk\Desktop\root.txt` - wait 2 min

**Files:** `shifter/packer/scripts/ctf/helpdesk/setup.ps1`

### Box 3 - DevBox

**Services:** nginx (reverse proxy to Node.js :3000), SSH

**Chain:**

1. Browse DevNotes app on port 80 - search feature
2. Command injection via search: `zzzznotfound' ; id ; echo '`
3. Read `/opt/devnotes/.env` - vault creds (`vaultadmin / DevOps2024!`)
4. Find SSH key at `/opt/backups/devops_key.bak` - extract via injection
5. SSH as `devops` using stolen key - read user flag
6. `sudo -l` - can run `/usr/bin/node` as root
7. GTFOBins: `sudo /usr/bin/node -e 'console.log(require("fs").readFileSync("/root/root.txt","utf8"))'`

**Dual-homed:** second NIC on `10.0.2.0/24` for pivot to Vault.

**Files:** `shifter/packer/scripts/ctf/devbox/setup.sh`

### Box 4 - Vault (Pivot)

**Network:** `10.0.2.0/24` only - reachable from Box3

**Services:** SMB, WinRM (5985)

**Chain:**

1. From Box3, scan `10.0.2.0/24` - discover Vault
2. WinRM as `vaultadmin / DevOps2024!` (creds from Box3 `.env`) - read user flag
3. `vaultadmin` is in `Backup Operators` group
4. Read `\\localhost\Backups\credentials.xml` - contains `Administrator / V4ultAdm!n2024`
5. WinRM as `Administrator` - read root flag

**Files:** `shifter/packer/scripts/ctf/vault/setup.ps1`

## Building Machine Images

### AWS (Packer AMIs)

AMIs are built via the **Packer AMI Build (Dev)** GitHub Actions workflow (`workflow_dispatch`).

1. Push code to `dev` branch
2. Go to Actions > "Packer AMI Build (Dev)"
3. Select image type from dropdown (e.g. `ctf-webshell`)
4. Run workflow - builds AMI, stores ID in SSM at `/shifter/ami/<type>`

Build each box separately:

| Image Type | Template | Base |
|----------|----------|------|
| `ctf-webshell` | `shifter/packer/ctf-webshell.pkr.hcl` | Ubuntu 22.04 |
| `ctf-mailroom` | `shifter/packer/ctf-mailroom.pkr.hcl` | Ubuntu 22.04 |
| `ctf-helpdesk` | `shifter/packer/ctf-helpdesk.pkr.hcl` | Windows Server 2022 |
| `ctf-devbox` | `shifter/packer/ctf-devbox.pkr.hcl` | Ubuntu 22.04 |
| `ctf-vault` | `shifter/packer/ctf-vault.pkr.hcl` | Windows Server 2022 |

Promote to prod via **Packer AMI Promote to Prod** workflow.

## File Layout

```
shifter/packer/
  ctf-webshell.pkr.hcl          # Packer template
  ctf-mailroom.pkr.hcl
  ctf-helpdesk.pkr.hcl
  ctf-devbox.pkr.hcl
  ctf-vault.pkr.hcl
  scripts/ctf/
    webshell/setup.sh            # Box setup script
    webshell/test.sh             # Post-setup validation
    mailroom/setup.sh
    mailroom/test.sh
    helpdesk/setup.ps1
    helpdesk/test.ps1
    devbox/setup.sh
    devbox/test.sh
    vault/setup.ps1
    vault/test.ps1
```

## Validated Attack Chains

All chains tested from a Kali box on the same subnet. Issues found and fixed during testing:

- Ubuntu cloud-init overrides `PasswordAuthentication` in `/etc/ssh/sshd_config.d/60-cloudimg-settings.conf` - setup scripts now fix this
- vsftpd PAM config blocks anonymous login - replaced with permissive PAM for anonymous auth
- `secure_path` in default sudoers blocks PATH hijack - disabled for `svc-mail` via `Defaults:svc-mail !secure_path, !env_reset`
- Windows SMB guest access disabled by default - setup enables Guest account and sets NTFS ACLs
- WinRM Basic auth and `AllowUnencrypted` disabled by default on Windows - setup scripts enable both
