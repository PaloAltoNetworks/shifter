# Shifter Ubuntu scenario pod image.
#
# Runs the same provisioning script set as the VM builds, minus aws-ssm and
# cleanup. Launches sshd + apache2 + mysqld + vsftpd + xrdp + xrdp-sesman
# under supervisord so the pod answers the same attack surface a VM does.
#
# Build context: the `shifter/packer` directory (same as the kali container).

FROM docker.io/library/ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        openssh-server \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

COPY scripts/ /tmp/shifter-scripts/
RUN chmod +x /tmp/shifter-scripts/lib/systemd.sh \
    && find /tmp/shifter-scripts -type f -name "*.sh" -exec chmod +x {} \;

RUN set -eux; \
    /tmp/shifter-scripts/ubuntu/base.sh; \
    /tmp/shifter-scripts/ubuntu/services.sh; \
    /tmp/shifter-scripts/ubuntu/tools.sh; \
    /tmp/shifter-scripts/ubuntu/desktop.sh; \
    /tmp/shifter-scripts/ubuntu/claude-code.sh

COPY containers/ubuntu/supervisord.conf /etc/supervisor/conf.d/shifter.conf
COPY containers/ubuntu/entrypoint.sh /usr/local/bin/shifter-pod-entrypoint
RUN chmod +x /usr/local/bin/shifter-pod-entrypoint \
    && install -d -m 0755 /var/log/supervisor /var/run/sshd

# SSH (22), HTTP (80), MySQL (3306), RDP (3389), FTP (21).
EXPOSE 21 22 80 3306 3389

ENTRYPOINT ["/usr/local/bin/shifter-pod-entrypoint"]
