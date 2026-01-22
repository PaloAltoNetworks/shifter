# FAQ

## Provisioning

**How long does provisioning take?**

2-5 minutes for most scenarios. Larger scenarios (Cortex BYOT) take longer.

**Why is my range stuck in "Provisioning"?**

Provisioning involves creating VMs, configuring networking, and installing agents. If it's been more than 10 minutes, try canceling and relaunching. If the problem persists, contact support.

**Can I cancel a provisioning range?**

Yes. Go to the Ranges page, click Cancel on the range. This terminates the provisioning process.

## Ranges

**Can I have multiple ranges at once?**

Currently limited to one active range at a time. Destroy your current range before launching another.

**How do I destroy a range?**

Ranges page → click Destroy on your range. This is irreversible.

## Agents

**What agent formats are supported?**

- Windows MSI (`.msi`) or ZIP (`.zip`)
- Linux shell installer (`.tar.gz`)
- Debian package (`.deb`)
- RPM package (`.rpm`)

**How much storage do I have?**

2GB per file, 5GB total across all agents.

**Where do I download agents?**

From your XDR or XSIAM console. The exact location depends on your console version.

## Alerts

**Where do alerts appear?**

In your XDR/XSIAM console - the same one you downloaded the agent from. Alerts typically appear within seconds of an attack.

**Why aren't I seeing alerts?**

1. Verify the agent is installed (check Agent status in your console)
2. Ensure your attack generates detectable activity
3. Check your console's alert filters

## NGFW

**Do I need NGFW for basic demos?**

No. NGFW is optional and only needed if you want traffic logging in XDR/XSIAM.

**Why does NGFW setup require credentials?**

NGFW instances must register with Strata Cloud Manager and connect to your XDR/XSIAM. Credentials enable this integration.
