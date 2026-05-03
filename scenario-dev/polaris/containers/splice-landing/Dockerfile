FROM alpine:3.19

RUN apk add --no-cache openssh-server ca-certificates nmap \
 && ssh-keygen -A \
 && adduser -D -s /bin/sh splice \
 && mkdir -p /home/splice/.ssh \
 && chown -R splice:splice /home/splice

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
CMD ["/entrypoint.sh"]
