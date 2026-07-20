# base image: debian:12-slim
FROM debian@sha256:fac46bff2e02f51425b6e33b0e1169f55dfb053d83511ca28aa50c09fd5ed7a4

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openssh-server sudo gnupg git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /run/sshd

# Default users are seeded via the AD directory + local entrypoint.
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
CMD ["/entrypoint.sh"]
