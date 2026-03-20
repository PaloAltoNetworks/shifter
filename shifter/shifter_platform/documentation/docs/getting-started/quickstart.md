# Quickstart

Launch your first range in 5 minutes.

## Prerequisites

- XDR or XSIAM agent installer downloaded from your console
- Windows (`.msi`), Linux shell (`.tar.gz`), Debian (`.deb`), or RPM (`.rpm`)

## Steps

### 1. Upload Your Agent

1. Go to **Assets > Agents** in the sidebar
2. Enter a name you'll recognize (e.g., "Acme Corp XSIAM")
3. Select your installer file
4. Click **Upload Agent**

### 2. Launch a Range

1. Go to **Ranges** in the sidebar
2. Select **Basic Range** scenario
3. Select victim OS (Windows or Linux)
4. Select your uploaded agent
5. Click **Launch Range**

### 3. Wait for Provisioning

Typically 2-5 minutes. You'll see status updates:

- **Pending** - Queued for provisioning
- **Provisioning** - Infrastructure spinning up
- **Ready** - Range is live

### 4. Access Your Range

Once ready:

1. Go to **Terminal** in the sidebar
2. Click on an instance tab to open SSH
3. For Windows/Kali GUI: click the **RDP** button

## What You Get

Basic Range includes:

- **Attacker** - Kali Linux with standard attack tools
- **Workstation** - Your selected OS with your agent installed

Your agent reports to your XDR/XSIAM console. Run attacks from Kali, see alerts in your console.

## Next Steps

- [Basic Range Details](../scenarios/basic-range) - Full scenario documentation
- [Terminal Guide](../features/terminal) - SSH and RDP access
- [Other Scenarios](../scenarios/) - AD labs, NGFW integration
