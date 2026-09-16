"""Bash bootstrap-script templates for the POLARIS range plan.

Extracted from ``polaris_range_bootstrap.py`` (Sonar S104). These are the SSM
RunCommand script bodies that :class:`PolarisRangeBootstrapPlan` injects as its
setup steps; keeping the large embedded bash in its own module keeps the plan
module under the Sonar line budget. The plan module imports them back, so its
public surface is unchanged.
"""

# Bash run on the polaris VM Ubuntu host via SSM. Rewrites the bake-time
# docker-compose.override.yml with this range's DC IP + per-instance kali
# pubkey, then force-recreates the dns + a14-kali containers so their
# entrypoints pick up the new env vars and re-render their internal state.
POLARIS_RANGE_BOOTSTRAP_SCRIPT = """#!/bin/bash
set -euo pipefail

DC_IP="{{ dc_ip }}"
KALI_PUBKEY="{{ public_key }}"

if [[ -z "$DC_IP" ]]; then
  echo "polaris bootstrap: DC_IP is empty, refusing to rewrite override" >&2
  exit 1
fi
if [[ -z "$KALI_PUBKEY" ]]; then
  echo "polaris bootstrap: KALI_PUBKEY is empty, refusing to rewrite override" >&2
  exit 1
fi
{{ aws_agent_setup_block }}
cd /opt/polaris/scenario-dev/polaris/build

# Install the exact reviewed helper carried by the provisioner image. The
# Compose override mounts it read-only into a14-kali and makes it the entrypoint
# wrapper, so every later recreation repairs the writable-layer projection.
install -d -o root -g root -m 0755 /opt/polaris/libexec
HELPER_TMP="$(mktemp /opt/polaris/libexec/.polaris-splice-credential.XXXXXX)"
printf '%s' "{{ splice_credential_helper_b64 }}" | base64 -d > "$HELPER_TMP"
chmod 0755 "$HELPER_TMP"
mv "$HELPER_TMP" /opt/polaris/libexec/polaris-splice-credential.py

# Per-range Ed25519 keypair for the A9 splice-relay credential gate
# (#707). The private half is staged on a14-kali via the entrypoint
# (`KALI_SPLICE_PRIVATE_KEY_B64`, base64 so the value stays single-line
# inside the compose override); the public half is installed into
# a9-splice's /root/.ssh/authorized_keys via A9_AUTHORIZED_KEY. A9's
# sshd has PasswordAuthentication off (Dockerfile change), so this key
# is the only path to the Bunker OT controllers. Per-range generation
# means an exfil from one participant's a14-kali cannot be used to
# attack another range — even though ranges are network-isolated, the
# key is treated as scenario credential material with least exposure.
SPLICE_KEY_DIR="$(mktemp -d)"
chmod 700 "$SPLICE_KEY_DIR"
ssh-keygen -t ed25519 -N "" -C "splice-relay@$(date -u +%Y%m%dT%H%M%SZ)" \
    -f "$SPLICE_KEY_DIR/splice_relay" -q
SPLICE_PRIVATE_KEY_B64="$(base64 -w0 < "$SPLICE_KEY_DIR/splice_relay")"
SPLICE_PUBLIC_KEY="$(cat "$SPLICE_KEY_DIR/splice_relay.pub")"
shred -u "$SPLICE_KEY_DIR/splice_relay" "$SPLICE_KEY_DIR/splice_relay.pub" 2>/dev/null \
    || rm -f "$SPLICE_KEY_DIR/splice_relay" "$SPLICE_KEY_DIR/splice_relay.pub"
rmdir "$SPLICE_KEY_DIR"

# Atomic rewrite via tmp + mv so docker compose never sees a partial file.
cat > docker-compose.override.yml.new <<COMPOSE_EOF
services:
  a14-kali:
    ports:
      - "22:22"
      - "3389:3389"
    environment:
      KALI_AUTHORIZED_KEY: "$KALI_PUBKEY"
      KALI_SPLICE_PRIVATE_KEY_B64: "$SPLICE_PRIVATE_KEY_B64"{{ aws_agent_compose_block }}{{ gcp_agent_compose_block }}
    entrypoint:
      - /usr/local/libexec/polaris-splice-credential.py
      - entrypoint
  a9-splice:
    environment:
      A9_AUTHORIZED_KEY: "$SPLICE_PUBLIC_KEY"
  dns:
    environment:
      DC01_IP: "$DC_IP"
COMPOSE_EOF
mv docker-compose.override.yml.new docker-compose.override.yml

# Force-recreate only the containers whose env vars changed. The other
# 14 stay running undisturbed. a9-splice was added in #707 because the
# A9 entrypoint now consumes A9_AUTHORIZED_KEY.
docker compose up -d --force-recreate dns a14-kali a9-splice

# The baked compose attaches a14-kali to splice-link at container start
# (legacy pre-gate wiring). Strip that here — the splice landing is gated
# on flag 19 via the polaris-splice-watcher systemd service, which will
# reattach a14-kali once A5 reports runaway_complete. Docker compose
# prefixes network names with the project name (here: "build"), so the
# actual name is "build_splice-link"; discover by suffix to stay robust
# against project-name changes. Non-fatal if already disconnected.
splice_net_name=$(docker network ls --format '{{.Name}}' | grep -E '(^|_)splice-link$' | head -n1 || true)
if [[ -n "$splice_net_name" ]]; then
  docker network disconnect "$splice_net_name" a14-kali 2>/dev/null || true
fi

# Wait up to 60s for the three recreated containers to be Up before
# declaring success.
# `docker ps --format` uses Go template syntax (e.g. .Names, .Status)
# inside double-brace delimiters. The orchestrator's render pass uses a
# regex that requires word characters between the delimiters, so Go
# template tokens with a leading dot pass through untouched. (Don't
# describe Jinja-style placeholders inline in this comment — the
# renderer would see them too and demand a substitution variable.)
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  ps_out=$(docker ps --format '{{.Names}} {{.Status}}' || true)
  a14_up=$(echo "$ps_out" | grep -c '^a14-kali .*Up' || true)
  dns_up=$(echo "$ps_out" | grep -c '^dns .*Up' || true)
  a9_up=$(echo "$ps_out" | grep -c '^a9-splice .*Up' || true)
  if [[ "$a14_up" == "1" && "$dns_up" == "1" && "$a9_up" == "1" ]]; then
    echo "polaris bootstrap: a14-kali + dns + a9-splice up after attempt $attempt"
    break
  fi
  sleep 5
done

# The participant lands in the Polaris a14-kali container, not the
# standalone Kali image path. Enforce the normal Kali user experience at
# bootstrap time so the container remains authoritative even when the
# upstream compose tarball changes or a14-kali is force-recreated:
# - `kali` can use sudo with its assigned range password.
# - XRDP's Xorg backend can launch for non-console sessions.
# - Participant SSH presents the provisioner-issued host key recorded in the
#   range output, so the portal can pin the browser terminal connection.
if [ ! -s /etc/ssh/ssh_host_ed25519_key ]; then
  echo "polaris bootstrap: provisioner-issued host key is missing" >&2
  exit 1
fi
docker cp /etc/ssh/ssh_host_ed25519_key a14-kali:/etc/ssh/ssh_host_ed25519_key
docker exec a14-kali sh -c '
set -eu
if ! id kali >/dev/null 2>&1; then
  echo "polaris bootstrap: kali user missing in a14-kali" >&2
  exit 1
fi
install -d -o kali -g kali -m 0755 /home/kali
if ! getent group sudo >/dev/null 2>&1; then
  groupadd sudo
fi
usermod -aG sudo kali

chown root:root /etc/ssh/ssh_host_ed25519_key
chmod 0600 /etc/ssh/ssh_host_ed25519_key
ssh-keygen -y -f /etc/ssh/ssh_host_ed25519_key > /etc/ssh/ssh_host_ed25519_key.pub
chown root:root /etc/ssh/ssh_host_ed25519_key.pub
chmod 0644 /etc/ssh/ssh_host_ed25519_key.pub

install -d -m 0755 /etc/sudoers.d
printf "%s\n" "kali ALL=(ALL:ALL) NOPASSWD: ALL" > /etc/sudoers.d/90-shifter-kali
chmod 0440 /etc/sudoers.d/90-shifter-kali

# The packaged nmap launcher execs /usr/lib/nmap/nmap. Some upstream Kali
# images attach NET_ADMIN file capabilities to that real binary; Docker rejects
# exec entirely when a file capability is outside the container bounding set.
# Root already has the required NET_RAW capability, so remove the incompatible
# file capability and let participants elevate through passwordless sudo.
if command -v setcap >/dev/null 2>&1 && [ -e /usr/lib/nmap/nmap ]; then
  setcap -r /usr/lib/nmap/nmap 2>/dev/null || true
fi

# tmux owns wheel events so its history remains scrollable. The xterm standard
# Shift+drag bypass selects browser text; the portal copies that selection and
# handles right-click paste and Ctrl+Shift+C/V. Apply the option both to future
# servers and to a tmux server that may already be running.
printf "%s\n" \
  "set -g mouse on" \
  "set -g set-clipboard on" \
  "bind-key -n F11 copy-mode -eu" \
  "bind-key -T copy-mode F11 send-keys -X -N 3 scroll-up" \
  "bind-key -T copy-mode-vi F11 send-keys -X -N 3 scroll-up" \
  "bind-key -T copy-mode F12 send-keys -X -N 3 scroll-down" \
  "bind-key -T copy-mode-vi F12 send-keys -X -N 3 scroll-down" \
  > /home/kali/.tmux.conf
chown kali:kali /home/kali/.tmux.conf
chmod 0644 /home/kali/.tmux.conf

install -d -m 0755 /etc/X11
if [ -f /etc/X11/Xwrapper.config ] && [ ! -f /etc/X11/Xwrapper.config.shifter.bak ]; then
  cp /etc/X11/Xwrapper.config /etc/X11/Xwrapper.config.shifter.bak
fi
if [ ! -f /etc/X11/Xwrapper.config ]; then
  touch /etc/X11/Xwrapper.config
fi
if grep -q "^allowed_users=" /etc/X11/Xwrapper.config; then
  sed -i "s/^allowed_users=.*/allowed_users=anybody/" /etc/X11/Xwrapper.config
else
  printf "%s\n" "allowed_users=anybody" >> /etc/X11/Xwrapper.config
fi
if grep -q "^needs_root_rights=" /etc/X11/Xwrapper.config; then
  sed -i "s/^needs_root_rights=.*/needs_root_rights=yes/" /etc/X11/Xwrapper.config
else
  printf "%s\n" "needs_root_rights=yes" >> /etc/X11/Xwrapper.config
fi

repair_xrdp_file() {
  source_path="$1"
  mode="$2"
  if [ -e "$source_path" ]; then
    tmp_path="${source_path}.shifter"
    cp -L "$source_path" "$tmp_path"
    chown xrdp:xrdp "$tmp_path"
    chmod "$mode" "$tmp_path"
    mv -f "$tmp_path" "$source_path"
  fi
}
if id xrdp >/dev/null 2>&1; then
  repair_xrdp_file /etc/xrdp/cert.pem 0644
  repair_xrdp_file /etc/xrdp/key.pem 0640
fi
if [ -f /etc/xrdp/xrdp.ini ]; then
  if grep -q "^security_layer=" /etc/xrdp/xrdp.ini; then
    sed -i "s/^security_layer=.*/security_layer=tls/" /etc/xrdp/xrdp.ini
  else
    printf "%s\n" "security_layer=tls" >> /etc/xrdp/xrdp.ini
  fi
  if grep -q "^crypt_level=" /etc/xrdp/xrdp.ini; then
    sed -i "s/^crypt_level=.*/crypt_level=high/" /etc/xrdp/xrdp.ini
  else
    printf "%s\n" "crypt_level=high" >> /etc/xrdp/xrdp.ini
  fi
  if grep -q "^ssl_protocols=" /etc/xrdp/xrdp.ini; then
    sed -i "s/^ssl_protocols=.*/ssl_protocols=TLSv1.2/" /etc/xrdp/xrdp.ini
  else
    printf "%s\n" "ssl_protocols=TLSv1.2" >> /etc/xrdp/xrdp.ini
  fi
fi
'
docker exec --user kali a14-kali tmux set-option -g mouse on 2>/dev/null || true
docker exec --user kali a14-kali tmux set-option -g set-clipboard on 2>/dev/null || true
docker exec --user kali a14-kali tmux bind-key -n F11 copy-mode -eu 2>/dev/null || true
docker exec --user kali a14-kali tmux bind-key -T copy-mode F11 send-keys -X -N 3 scroll-up 2>/dev/null || true
docker exec --user kali a14-kali tmux bind-key -T copy-mode-vi F11 send-keys -X -N 3 scroll-up 2>/dev/null || true
docker exec --user kali a14-kali tmux bind-key -T copy-mode F12 send-keys -X -N 3 scroll-down 2>/dev/null || true
docker exec --user kali a14-kali tmux bind-key -T copy-mode-vi F12 send-keys -X -N 3 scroll-down 2>/dev/null || true
docker restart a14-kali >/dev/null
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if docker ps --format '{{.Names}} {{.Status}}' | grep -q '^a14-kali .*Up'; then
    echo "polaris bootstrap: a14-kali restarted after XRDP repair"
    break
  fi
  sleep 5
done
if ! docker ps --format '{{.Names}} {{.Status}}' | grep -q '^a14-kali .*Up'; then
  echo "polaris bootstrap: a14-kali did not restart after XRDP repair" >&2
  exit 1
fi
if ! docker exec a14-kali id kali | grep -q 'sudo'; then
  echo "polaris bootstrap: kali sudo entitlement missing after repair" >&2
  exit 1
fi
if ! docker exec a14-kali sudo -l -U kali >/dev/null; then
  echo "polaris bootstrap: kali sudoers policy missing after repair" >&2
  exit 1
fi
if ! docker exec a14-kali grep -q '^allowed_users=anybody$' /etc/X11/Xwrapper.config; then
  echo "polaris bootstrap: Xwrapper allowed_users was not repaired" >&2
  exit 1
fi
if ! docker exec a14-kali grep -q '^needs_root_rights=yes$' /etc/X11/Xwrapper.config; then
  echo "polaris bootstrap: Xwrapper needs_root_rights was not repaired" >&2
  exit 1
fi
if docker exec a14-kali test -L /etc/xrdp/key.pem; then
  echo "polaris bootstrap: XRDP key remained a symlink after repair" >&2
  exit 1
fi
if ! docker exec --user xrdp a14-kali test -r /etc/xrdp/key.pem; then
  echo "polaris bootstrap: XRDP key is not readable by xrdp after repair" >&2
  exit 1
fi
if ! docker exec a14-kali grep -q '^security_layer=tls$' /etc/xrdp/xrdp.ini; then
  echo "polaris bootstrap: XRDP security_layer was not repaired" >&2
  exit 1
fi
if ! docker exec a14-kali grep -q '^crypt_level=high$' /etc/xrdp/xrdp.ini; then
  echo "polaris bootstrap: XRDP crypt_level was not repaired" >&2
  exit 1
fi
if ! docker exec a14-kali grep -q '^ssl_protocols=TLSv1.2$' /etc/xrdp/xrdp.ini; then
  echo "polaris bootstrap: XRDP TLS protocol compatibility was not repaired" >&2
  exit 1
fi
echo "polaris bootstrap: kali sudo and XRDP prerequisites enforced"

docker exec a9-splice sh -c '
mkdir -p /root/.ssh
chmod 700 /root/.ssh
'
printf '%s\n' "$SPLICE_PUBLIC_KEY" | docker exec -i a9-splice sh -c '
cat > /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
'

# Use the same helper that entrypoint and fleet repair use. It restores legacy
# running containers without restarting them and fails closed on pair mismatch.
/opt/polaris/libexec/polaris-splice-credential.py host-repair --container a14-kali

# Verify the kali container actually has the per-instance pubkey written
# (the a14 entrypoint reads $KALI_AUTHORIZED_KEY and writes the file).
for attempt in 1 2 3 4 5; do
  if docker exec a14-kali test -s /home/kali/.ssh/authorized_keys 2>/dev/null; then
    echo "polaris bootstrap: kali authorized_keys present"
    break
  fi
  sleep 3
done

# Verify the splice key staging (#707): private key on a14-kali, public
# key in a9-splice. The Bunker chain depends on both.
splice_staged=0
for attempt in 1 2 3 4 5; do
  splice_priv_ok=0
  splice_pub_ok=0
  docker exec a14-kali test -s /home/kali/.ssh/splice_relay 2>/dev/null && splice_priv_ok=1
  docker exec a9-splice test -s /root/.ssh/authorized_keys 2>/dev/null && splice_pub_ok=1
  if [[ "$splice_priv_ok" == "1" && "$splice_pub_ok" == "1" ]]; then
    echo "polaris bootstrap: splice key staged on a14-kali and a9-splice"
    splice_staged=1
    break
  fi
  sleep 3
done
if [[ "$splice_staged" != "1" ]]; then
  echo "polaris bootstrap: splice key staging failed" >&2
  exit 1
fi

echo "polaris bootstrap: complete"
exit 0
"""
