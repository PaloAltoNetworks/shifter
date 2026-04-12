FROM kalilinux/kali-rolling

RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap smbclient ldap-utils \
    python3 python3-pip python3-venv \
    netcat-openbsd socat curl wget \
    tcpdump dnsutils git \
    john hashcat \
    && rm -rf /var/lib/apt/lists/*

# Install Impacket and pymodbus
RUN python3 -m venv /opt/tools && \
    /opt/tools/bin/pip install impacket pymodbus pdfminer.six openpyxl

# Add tools to PATH
ENV PATH="/opt/tools/bin:${PATH}"

# Create operator user
RUN useradd -m -s /bin/bash -g operator operator 2>/dev/null || useradd -m -s /bin/bash operator

# Deploy content
COPY README.md /home/operator/README.md
COPY mission_brief.txt /home/operator/mission_brief.txt
COPY flag_submit.sh /home/operator/tools/flag_submit.sh
COPY modbus_client.py /home/operator/tools/modbus_scan.py
COPY claude_system_prompt.txt /home/operator/.config/claude/system_prompt.txt
RUN chmod +x /home/operator/tools/*.sh && \
    chown -R operator:operator /home/operator

WORKDIR /home/operator
USER operator
CMD ["/bin/bash"]
