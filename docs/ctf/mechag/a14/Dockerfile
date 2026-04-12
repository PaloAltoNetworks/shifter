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
    && rm -rf /var/lib/apt/lists/*

# Ensure kali user exists with home directory (the kalilinux/kali-rolling base image
# does not create one and the metapackages don't add it either).
RUN id kali >/dev/null 2>&1 || useradd -m -s /bin/bash kali

# Python helper libs needed by participants for OT + analysis tasks
RUN python3 -m venv /opt/tools && \
    /opt/tools/bin/pip install --no-cache-dir \
        impacket pymodbus pdfminer.six openpyxl reportlab certipy-ad
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

# CTF content overlay — these files live in A14-kali/ (content dir) per
# convention; the Modbus scan helper is shared with A9-splice-landing/.
# Build context is the parent mechag/ dir so COPY can reach both.
COPY A14-kali/README.md /home/kali/README.md
COPY A14-kali/mission_brief.txt /home/kali/mission_brief.txt
COPY A14-kali/mission_brief.pdf /home/kali/mission_brief.pdf
COPY A14-kali/flag_submit.sh /home/kali/tools/flag_submit.sh
COPY A9-splice-landing/modbus_client.py /home/kali/tools/modbus_scan.py
COPY A14-kali/claude_system_prompt.txt /home/kali/.config/claude/system_prompt.txt
RUN chmod +x /home/kali/tools/*.sh /home/kali/tools/*.py && \
    chown -R kali:kali /home/kali

# Entrypoint: start sshd + xrdp and stay foreground
COPY a14/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 22 3389
WORKDIR /home/kali
CMD ["/usr/local/bin/entrypoint.sh"]
