# base image: alpine:3.19
FROM alpine@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b

RUN apk add --no-cache openssh-server ca-certificates nmap \
 && ssh-keygen -A \
 && adduser -D -s /bin/sh splice \
 && mkdir -p /home/splice/.ssh \
 && chown -R splice:splice /home/splice

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
CMD ["/entrypoint.sh"]
