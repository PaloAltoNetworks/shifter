# NGFW

Set up persistent Next-Generation Firewalls for traffic logging.

## What is NGFW?

A software firewall that routes range traffic and logs it to your XDR/XSIAM. Use NGFW scenarios to demonstrate network-level visibility alongside endpoint detection.

## Prerequisites

Before setting up NGFW:

1. Add SCM credentials (see [Credentials](credentials))
2. Add a deployment profile credential
3. Have access to Strata Cloud Manager

## Setup Wizard

### Step 1: Name and Profile

1. Go to **Assets > NGFWs**
2. Click **Setup NGFW**
3. Enter a name for the NGFW
4. Select a deployment profile

### Step 2: Registration

Select your SCM credential for PIN-based device registration.

### Step 3: Confirmation

Review your settings before proceeding.

### Step 4: Provisioning

NGFW provisioning begins. This takes several minutes.

## After Provisioning

Once the NGFW is ready:

1. **Associate in SCM**: Add the device to your Strata Cloud Manager folder
2. **Connect to XDR/XSIAM**: Configure log forwarding in SCM
3. **Launch NGFW Range**: Use "Basic Range with NGFW" or "Cortex BYOT"

## Accessing NGFW Management

### CLI Access

Access the PAN-OS command line interface directly from Shifter:

1. Go to your NGFW detail page
2. Click **Open CLI** in the Management Access section
3. A new browser tab opens with SSH access to the NGFW
4. Login username: `admin`

Use the CLI for configuration changes, troubleshooting, and advanced operations.

### GUI Access

Access the PAN-OS web interface:

**Option 1: SSH Tunnel (Recommended)**
1. Click **Open CLI** to establish SSH connection
2. From your local terminal, create an SSH tunnel:
   ```bash
   ssh -L 8443:<management_ip>:443 -i <key> admin@<management_ip>
   ```
3. Browse to `https://localhost:8443`

**Option 2: VPN Access**
If you have VPN access to the VPC, browse directly to `https://<management_ip>`

**Option 3: Kali Desktop**
If you have an active range with Kali, use the browser from within the Kali desktop

**Login Credentials:**
- Username: `admin`
- Password: Set during initial bootstrap (check SCM or contact admin)

## Managing NGFWs

From the NGFW page:

- View provisioned NGFWs with status
- See serial numbers and creation dates
- Refresh status
- Deprovision (destroy) an NGFW

## NGFW Status

| Status | Meaning |
|--------|---------|
| Provisioning | NGFW being created |
| Awaiting Association | Waiting for SCM device association |
| Ready | NGFW available for use |
| Deprovisioning | NGFW being destroyed |
| Failed | Setup error occurred |

## Tips

- NGFWs are persistent - set up once, reuse across multiple ranges
- Complete SCM association before launching NGFW ranges
- Deprovision NGFWs you no longer need to free resources
