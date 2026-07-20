#cloud-config
write_files:
  - path: /usr/local/sbin/configure-shifter-openvpn.py
    owner: root:root
    permissions: "0700"
    content: |
      #!/usr/bin/env python3
      import json
      import pathlib
      import subprocess

      import boto3

      secret_id = "shifter/${environment}/range/${range_id}/vpn-${request_uuid}-server"
      payload = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)["SecretString"]
      material = json.loads(payload)
      expected = {"ca", "certificate", "private_key", "tls_crypt"}
      if set(material) != expected:
          raise RuntimeError("OpenVPN server identity has an invalid shape")

      directory = pathlib.Path("/etc/openvpn/server")
      directory.mkdir(mode=0o700, parents=True, exist_ok=True)
      files = {
          "ca.crt": material["ca"],
          "server.crt": material["certificate"],
          "server.key": material["private_key"],
          "tls-crypt.key": material["tls_crypt"],
      }
      for name, value in files.items():
          path = directory / name
          path.write_text(value, encoding="utf-8")
          path.chmod(0o600)

      config = """port 1194
      proto udp4
      dev tun
      topology subnet
      server 172.30.0.0 255.255.255.0
      ca /etc/openvpn/server/ca.crt
      cert /etc/openvpn/server/server.crt
      key /etc/openvpn/server/server.key
      tls-crypt /etc/openvpn/server/tls-crypt.key
      verify-client-cert require
      remote-cert-eku "TLS Web Client Authentication"
      push "route ${target_ip} 255.255.255.255"
      keepalive 10 60
      persist-key
      persist-tun
      user nobody
      group nogroup
      auth SHA256
      cipher AES-256-GCM
      data-ciphers AES-256-GCM:AES-128-GCM
      tls-version-min 1.2
      explicit-exit-notify 1
      verb 3
      """
      (directory / "server.conf").write_text(config, encoding="utf-8")
      (directory / "server.conf").chmod(0o600)

      pathlib.Path("/etc/sysctl.d/90-shifter-openvpn.conf").write_text("net.ipv4.ip_forward=1\n", encoding="utf-8")
      subprocess.run(["sysctl", "--system"], check=True, stdout=subprocess.DEVNULL)
      rules = [
          ["iptables", "-P", "FORWARD", "DROP"],
          ["iptables", "-A", "FORWARD", "-i", "tun0", "-d", "${target_ip}/32", "-j", "ACCEPT"],
          ["iptables", "-A", "FORWARD", "-o", "tun0", "-s", "${target_ip}/32", "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"],
          ["iptables", "-t", "nat", "-A", "POSTROUTING", "-s", "172.30.0.0/24", "-d", "${target_ip}/32", "-j", "MASQUERADE"],
      ]
      for rule in rules:
          subprocess.run(rule, check=True)
      subprocess.run(["systemctl", "enable", "--now", "openvpn-server@server"], check=True)
      subprocess.run(["systemctl", "daemon-reload"], check=True)
      subprocess.run(["systemctl", "enable", "--now", "shifter-openvpn-health"], check=True)
  - path: /usr/local/sbin/shifter-openvpn-health.py
    owner: root:root
    permissions: "0700"
    content: |
      #!/usr/bin/env python3
      import socketserver
      import subprocess

      TARGET = "${target_ip}/32"

      def healthy():
          active = subprocess.run(
              ["systemctl", "is-active", "--quiet", "openvpn-server@server"],
              check=False,
          ).returncode == 0
          policy = subprocess.run(
              ["iptables", "-S", "FORWARD"],
              check=False,
              capture_output=True,
              text=True,
          ).stdout.splitlines()
          rules = (
              ["iptables", "-C", "FORWARD", "-i", "tun0", "-d", TARGET, "-j", "ACCEPT"],
              [
                  "iptables", "-C", "FORWARD", "-o", "tun0", "-s", TARGET,
                  "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT",
              ],
              [
                  "iptables", "-t", "nat", "-C", "POSTROUTING", "-s", "172.30.0.0/24",
                  "-d", TARGET, "-j", "MASQUERADE",
              ],
          )
          return active and "-P FORWARD DROP" in policy and all(
              subprocess.run(rule, check=False).returncode == 0 for rule in rules
          )

      class Handler(socketserver.BaseRequestHandler):
          def handle(self):
              if healthy():
                  self.request.sendall(b"ready\n")

      class Server(socketserver.ThreadingTCPServer):
          allow_reuse_address = True

      with Server(("0.0.0.0", 1195), Handler) as server:
          server.serve_forever()
  - path: /etc/systemd/system/shifter-openvpn-health.service
    owner: root:root
    permissions: "0644"
    content: |
      [Unit]
      Description=Shifter OpenVPN service and target-policy readiness
      Requires=openvpn-server@server.service
      After=openvpn-server@server.service
      BindsTo=openvpn-server@server.service

      [Service]
      Type=simple
      ExecStart=/usr/local/sbin/shifter-openvpn-health.py
      Restart=on-failure
      RestartSec=2

      [Install]
      WantedBy=multi-user.target
runcmd:
  - [python3, /usr/local/sbin/configure-shifter-openvpn.py]
