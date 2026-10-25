# Shared participant OpenVPN pool server (#2480): OpenVPN plus its authorizing
# controller, in its own network namespace on a pool VM.
#
# The image's default user is unprivileged and cannot start the server. The pool
# VM starts it as root with NET_ADMIN, SETUID and SETGID only, and setpriv then
# switches to the shifter-vpn user keeping NET_ADMIN (tunnel, routes, nftables in
# this namespace) as its only capability. no-new-privileges stops it regaining
# any other.
# base image: alpine:3.22
FROM alpine@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8

LABEL maintainer="Shifter maintainers" \
      org.opencontainers.image.title="shifter-openvpn" \
      org.opencontainers.image.description="Shifter shared participant OpenVPN pool server" \
      org.opencontainers.image.source="https://github.com/Brad-Edwards/shifter" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.authors="Shifter maintainers"

# Minor-version constraints: CI rebuilds without cache pick up patch releases.
RUN apk add --no-cache "nftables~1.1" "openvpn~2.6" "python3~3.12" "setpriv~2.41" \
    && addgroup -S -g 10001 shifter-vpn \
    && adduser -S -D -H -u 10001 -G shifter-vpn -s /sbin/nologin shifter-vpn

WORKDIR /opt/shifter-openvpn
COPY shifter_openvpn ./shifter_openvpn

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 1194/udp 8080/tcp
USER shifter-vpn
ENTRYPOINT ["setpriv", "--reuid=10001", "--regid=10001", "--clear-groups", \
            "--inh-caps=-all,+net_admin", "--ambient-caps=-all,+net_admin", \
            "--", "python3", "-m", "shifter_openvpn"]
