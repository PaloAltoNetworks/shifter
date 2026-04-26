FROM debian:12-slim

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
