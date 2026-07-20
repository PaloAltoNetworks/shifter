# base image: alpine:3.19
FROM alpine@sha256:6baf43584bcb78f2e5847d1de515f23499913ac9f12bdf834811a3145eb11ca1

RUN apk add --no-cache openssh-server ca-certificates nmap \
 && ssh-keygen -A \
 && adduser -D -s /bin/sh splice \
 && mkdir -p /home/splice/.ssh \
 && chown -R splice:splice /home/splice

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
CMD ["/entrypoint.sh"]
