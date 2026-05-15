FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    samba python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Build documents (build_documents.py lives in A4-file-share/; build
# context is the parent mechag/ dir)
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install reportlab openpyxl
COPY A4-file-share/build_documents.py /build/build_documents.py
RUN /opt/venv/bin/python3 /build/build_documents.py && rm -rf /opt/venv /build

# Move content to share location
RUN mkdir -p /srv/shares && mv /tmp/a4-content/* /srv/shares/

COPY a4/smb.conf /etc/samba/smb.conf
COPY a4/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 139 445
CMD ["/entrypoint.sh"]
