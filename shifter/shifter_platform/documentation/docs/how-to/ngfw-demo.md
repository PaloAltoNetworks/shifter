# Set Up NGFW Demo

Complete walkthrough: add credentials, provision NGFW, associate in SCM, launch NGFW-enabled range.

## Before You Start

You need:

- Access to Strata Cloud Manager (SCM)
- Access to your XDR or XSIAM console
- Software NGFW Credits deployment profile with authcode
- SCM folder configured for device onboarding

Time: ~45 minutes (mostly waiting for provisioning)

## Step 1: Add Deployment Profile Credential

The deployment profile contains the authcode that licenses your NGFW.

1. Go to **Assets > Credentials** in Shifter
2. Click **Add Credential**
3. Select **Deployment Profile**
4. Enter:

   - **Name**: Something descriptive (e.g., "Lab NGFW License")
   - **Authcode**: Your Software NGFW Credits authcode
5. Save

## Step 2: Add SCM Credential

The SCM credential enables automatic device registration.

1. Go to **Assets > Credentials**
2. Click **Add Credential**
3. Select **SCM Credential**
4. Enter:

   - **Name**: Descriptive name
   - **SCM Folder**: The folder in SCM where the device will register
   - **PIN ID**: Auto-registration PIN from SCM
   - **SLS Region**: Your Strata Logging Service region
5. Save

### Where to Get These Values

**SCM Folder**: In SCM, go to Configuration > NGFW and Prisma Access > Folders
**PIN ID**: In SCM, go to Configuration > Device Associations > Get PIN
**SLS Region**: Check your SCM dashboard or account settings

## Step 3: Provision the NGFW

1. Go to **Assets > NGFWs**
2. Click **Setup NGFW**
3. **Step 1 - Name & Profile**:

   - Enter a name for the NGFW
   - Select your deployment profile
   - Click Next
4. **Step 2 - Registration**:

   - Select your SCM credential
   - Click Next
5. **Step 3 - Confirm**:

   - Review settings
   - Click **Provision NGFW**
6. **Step 4 - Provisioning**:

   - Wait 15-30 minutes
   - Watch the progress steps

## Step 4: Associate Device in SCM

When provisioning reaches "Action Required":

1. Note the **Serial Number** shown in Shifter
2. Go to **Strata Cloud Manager**
3. Navigate to **Configuration > Device Associations**
4. Click **Add Device**
5. Enter the serial number
6. Associate to your folder

## Step 5: Connect to XDR/XSIAM

1. Go to your **XDR or XSIAM console**
2. Navigate to **Settings > NGFW**
3. Click **Add New Instance**
4. Follow the prompts to connect the firewall

## Step 6: Complete Setup in Shifter

1. Return to Shifter's NGFW wizard
2. Click **Complete Setup**
3. Wait for final configuration (up to 15 minutes)
4. Success message appears when ready

## Step 7: Launch NGFW-Enabled Range

1. Go to **Ranges**
2. Select **Basic Range with NGFW** or **Cortex BYOT**
3. Select your agent
4. Click **Launch Range**

## Verifying the Setup

**In your range:**

- Traffic between attacker and victim routes through NGFW
- Run attacks from Kali terminal

**In XDR/XSIAM:**

- You should see both:
  - Endpoint alerts from your agent
  - Network alerts from NGFW logs
- Alerts correlate attack activity across sources

## Troubleshooting

**NGFW stuck provisioning?**
- Check that your authcode is valid
- Ensure SCM credentials are correct
- Try deprovisioning and starting over

**Device won't associate in SCM?**
- Verify the serial number matches
- Check that the SCM folder allows new devices
- Ensure PIN hasn't expired

**No network alerts in XDR/XSIAM?**
- Verify NGFW shows as connected in XDR/XSIAM settings
- Check log forwarding is configured in SCM
- Generate obvious traffic (not just ICMP)

**Range launch fails with NGFW?**
- Ensure NGFW status is "Ready" before launching
- Check that NGFW wasn't deprovisioned
