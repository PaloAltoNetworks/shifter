# Smoke Linux (AWS)

A minimal, agent-free range used by the platform post-deploy smoke on the AWS
EC2 range backend (`run_post_deploy_smoke --variant linux`). It provisions two
Linux guests on a single switched LAN, both built from the base range images:

- `attacker`: Kali, reachable over an SSH participant access channel.
- `victim`: Ubuntu, reachable over an SSH participant access channel.

This is the portable-addressing variant of `smoke-linux`: it authors no CIDR,
gateway, or fixed guest IPs, so the AWS EC2 backend allocates a subnet inside
the range VPC instead of rejecting authored addressing. The smoke validates the
platform (range provisioning, guest connectivity over SSH, and teardown), not
scenario content. There is no XDR agent, no domain, and no authored credentials;
the per-range SSH key is provisioned automatically at realization.
