# NGFW Bootstrap - Validated Process

**Date:** 2026-01-14
**Validated with:** Instance i-0bae542548615fb6d (test-ngfw-manual-5)

## Successful Bootstrap Result

```
hostname: test-ngfw-manual-4
serial: 007955000757740
vm-license: VM-SERIES-4
device-certificate-status: Valid
```

---

## Requirements

### 1. S3 Bootstrap Structure (ALL folders required)

```
bucket/path/
  config/
    init-cfg.txt      <- configuration file
  license/
    authcodes         <- file containing authcode (no extension)
  content/            <- required, can be empty
  software/           <- required, can be empty
```

### 2. init-cfg.txt Template

```
type=dhcp-client
hostname={{ hostname }}
dns-primary=8.8.8.8
dns-secondary=8.8.4.4
panorama-server=cloud
vm-series-auto-registration-pin-id={{ pin_id }}
vm-series-auto-registration-pin-value={{ pin_value }}
dgname={{ scm_folder_name }}
```

**CRITICAL:**
- `panorama-server=cloud` is REQUIRED for SCM registration and device certificate
- Use `vm-series-auto-registration-pin-id` NOT `pin-id`
- Use `vm-series-auto-registration-pin-value` NOT `pin-value`
- No spaces around `=` signs
- No quotes around values

### 3. authcodes File

Plain text file containing just the authcode:
```
D9232090
```

### 4. IAM Role Permissions

The IAM role attached to the NGFW instance MUST have:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::BUCKET_NAME",
        "arn:aws:s3:::BUCKET_NAME/path/to/bootstrap/*"
      ]
    }
  ]
}
```

**CRITICAL:** `s3:ListBucket` is REQUIRED. Without it, PAN-OS cannot discover bootstrap files.

### 5. EC2 User-Data Format

```
vmseries-bootstrap-aws-s3bucket=BUCKET_NAME/path/to/bootstrap
```

**Note:** No `s3://` prefix, no trailing slash.

### 6. EC2 Launch Requirements

- AMI: PA-VM-AWS (e.g., ami-0a2308a59c01dba70 for PA-VM-AWS-12.1.4)
- Instance type: m5.xlarge minimum (4 vCPU for VM-SERIES-4 license)
- IAM instance profile: Must have S3 permissions above
- Key pair: Required for SSH access
- Security group: Must allow SSH (22) and HTTPS (443)

---

## Timeline

- **0:00** - Instance launched
- **~9 min** - SSH port responding (Connection refused)
- **~10 min** - SSH auth working but "Invalid user" (mgmt plane initializing)
- **~11 min** - SSH "Welcome admin" (mgmt plane ready)
- **~11-15 min** - Bootstrap applies (license, device cert, hostname)

Total time from launch to fully bootstrapped: **~11-15 minutes**

---

## SSH Command Execution for PAN-OS

**WRONG** (returns empty or hangs):
```bash
ssh admin@host "show clock"
ssh admin@host 'show system info'
```

**CORRECT** (pipe the command):
```bash
echo "show clock" | ssh -i key.pem -o StrictHostKeyChecking=no -o IdentitiesOnly=yes admin@IP
echo "show system info" | ssh -i key.pem admin@IP
```

**Verification command:**
```bash
echo "show system info" | ssh -i key.pem admin@IP 2>&1 | grep -E "hostname|serial|vm-license|device-certificate"
```

---

## Common Failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| hostname: PA-VM | Bootstrap not read | Check IAM has s3:ListBucket |
| serial: unknown | No authcode applied | Check license/authcodes file exists |
| vm-license: none | Authcode not valid or not found | Verify authcode in license/authcodes |
| device-certificate-status: None | Missing panorama-server=cloud | Add panorama-server=cloud to init-cfg.txt |
| device-certificate-status: None | Wrong PIN key names | Use vm-series-auto-registration-pin-id/value |

---

## Cleanup Checklist

After testing, terminate:
- [ ] EC2 instance
- [ ] Delete test IAM role and instance profile
- [ ] Delete test key pair
- [ ] Delete test security group
- [ ] Delete test S3 bootstrap files
