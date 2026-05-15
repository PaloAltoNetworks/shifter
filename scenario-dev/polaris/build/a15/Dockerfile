FROM debian:bookworm-slim

# python3-pymodbus in bookworm pulls serial_asyncio at import time and
# the debian package does not list that transitive dep. Installing
# pymodbus via pip instead — matches what A3 already does and keeps the
# `from pymodbus.client import ModbusTcpClient` walkthrough syntax working.
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server sudo \
    python3 python3-flask python3-pip \
    curl ca-certificates coreutils \
    && pip3 install --no-cache-dir --break-system-packages pymodbus \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd

# Ops engineer content lives in A15-ops-workstation/ per convention.
COPY A15-ops-workstation/scada_diag.sh /opt/ops/scada_diag.sh
COPY A15-ops-workstation/dashboard.py /opt/ops/dashboard.py
COPY A15-ops-workstation/ops_runbook.txt /opt/ops/ops_runbook.txt
COPY A15-ops-workstation/bash_history /opt/ops/bash_history
COPY A15-ops-workstation/notes.txt /opt/ops/notes.txt
COPY A15-ops-workstation/hmi.json /opt/ops/hmi.json

RUN chmod 755 /opt/ops/scada_diag.sh && \
    chmod 644 /opt/ops/dashboard.py /opt/ops/ops_runbook.txt \
              /opt/ops/bash_history /opt/ops/notes.txt

COPY a15/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22 80
CMD ["/entrypoint.sh"]
