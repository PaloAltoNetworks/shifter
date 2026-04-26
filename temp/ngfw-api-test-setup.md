# NGFW API Test Setup

Test environment for validating pan-os-python SDK before migrating production code.

## Resources Created

**Test NGFW Instance:**
- Instance ID: `i-006fcc555c3be0c98`
- Public IP: `3.139.100.204`
- Private IP: `172.31.36.8`
- AMI: `ami-065e27477b191614c` (PAN-OS 11.2.3)
- Type: `m5.xlarge`
- Region: `us-east-2`
- VPC: `vpc-0eb7ca67e9f22929a` (default VPC)
- Subnet: `subnet-0de28b8e6614ab6d9` (default public subnet, us-east-2c)

**Security Group:**
- ID: `sg-0d9bb551514423433`
- Name: `ngfw-api-test`
- Inbound: 443 (API), 22 (SSH) from 0.0.0.0/0

**S3 Bootstrap:**
- Bucket: `shifter-ngfw-test-bootstrap-397`
- Path: `bootstrap/test/`
- Files created:
  - `config/init-cfg.txt` (SCM auto-registration)
  - `license/authcodes` (D9232090)
  - `content/.keep`
  - `software/.keep`

## Bootstrap Configuration

The NGFW is configured with SCM auto-registration:
- **PIN ID:** `f3593d62-c955-4dbe-8b31-1b143ff4c214`
- **PIN Value:** `bac7e24559084fa68cfd4a386d904e26`
- **Folder:** `All Firewalls`
- **Authcode:** `D9232090`

This should auto-license the NGFW with Palo Alto's cloud services.

## Testing the API

### 1. Install pan-os-python

```bash
pip install pan-os-python
```

### 2. Run the test script

```bash
# Basic connectivity test
python temp/test-ngfw-api.py

# Test with configuration operations
python temp/test-ngfw-api.py --config
```

### 3. Expected Timeline

- **0-5 min:** Instance launching, no API response
- **5-15 min:** API responds, serial = "unknown", bootstrap in progress
- **15-25 min:** Serial appears, device certificate valid, fully ready

### 4. Manual API Test

```python
from panos import firewall

# Connect
fw = firewall.Firewall("3.139.100.204", api_username="admin", api_password="admin")

# Get system info
result = fw.op("show system info")
print(result)

# Parse serial
serial = result.find(".//serial").text
print(f"Serial: {serial}")
```

## What to Test

1. **API Availability Timing**
   - When does port 443 start responding?
   - Does it come up at the same time as SSH?

2. **System Info Polling**
   - Does the API method work for getting serial/certificate status?
   - Is XML parsing reliable?

3. **Configuration Operations**
   - Can we create AddressObject via API?
   - Can we create SecurityRule via API?
   - Does commit() work?

4. **Compare with SSH**
   - Is the API faster/more reliable than SSH?
   - Better error messages?

## Cleanup When Done

```bash
# Terminate instance
aws ec2 terminate-instances \
  --region us-east-2 \
  --profile panw-shifter-dev-workstation \
  --instance-ids i-006fcc555c3be0c98

# Delete security group (after instance terminates)
aws ec2 delete-security-group \
  --region us-east-2 \
  --profile panw-shifter-dev-workstation \
  --group-id sg-0d9bb551514423433

# Clean S3 bootstrap files
aws s3 rm s3://shifter-ngfw-test-bootstrap-397/bootstrap/test/ \
  --recursive \
  --region us-east-2 \
  --profile panw-shifter-dev-workstation
```

## Next Steps After Testing

If API works well:
1. Update issue #591 with test results
2. Implement API methods in `ssh_executor.py` (or new `api_executor.py`)
3. Update `main.py` to use API instead of SSH
4. Add proper error handling and timeouts
5. Test with real provisioning flow
6. Remove SSH code once validated
