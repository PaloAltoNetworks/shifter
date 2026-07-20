# base image: debian:12-slim
FROM debian@sha256:60eac759739651111db372c07be67863818726f754804b8707c90979bda511df

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      postfix postfix-pcre dovecot-core dovecot-imapd dovecot-lmtpd \
      sasl2-bin ca-certificates supervisor \
 && rm -rf /var/lib/apt/lists/*

COPY main.cf /etc/postfix/main.cf
COPY dovecot.conf /etc/dovecot/dovecot.conf
COPY supervisord.conf /etc/supervisord.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 25 143

CMD ["/entrypoint.sh"]
