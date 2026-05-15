FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    postfix dovecot-imapd roundcube roundcube-sqlite3 \
    apache2 libapache2-mod-php php-imap \
    python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Serve Roundcube at the web root. The debian roundcube package ships a
# roundcube.conf with an `Alias /roundcube ...` line commented out and
# expects the operator to either enable that alias OR point DocumentRoot
# at roundcube's public_html. We take the DocumentRoot approach so that
# `http://mail.boreas.local/` lands directly on Roundcube (matches what
# the A1 smoketest and the walkthrough expect).
RUN sed -i 's|DocumentRoot /var/www/html|DocumentRoot /var/lib/roundcube/public_html|' \
    /etc/apache2/sites-available/000-default.conf && \
    printf '<Directory /var/lib/roundcube/public_html>\n    Options FollowSymLinks\n    AllowOverride All\n    Require all granted\n</Directory>\n' \
    > /etc/apache2/conf-available/roundcube-root.conf && \
    a2enconf roundcube-root

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
