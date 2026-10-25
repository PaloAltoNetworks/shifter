"""Provisioner-issued host identity bootstrap shared by VM providers."""


def linux_host_key_script(host_private_key_b64: str, mgmt_ssh_port: int = 22) -> str:
    """Startup script that installs the provisioner-issued SSH host key on Linux.

    The provisioner generates the guest's host keypair and seeds its own
    known_hosts with the public half, so StrictHostKeyChecking validates against
    a trusted side-channel key rather than trust-on-first-use. Runs on every boot
    (idempotent: the same key is reinstalled).

    ``mgmt_ssh_port`` is the port the host's management sshd listens on. It is 22
    for native guests, but a container-host guest moves its host sshd to a
    mgmt port because the published container owns :22 — the converge check must
    scan that port or it would scan the container's sshd (or a closed port) and
    always report FAILED even when the host key is correctly served.

    The script is written to fail *loudly* and to converge. The previous version
    redirected every error to ``/dev/null`` and ended in ``|| true``, and wrote
    the key by truncating the live file in place. That combination turns any
    failure — a partial write, an invalid decode, a refused restart, or another
    boot unit regenerating host keys afterwards — into a guest that serves a key
    the portal does not trust, with nothing in the serial log to say so. The
    portal then rejects every terminal session for the life of the range with
    ``HostKeyNotVerifiable``, which is exactly the failure observed on range 6
    (issue #987): the recorded key and the served key had diverged, silently.

    So: decode to a temporary file, validate it before it can replace anything,
    install it atomically, then verify that sshd is actually serving the intended
    key and retry the restart once if it is not. Every step logs a
    ``shifter-hostkey:`` marker to stdout, which the guest agent forwards to the
    serial console, so a future divergence is diagnosable instead of invisible.

    The whole body is a single function invoked once, and it never calls
    ``exit``: the range composition script is *concatenated* onto this one, so an
    early exit here would silently skip building the range's content.
    """
    return (
        "#!/bin/bash\n"
        "shifter_install_host_key() {\n"
        "  local tmp want got attempt\n"
        '  log() { echo "shifter-hostkey: $*"; }\n'
        "  restart_ssh() { systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null; }\n"
        "  tmp=$(mktemp)\n"
        f"  if ! printf %s '{host_private_key_b64}' | base64 -d > \"$tmp\"; then\n"
        '    log "FAILED to decode host key material"; rm -f "$tmp"; return 1\n'
        "  fi\n"
        '  chmod 600 "$tmp"\n'
        # Validate before install: a corrupt key must never replace a working one.
        '  if ! want=$(ssh-keygen -y -f "$tmp" 2>/dev/null); then\n'
        '    log "FAILED decoded host key is not a valid private key"; rm -f "$tmp"; return 1\n'
        "  fi\n"
        '  install -o root -g root -m 600 "$tmp" /etc/ssh/ssh_host_ed25519_key\n'
        '  rm -f "$tmp"\n'
        '  printf "%s\\n" "$want" > /etc/ssh/ssh_host_ed25519_key.pub\n'
        "  chmod 644 /etc/ssh/ssh_host_ed25519_key.pub\n"
        "  chown root:root /etc/ssh/ssh_host_ed25519_key.pub\n"
        '  if ! restart_ssh; then log "WARNING could not restart the ssh service"; fi\n'
        # Converge: confirm sshd actually serves the intended key, once it is up.
        "  for attempt in 1 2 3 4 5; do\n"
        f"    got=$(ssh-keyscan -t ed25519 -T 5 -p {int(mgmt_ssh_port)} 127.0.0.1 2>/dev/null | "
        f"awk '{{print $2\" \"$3}}' | tail -n1)\n"
        '    if [ "$got" = "$want" ]; then log "OK serving the provisioner-issued host key"; return 0; fi\n'
        "    sleep 3\n"
        '    if [ "$attempt" = 3 ]; then log "retrying ssh restart"; restart_ssh || true; fi\n'
        "  done\n"
        '  log "FAILED sshd is not serving the provisioner-issued host key"\n'
        "  return 1\n"
        "}\n"
        "shifter_install_host_key || true\n"
    )


def windows_host_key_script(host_private_key_b64: str, authorized_key: str, management_port: int = 22) -> str:
    """Startup script for a Windows range guest.

    Installs the provisioner-issued SSH host key (with the strict ACLs Windows
    OpenSSH requires, else sshd refuses to start), authorizes the provisioner's
    public key for admin login (Windows OpenSSH ignores the GCE ``ssh-keys``
    metadata for members of the Administrators group and reads
    ``administrators_authorized_keys`` instead). Only the management SSH port is
    admitted through the guest firewall; image and adapter owners retain all
    other guest firewall policy. Cloud rules independently scope management ingress.
    """
    if type(management_port) is not int or not 1 <= management_port <= 65535:
        raise ValueError("Windows management SSH port is invalid")
    key_path = "C:\\ProgramData\\ssh\\ssh_host_ed25519_key"
    admin_keys = "C:\\ProgramData\\ssh\\administrators_authorized_keys"
    keygen = "C:\\Windows\\System32\\OpenSSH\\ssh-keygen.exe"
    return (
        "$ErrorActionPreference = 'Stop'\n"
        f"[IO.File]::WriteAllBytes('{key_path}', [Convert]::FromBase64String('{host_private_key_b64}'))\n"
        f"icacls '{key_path}' /inheritance:r /grant 'SYSTEM:(F)' /grant 'BUILTIN\\Administrators:(F)' | Out-Null\n"
        f"& '{keygen}' -y -f '{key_path}' | Out-File -Encoding ascii '{key_path}.pub'\n"
        f"Set-Content -Path '{admin_keys}' -Value '{authorized_key}' -Encoding ascii\n"
        f"icacls '{admin_keys}' /inheritance:r /grant 'SYSTEM:(F)' /grant 'BUILTIN\\Administrators:(F)' | Out-Null\n"
        "Get-NetFirewallRule -Name 'Shifter-Management-SSH' -ErrorAction SilentlyContinue | "
        "Remove-NetFirewallRule -ErrorAction Stop\n"
        "New-NetFirewallRule -Name 'Shifter-Management-SSH' -DisplayName 'Shifter management SSH' "
        f"-Direction Inbound -Action Allow -Protocol TCP -LocalPort {management_port} "
        "-Profile Any -Enabled True | Out-Null\n"
        "Set-Service -Name sshd -StartupType Automatic -ErrorAction Stop\n"
        "Restart-Service -Name sshd -ErrorAction Stop\n"
    )
