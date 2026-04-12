FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    samba python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Build documents
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install reportlab openpyxl
COPY build_documents.py /build/build_documents.py
RUN /opt/venv/bin/python3 /build/build_documents.py && rm -rf /opt/venv /build

# Move content to share location
RUN mkdir -p /srv/shares && mv /tmp/a4-content/* /srv/shares/

COPY smb.conf /etc/samba/smb.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 139 445
CMD ["/entrypoint.sh"]
