# Run Your First Demo

Complete walkthrough: download agent, upload to Shifter, launch range, run an attack, see alert.

## Before You Start

You need:

- Access to your XDR or XSIAM console
- A Shifter account (you're logged in if you're reading this)

Time: ~10 minutes total

## Step 1: Download Your Agent

1. Log into your XDR or XSIAM console
2. Navigate to agent downloads (location varies by console version)
3. Download the installer for your target OS:

   - Windows: `.msi` file
   - Linux: `.tar.gz` file (contains shell installer)

Save it somewhere you can find it.

## Step 2: Upload Agent to Shifter

1. In Shifter, go to **Assets > Agents**
2. Enter a name: something like "My XDR Agent" or "Customer Demo"
3. Click the file input and select your downloaded installer
4. Click **Upload Agent**
5. Wait for upload to complete (progress bar shows status)

## Step 3: Launch a Range

1. Go to **Ranges** in the sidebar
2. In the "Launch a Range" tile:

   - Select **Basic Range** from the Scenario dropdown
   - Select victim OS (match your agent - Windows or Linux)
   - Select your uploaded agent
3. Click **Launch Range**

## Step 4: Wait for Provisioning

Watch the status in the range tile:

- **Pending** → queued
- **Provisioning** → building infrastructure
- **Ready** → you're good to go

Typically 2-5 minutes.

## Step 5: Connect to Your Range

1. Go to **Terminal** in the sidebar
2. You'll see tabs for each instance:

   - **Attacker** (Kali)
   - **Workstation** (your victim)
3. Click the **Attacker** tab
4. Terminal connects automatically

## Step 6: Run a Simple Attack

In the Kali terminal, run a basic test:

```bash
# Scan the victim (find its IP first)
nmap -sV 10.0.0.0/24

# Or run a simple detection test
curl http://workstation/eicar.txt
```

For a more interesting demo, use Metasploit or other pre-installed tools.

## Step 7: Check Your Console

1. Go to your XDR/XSIAM console
2. Navigate to Alerts or Incidents
3. You should see alerts from your attack activity

Alerts typically appear within seconds to a few minutes.

## Step 8: Clean Up

When done:

1. Go to **Ranges** in Shifter
2. Click **Destroy** on your range
3. Confirm destruction

## What's Next?

- Try [AD Attack Lab](../scenarios/ad-attack-lab) for Active Directory attacks
- Set up [NGFW integration](ngfw-demo) for network visibility
- Explore the [Terminal features](../features/terminal) like split view

## Troubleshooting

**Range stuck provisioning?**
Wait 10 minutes. If still stuck, cancel and relaunch.

**No alerts appearing?**
- Verify agent shows as connected in your console
- Try a more obvious attack (malware sample, known bad activity)
- Check console alert filters

**Can't connect to terminal?**
Refresh the page. If still failing, the instance may still be starting up.
