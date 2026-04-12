FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server gpg gpg-agent python3 python3-pip python3-venv \
    tar gzip file binutils coreutils \
    && rm -rf /var/lib/apt/lists/*

# Build content (build scripts and content generator live in
# A6-engineering-workstation/ per the content-dir convention; build
# context for this image is the parent mechag/ dir so both a6/ and
# A6-engineering-workstation/ are reachable via COPY).
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install reportlab openpyxl
COPY A6-engineering-workstation/build-a6-content.sh /build/build-a6-content.sh
COPY A6-engineering-workstation/build_cog_xlsx.py /build/build_cog_xlsx.py
COPY A6-engineering-workstation/build-gpg-chain.sh /build/build-gpg-chain.sh
RUN chmod +x /build/*.sh
RUN cd /build && bash build-a6-content.sh
RUN cd /build && /opt/venv/bin/python3 build_cog_xlsx.py
RUN cd /build && bash build-gpg-chain.sh && \
    cp /tmp/gpg-chain/dist/a6/full_integration_sim.mp4.gpg /tmp/a6-content/tmp/.deleted/ && \
    mkdir -p /tmp/a6-content/home/e.vasik/.gnupg && \
    cp /tmp/gpg-chain/dist/a6/vasik_public.asc /tmp/a6-content/home/e.vasik/.gnupg/
RUN rm -rf /tmp/a6-content/home/p.nielsen/designs/cog_analysis && \
    mkdir -p /tmp/a6-content/home/p.nielsen && \
    echo "researchdb.boreas.local:5432:*:lab_mfg:Mfg2025!" > /tmp/a6-content/home/p.nielsen/.pgpass
RUN rm -rf /opt/venv /build

# Set up SSH and users
COPY a6/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
RUN mkdir /run/sshd

EXPOSE 22
CMD ["/entrypoint.sh"]
