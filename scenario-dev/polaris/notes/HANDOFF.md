# NORTHSTORM Range — Session Handoff

This file is preserved as **historical session context**, not as a current
topology spec.

For the live range, use these instead:

1. `scenario-dev/polaris/build/docker-compose.yml`
2. `scenario-dev/polaris/build/ctfd-challenges.json`
3. `scenario-dev/polaris/tests/walkthroughs/`

## Current high-level topology

- `shared`: A0, DNS, A14
- `corporate`: A1, A3, A4, A14, A15, A16
- `scada`: A5, A15
- `lab`: A6, A7, A8, A16
- `bunker-ot`: A9, A10, A11, A12, A13
- `splice-link`: A14, A9
- A2 is a separate Windows VM in the range VPC

## Current gameplay-critical pivots

- A3 is **corporate-only**
- A15 is the **only** Front Office pivot into SCADA
- A16 is the **only** Front Office pivot into Lab
- A7 is a **shared service** but is **not** reachable from Kali directly
- Flag 19 is a **per-range splice trigger**, not a collective unlock

## How to Access

```bash
# SSH to builder VM
gcloud compute ssh ctf-range-builder --zone=us-east4-a --ssh-key-file=~/.ssh/id_rsa

# Check containers
cd /home/atomik/range && sudo docker compose ps

# Get a Kali shell
sudo docker exec -it a14-kali /bin/bash

# Start the Windows DC (if stopped)
gcloud compute instances start ctf-test-a2-windc --zone=us-east4-a

# Full rebuild after code changes
sudo docker compose down && sudo docker network prune -f && sudo docker compose up -d --build
```
