FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server gpg gpg-agent python3 python3-pip python3-venv \
    python3-openpyxl \
    tar gzip file binutils coreutils \
    && rm -rf /var/lib/apt/lists/*

# Build content (build scripts and content generator live in
# A6-engineering-workstation/ per the content-dir convention; build
# context for this image is the parent mechag/ dir so both a6/ and
# A6-engineering-workstation/ are reachable via COPY).
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install reportlab openpyxl
COPY A6-engineering-workstation/build-a6-content.sh /build/build-a6-content.sh
COPY A6-engineering-workstation/build_cog_xlsx.py /build/build_cog_xlsx.py
RUN chmod +x /build/*.sh
RUN cd /build && bash build-a6-content.sh
RUN cd /build && /opt/venv/bin/python3 build_cog_xlsx.py

# GPG chain artifacts are pre-generated into _shared/gpg-chain/ so A6 and A8
# reference the SAME keypair. Regenerating inside the A6 image would desync
# A8's private-key blob from the encrypted file's recipient (flag 30).
# To rotate the keypair, re-run A6-engineering-workstation/build-gpg-chain.sh
# and re-copy artifacts into _shared/gpg-chain/.
COPY _shared/gpg-chain/vasik_public.asc /build/gpg-chain/vasik_public.asc
COPY _shared/gpg-chain/full_integration_sim.mp4.gpg /build/gpg-chain/full_integration_sim.mp4.gpg
RUN mkdir -p /tmp/a6-content/tmp/.deleted /tmp/a6-content/home/e.vasik/.gnupg && \
    cp /build/gpg-chain/full_integration_sim.mp4.gpg /tmp/a6-content/tmp/.deleted/ && \
    cp /build/gpg-chain/vasik_public.asc /tmp/a6-content/home/e.vasik/.gnupg/

# research-analyst account authorizes A16's p.shah via a pre-generated
# SSH key stored under _shared/. Copy to /etc/ so it survives the
# /build cleanup in the next RUN layer — entrypoint.sh reads from
# /etc/research-analyst.pub.
COPY _shared/research-analyst-key/id_rsa.pub /etc/research-analyst.pub
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
