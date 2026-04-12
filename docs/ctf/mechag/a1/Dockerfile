FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    postfix dovecot-imapd roundcube roundcube-sqlite3 \
    apache2 libapache2-mod-php php-imap \
    python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Build mail content (build_mail.py lives in A1-mail-server/; build context
# is the parent mechag/ dir so COPY can reach both a1/ and A1-mail-server/)
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install reportlab openpyxl
COPY A1-mail-server/build_mail.py /build/build_mail.py
RUN /opt/venv/bin/python3 /build/build_mail.py && rm -rf /opt/venv /build

# Configure Postfix for local delivery
RUN echo "boreas.local" > /etc/mailname
COPY a1/postfix-main.cf /etc/postfix/main.cf

# Configure Dovecot
COPY a1/dovecot-local.conf /etc/dovecot/conf.d/99-local.conf

# Create users and seed mailboxes
COPY a1/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 25 143 80
CMD ["/entrypoint.sh"]
