# Agents

Upload and manage your XDR/XSIAM agent installers.

## What's an Agent?

An agent is your XDR or XSIAM installer file. When you launch a range, Shifter deploys this agent to victim machines. Alerts from attacks appear in your XDR/XSIAM console.

## Supported Formats

Upload the installer as downloaded from your XDR/XSIAM console:

| Installer Type | File Extension | Platform |
|----------------|----------------|----------|
| Windows MSI | `.msi` | Windows |
| Windows ZIP | `.zip` | Windows |
| Linux shell | `.tar.gz`, `.tgz` | Linux (generic) |
| Debian package | `.deb` | Debian, Ubuntu |
| RPM package | `.rpm` | RHEL, CentOS, Fedora |

## Storage Limits

- Maximum file size: 2GB per agent
- Total storage: 5GB per user

## Upload an Agent

1. Go to **Assets > Agents** in the sidebar
2. Enter a name (e.g., "Acme Corp XSIAM Production")
3. Select your installer file
4. Click **Upload Agent**
5. Wait for upload to complete

## Manage Agents

From the Agents page you can:

- View all uploaded agents
- See file size and upload date
- Delete agents you no longer need

## Tips

- Use descriptive names - you may have agents for different customers or versions
- Download fresh agents from your console to ensure they're current
- Delete old agents to free up storage space
