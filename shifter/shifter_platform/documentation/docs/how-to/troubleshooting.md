# Troubleshooting Guide

Common issues and how to resolve them.

## Range Issues

### Range Stuck in "Provisioning"

**Symptoms**: Status shows "Provisioning" for more than 10 minutes.

**Solutions**:
1. Wait a bit longer - some scenarios take 10-15 minutes
2. Cancel the range and relaunch
3. If repeated failures, check your agent file is valid

### Range Shows "Failed"

**Symptoms**: Status shows "Failed" with an error message.

**Solutions**:
1. Read the error message - it usually indicates the cause
2. Check your agent file:
   - Is it the right format for the OS you selected?
   - Is the file corrupted? Try re-downloading from your console
3. Try a different scenario (Basic Range is most reliable)
4. Destroy and relaunch

### Can't Launch Range - "Already Have Active Range"

**Symptoms**: Launch button disabled or error about existing range.

**Solution**: Destroy your current range first. Go to Ranges, click Destroy on the active range.

## Terminal Issues

### Terminal Won't Connect

**Symptoms**: Terminal shows "Connecting..." indefinitely or "Not connected".

**Solutions**:
1. Refresh the page
2. Wait a minute - instance may still be starting
3. Check if range is in "Ready" status
4. Try a different browser

### Terminal Disconnects Frequently

**Symptoms**: Connection drops, have to reconnect.

**Solutions**:
1. Check your network connection
2. Avoid letting the browser tab go idle for long periods
3. Refresh and reconnect

### RDP Button Does Nothing

**Symptoms**: Clicking RDP doesn't open a new window.

**Solutions**:
1. Check browser popup blocker - allow popups from Shifter
2. Try right-click > "Open in new tab"
3. Wait for instance to fully boot (RDP service may not be ready)

## Agent Issues

### Upload Fails

**Symptoms**: Upload errors or stuck at 0%.

**Solutions**:
1. Check file size - max 2GB per file
2. Check total storage - max 5GB across all agents
3. Verify file format is supported
4. Try a different browser
5. Check network connection

### Agent Shows Wrong OS

**Symptoms**: Agent listed as wrong platform.

**Cause**: OS is detected from file format, not contents.

**Solution**: If detection is wrong, delete and re-upload with correct format. Ensure you're using:
- `.msi` or `.zip` for Windows
- `.tar.gz` for Linux shell installer
- `.deb` for Debian/Ubuntu
- `.rpm` for RHEL/CentOS

### No Alerts in Console After Attack

**Symptoms**: Running attacks but no alerts appear.

**Solutions**:
1. Verify agent is installed and connected:
   - Check your XDR/XSIAM console for agent status
   - Agent should show as "Connected" or similar
2. Run a more obvious attack:
   - Execute known malware samples
   - Run detection test tools
   - Trigger behavioral detections
3. Check console filters:
   - Ensure you're looking at the right time range
   - Check severity filters aren't hiding alerts
4. Wait a few minutes - some alerts take time to process

## NGFW Issues

### NGFW Stuck Provisioning

**Symptoms**: Provisioning progress stuck for 30+ minutes.

**Solutions**:
1. NGFW provisioning genuinely takes 15-30 minutes - be patient
2. If stuck beyond 45 minutes, try deprovisioning and starting over
3. Verify your deployment profile authcode is valid
4. Check SCM credential has correct PIN

### Can't Associate Device in SCM

**Symptoms**: SCM rejects the serial number or association fails.

**Solutions**:
1. Double-check serial number (copy-paste to avoid typos)
2. Verify SCM folder exists and accepts new devices
3. Check PIN hasn't expired
4. Ensure you have permissions in SCM

### NGFW-Enabled Range Won't Launch

**Symptoms**: Launching Basic Range with NGFW or Cortex BYOT fails.

**Solutions**:
1. Verify NGFW status is "Ready" (not "Provisioning" or "Failed")
2. Complete SCM association and XDR/XSIAM connection first
3. Check NGFW wasn't deprovisioned

### No Network Alerts in XDR/XSIAM

**Symptoms**: Have endpoint alerts but no network/NGFW alerts.

**Solutions**:
1. Verify NGFW is connected in XDR/XSIAM settings
2. Check log forwarding is configured in SCM
3. Generate network traffic that produces logs:
   - HTTP requests (not just ICMP/ping)
   - Known bad URLs or IPs
   - Suspicious traffic patterns

## Account Issues

### Can't Access Certain Features

**Symptoms**: Buttons disabled, features unavailable.

**Solutions**:
1. Ensure you're logged in
2. Check if feature requires setup first (e.g., NGFW scenarios require NGFW)
3. Contact support if you believe this is an error

## Getting More Help

If none of these solutions work:
1. Note the exact error message
2. Note what you were trying to do
3. Contact support (see [Support](../reference/support.md))
