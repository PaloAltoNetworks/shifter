# Shifter Kali scenario pod image.
#
# Runs the same provisioning script set as the VM builds (amazon-ebs and
# googlecompute in kali.pkr.hcl), minus aws-ssm (not applicable to
# containers) and common/cleanup.sh (container image layers are small by
# construction). Launches sshd + xrdp + xfce + caldera under supervisord
# so the pod answers SSH + RDP + caldera the same way a VM does.
#
# Build context: the repository root. Invoke from the `shifter/packer`
# directory so COPY paths resolve relative to scripts/ and containers/.

FROM docker.io/library/debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive

# Supervisor + openssh-server are the pod runtime harness. Packages
# installed by the provisioning scripts below get their own apt calls.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        openssh-server \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

# Provisioning scripts from the Packer tree. The Dockerfile expects the
# build context to be `shifter/packer/`, so these paths resolve from there.
COPY scripts/ /tmp/shifter-scripts/
RUN chmod +x /tmp/shifter-scripts/lib/systemd.sh \
    && find /tmp/shifter-scripts -type f -name "*.sh" -exec chmod +x {} \;

# Run the same cloud-neutral script set the VM builds use. aws-ssm.sh is
# intentionally excluded; cleanup.sh is not used in container builds.
RUN set -eux; \
    /tmp/shifter-scripts/kali/base.sh; \
    /tmp/shifter-scripts/kali/tools.sh; \
    /tmp/shifter-scripts/kali/caldera.sh; \
    /tmp/shifter-scripts/kali/claude-code.sh

# Pod runtime harness.
COPY containers/kali/supervisord.conf /etc/supervisor/conf.d/shifter.conf
COPY containers/kali/entrypoint.sh /usr/local/bin/shifter-pod-entrypoint
RUN chmod +x /usr/local/bin/shifter-pod-entrypoint \
    && install -d -m 0755 /var/log/supervisor /var/run/sshd

# SSH (22), RDP (3389), Caldera UI (8888).
EXPOSE 22 3389 8888

ENTRYPOINT ["/usr/local/bin/shifter-pod-entrypoint"]
