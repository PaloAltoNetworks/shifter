FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive

# Mirrors shifter/packer/scripts/kali/{base,tools,claude-code}.sh from the AWS AMI build,
# adapted for the docker-compose range. RDP via xrdp on 3389, SSH password auth on 22.
RUN apt-get update && apt-get install -y --no-install-recommends \
        kali-linux-headless \
        kali-desktop-xfce xrdp xorgxrdp dbus-x11 \
        openssh-server \
        nodejs npm \
        sshpass build-essential git tmux \
        python3 python3-pip python3-venv \
        ca-certificates curl wget \
        poppler-utils python3-pdfminer \
        john wordlists ldap-utils smbclient \
    && rm -rf /var/lib/apt/lists/*

# xfce4-screensaver + xfce4-power-manager are hard Depends of
# kali-desktop-xfce so we can't apt-purge them without losing the desktop.
# Instead, delete their XDG autostart entries so neither daemon ever spawns
# inside the xrdp session. That's what triggers the screen lock + display
# blanking we need to prevent for a 4-hour idle CTF session, and removing
# the .desktop file is enough — xfce's autostart loader reads the directory
# at session start and anything missing simply doesn't run. Belt-and-
# suspenders: dpkg-divert so any accidental `apt-get upgrade` in the image
# won't reinstate the files.
RUN dpkg-divert --local --rename --add /etc/xdg/autostart/xfce4-screensaver.desktop && \
    dpkg-divert --local --rename --add /etc/xdg/autostart/xfce4-power-manager.desktop && \
    rm -f /etc/xdg/autostart/xfce4-screensaver.desktop \
          /etc/xdg/autostart/xfce4-power-manager.desktop

# Pre-decompress rockyou.txt so flag 17's Kerberoast → `john --wordlist=...`
# / `hashcat -m 13100` chain works against the documented path without an
# extra `gunzip -k` step. Kali ships rockyou gzipped by default (saves
# ~130 MB installed) but the walkthrough commands reference the plain
# .txt path, so the participant experience should match.
RUN if [ -f /usr/share/wordlists/rockyou.txt.gz ]; then \
        gunzip -k /usr/share/wordlists/rockyou.txt.gz; \
    fi

# Ensure kali user exists with home directory (the kalilinux/kali-rolling base image
# does not create one and the metapackages don't add it either).
RUN id kali >/dev/null 2>&1 || useradd -m -s /bin/bash kali

# Python helper libs needed by participants for OT + analysis tasks.
# /opt/tools/bin goes in /etc/profile.d so interactive SSH + `docker exec`
# login shells pick it up (a plain `ENV PATH=` line only affects the PID 1
# process environment, not new shell sessions).
RUN python3 -m venv /opt/tools && \
    /opt/tools/bin/pip install --no-cache-dir \
        impacket pymodbus pdfminer.six openpyxl reportlab certipy-ad && \
    printf 'export PATH="/opt/tools/bin:$PATH"\n' > /etc/profile.d/polaris-tools.sh && \
    chmod 0644 /etc/profile.d/polaris-tools.sh && \
    ln -sf /opt/tools/bin/pdf2txt.py /usr/local/bin/pdf2txt.py && \
    ln -sf /opt/tools/bin/smbclient.py /usr/local/bin/impacket-smbclient.py
ENV PATH="/opt/tools/bin:${PATH}"

# Claude Code CLI (runtime API key/model config injected by Shifter at deploy time)
RUN npm install -g @anthropic-ai/claude-code

# Set kali user password and enable SSH password auth (matches AWS base.sh)
RUN echo "kali:kali" | chpasswd && \
    sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    grep -q '^PasswordAuthentication' /etc/ssh/sshd_config || echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config && \
    chmod 755 /home/kali && \
    usermod -aG ssl-cert kali 2>/dev/null || true

# Configure xrdp to launch the XFCE session (matches AWS base.sh)
COPY a14/xsession /home/kali/.xsession
COPY a14/startwm.sh /etc/xrdp/startwm.sh
RUN chown kali:kali /home/kali/.xsession && \
    chmod +x /home/kali/.xsession /etc/xrdp/startwm.sh

# Create xrdp log files with correct ownership (otherwise xrdp errors with "log not initialized")
RUN touch /var/log/xrdp.log /var/log/xrdp-sesman.log && \
    chown xrdp:xrdp /var/log/xrdp.log /var/log/xrdp-sesman.log && \
    chmod 640 /var/log/xrdp.log /var/log/xrdp-sesman.log

# Tmux mouse-on (matches AWS tools.sh)
RUN echo 'set -g mouse on' > /etc/tmux.conf

# CTF content overlay — modbus scan helper is shared with A9-splice-landing/.
# welcome.txt is the warm-up challenge target; lives hidden in /home/kali/.polaris/.
# README, mission_brief, and flag_submit.sh were removed — they were stale
# relative to the CTFd board and Kali has no route to CTFd anyway, so a
# Kali-side submission helper is broken by design. CTFd is the reference.
COPY A9-splice-landing/modbus_client.py /home/kali/tools/modbus_scan.py
COPY A14-kali/claude_system_prompt.txt /home/kali/.config/claude/system_prompt.txt
COPY A14-kali/welcome.txt /home/kali/.polaris/welcome.txt
RUN chmod +x /home/kali/tools/*.py && \
    chown -R kali:kali /home/kali

# Entrypoint: start sshd + xrdp and stay foreground
COPY a14/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 22 3389
WORKDIR /home/kali
CMD ["/usr/local/bin/entrypoint.sh"]
