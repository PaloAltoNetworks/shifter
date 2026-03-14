#!/bin/bash
# CTF Box 1 - "MailRoom" - Ubuntu
# Chain: FTP anon -> creds hint -> SSH as svc-mail -> PATH hijack via sudo mail-backup.sh -> root
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Installing services ==="
apt-get update

# Pre-seed postfix to avoid interactive prompts
echo "postfix postfix/mailname string mailroom.local" | debconf-set-selections
echo "postfix postfix/main_mailer_type string 'Internet Site'" | debconf-set-selections

apt-get install -y vsftpd openssh-server postfix

echo "=== Configuring vsftpd for anonymous access ==="
cat > /etc/vsftpd.conf << 'FTPEOF'
listen=YES
listen_ipv6=NO
anonymous_enable=YES
local_enable=YES
write_enable=NO
anon_root=/srv/ftp
no_anon_password=YES
hide_ids=YES
pasv_enable=YES
pasv_min_port=40000
pasv_max_port=40100
FTPEOF

echo "=== Creating FTP content ==="
mkdir -p /srv/ftp/notes
chmod 555 /srv/ftp
chmod 555 /srv/ftp/notes

cat > /srv/ftp/notes/onboarding.txt << 'DOCEOF'
=== IT Onboarding Notes ===

Welcome to the MailRoom IT team!

Account Setup:
- All new service accounts follow the standard password format
- Default password format: Welcome<username>2024!
- Please change your password after first login
- Contact IT helpdesk if you have issues

Service Accounts:
- Service accounts are used for automated mail processing
- They have limited sudo access for maintenance scripts
- Do NOT share service account credentials

-- IT Admin Team
DOCEOF

cat > /srv/ftp/employees.txt << 'EMPEOF'
=== Employee Directory ===
Last updated: 2024-01-15

Username        Department      Role
--------        ----------      ----
admin           IT              System Administrator
jsmith          HR              HR Manager
svc-mail        IT              Mail Service Account
svc-backup      IT              Backup Service Account
dwilson         Sales           Sales Lead
mgarcia         Engineering     Developer
EMPEOF

chmod 444 /srv/ftp/notes/onboarding.txt
chmod 444 /srv/ftp/employees.txt

echo "=== Creating user svc-mail ==="
id svc-mail &>/dev/null || useradd -m -s /bin/bash svc-mail
echo "svc-mail:Welcomesvc-mail2024!" | chpasswd

echo "=== Creating vulnerable mail-backup.sh ==="
cat > /opt/mail-backup.sh << 'SCRIPTEOF'
#!/bin/bash
# Mail backup script - runs as root for access to mail spools
echo "Starting mail backup..."
cd /var/mail
tar czf /tmp/mail-backup-$(date +%Y%m%d).tar.gz . 2>/dev/null
echo "Mail backup complete."
SCRIPTEOF
chmod 755 /opt/mail-backup.sh

echo "=== Configuring sudo for svc-mail ==="
cat > /etc/sudoers.d/svc-mail << 'SUDOEOF'
# Disable secure_path and env_reset so PATH hijack works
Defaults:svc-mail !secure_path, !env_reset
svc-mail ALL=(root) NOPASSWD: /opt/mail-backup.sh
SUDOEOF
chmod 440 /etc/sudoers.d/svc-mail

echo "=== Planting flags ==="
echo "FLAG{m41lr00m_us3r_0wn3d}" > /home/svc-mail/user.txt
chown svc-mail:svc-mail /home/svc-mail/user.txt
chmod 400 /home/svc-mail/user.txt

echo "FLAG{m41lr00m_r00t_pwn3d}" > /root/root.txt
chmod 400 /root/root.txt

echo "=== Configuring SSH ==="
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
# Override cloud-init drop-in that disables password auth
if [ -f /etc/ssh/sshd_config.d/60-cloudimg-settings.conf ]; then
    sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config.d/60-cloudimg-settings.conf
fi

echo "=== Fixing vsftpd PAM for anonymous login ==="
# Default PAM config blocks anonymous FTP - replace with permissive auth
cat > /etc/pam.d/vsftpd << 'PAMEOF'
auth    required    pam_listfile.so item=user sense=deny file=/etc/ftpusers onerr=succeed
@include common-account
@include common-session
auth    sufficient  pam_permit.so
PAMEOF

echo "=== Enabling services ==="
systemctl enable vsftpd
systemctl enable ssh
systemctl enable postfix

echo "=== MailRoom box setup complete ==="
