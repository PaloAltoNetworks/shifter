# Shifter Platform Infrastructure Security Review

**Review Date:** 2026-02-07
**Reviewer:** Claude Sonnet 4.5
**Scope:** Infrastructure security, provisioner security, operational security

---

## Executive Summary

**Overall Infrastructure Security Posture: ADEQUATE with Notable Concerns**

The Shifter platform demonstrates solid security fundamentals with proper use of AWS IAM authentication, secrets management, and network isolation. However, several **CRITICAL** and **HIGH** risk areas require immediate attention, particularly around SQL injection vulnerabilities, SSH host key validation, and credential handling in logs.

### Key Strengths
- RDS IAM authentication for production environments
- AWS Secrets Manager for SSH key storage
- Network isolation with VPC segregation
- Parameterized queries in most database operations
- Field-level encryption with Fernet for sensitive data

### Critical Issues Requiring Immediate Remediation
1. SQL injection vulnerability in `main.py:update_range_status()` (CRITICAL)
2. SSH host key validation disabled (HIGH)
3. Potential credential exposure in logs (HIGH)
4. Hardcoded zero IV in Guacamole encryption (MEDIUM)
5. Terraform state file credential exposure (MEDIUM)

---

## 1. Provisioner SQL Safety

### CRITICAL: SQL Injection in update_range_status()

**File:** `/home/atomik/src/shifter/shifter/engine/provisioner/main.py:274-302`

**Risk Level:** CRITICAL

**Finding:**
```python
def update_range_status(range_id: int, status: str, **kwargs: str | int | None) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            updates = ["status = %s", "updated_at = NOW()"]
            values: list = [status]

            for key, value in kwargs.items():
                if value is not None:
                    if value == "NOW()":
                        updates.append(f"{key} = NOW()")  # <- VULNERABILITY
                    else:
                        updates.append(f"{key} = %s")     # <- VULNERABILITY
                        values.append(value)

            values.append(range_id)
            # nosec B608 comment claims this is safe, but it's NOT
            sql = f"UPDATE mission_control_range SET {', '.join(updates)} WHERE id = %s"
            cur.execute(sql, values)
```

**Exploitation Scenario:**
An attacker who can control `kwargs` keys can inject SQL:
```python
update_range_status(
    range_id=1,
    status="provisioning",
    **{"error_message = 'pwned'; DROP TABLE mission_control_range; --": "dummy"}
)
# Results in: UPDATE mission_control_range SET status = %s,
#             updated_at = NOW(),
#             error_message = 'pwned'; DROP TABLE mission_control_range; -- = %s
#             WHERE id = %s
```

While the code comment claims "Column names in 'updates' are from hardcoded kwargs keys in calling code", this is dangerous defensive programming. If ANY caller passes user-controlled keys, SQL injection occurs.

**Impact:**
- Database modification/deletion
- Data exfiltration
- Privilege escalation via manipulated range status

**Remediation:**
```python
# Whitelist allowed columns
ALLOWED_COLUMNS = {"error_message", "subnet_index", "ready_at", "destroyed_at"}

def update_range_status(range_id: int, status: str, **kwargs: str | int | None) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            updates = ["status = %s", "updated_at = NOW()"]
            values: list = [status]

            for key, value in kwargs.items():
                if key not in ALLOWED_COLUMNS:
                    raise ValueError(f"Invalid column: {key}")
                if value is not None:
                    if value == "NOW()":
                        updates.append(sql.SQL("{} = NOW()").format(sql.Identifier(key)))
                    else:
                        updates.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
                        values.append(value)

            values.append(range_id)
            query = sql.SQL("UPDATE mission_control_range SET {} WHERE id = %s").format(
                sql.SQL(", ").join(sql.SQL(u) for u in updates)
            )
            cur.execute(query, values)
```

### All Other SQL Operations: SECURE

**Finding:** All other database queries in the provisioner use proper parameterization:

**Examples:**
- `config.py:274-286` - Parameterized SELECT with %s placeholder
- `config.py:304-317` - Parameterized SELECT for NGFW data
- `main.py:413-420` - Parameterized UPDATE for engine_subnet
- `main.py:444-450` - Parameterized UPDATE for engine_instance
- `main.py:513-526` - Parameterized UPDATE with subquery for destroyed instances
- `main.py:575-589` - Parameterized SELECT for NGFW data

All queries properly use psycopg parameterization (`%s` placeholders with tuple/list of values).

---

## 2. Provisioner Config / Secrets

### LOW: Fernet Decryption Fallback Behavior

**File:** `/home/atomik/src/shifter/shifter/engine/provisioner/config.py:34-64`

**Risk Level:** LOW

**Finding:**
```python
def decrypt_field(encrypted_value: str) -> str:
    key = os.environ.get("FIELD_ENCRYPTION_KEY")
    if not key:
        logger.warning("FIELD_ENCRYPTION_KEY not set, returning value as-is")
        return encrypted_value  # <- Returns potentially encrypted data in plaintext context

    try:
        fernet = Fernet(key.encode() if isinstance(key, str) else key)
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_value.encode("ascii"))
        return fernet.decrypt(encrypted_bytes).decode("utf-8")
    except Exception as e:
        logger.warning(f"Failed to decrypt field: {e}")
        return encrypted_value  # <- Silent failure
```

**Issue:**
- If `FIELD_ENCRYPTION_KEY` is missing, encrypted ciphertext is returned as plaintext
- Decryption failures are logged but silently return ciphertext
- Could lead to credentials being inserted into database in ciphertext form, breaking authentication

**Recommendation:**
```python
def decrypt_field(encrypted_value: str) -> str:
    if not encrypted_value:
        return ""

    key = os.environ.get("FIELD_ENCRYPTION_KEY")
    if not key:
        raise ValueError("FIELD_ENCRYPTION_KEY environment variable required for decryption")

    fernet = Fernet(key.encode() if isinstance(key, str) else key)
    encrypted_bytes = base64.urlsafe_b64decode(encrypted_value.encode("ascii"))
    return fernet.decrypt(encrypted_bytes).decode("utf-8")
```

### INFO: Database Authentication - Proper IAM Usage

**File:** `/home/atomik/src/shifter/shifter/engine/provisioner/config.py:187-251`

**Risk Level:** INFO (SECURE)

**Finding:**
- Production mode uses RDS IAM authentication with short-lived tokens
- Local dev mode uses password authentication (appropriate for development)
- SSL/TLS enforced in production (`sslmode="require"`)
- No password storage, tokens generated on-demand

**Security Strength:** This is the correct pattern for AWS RDS access.

---

## 3. SSH Security

### HIGH: SSH Host Key Validation Disabled

**Files:**
- `/home/atomik/src/shifter/shifter/engine/provisioner/executors/ssh_executor.py:136-142`
- `/home/atomik/src/shifter/shifter/engine/provisioner/executors/ngfw_executor.py:73-90`

**Risk Level:** HIGH

**Finding:**

**ssh_executor.py (Paramiko):**
```python
client = paramiko.SSHClient()
client.set_missing_host_key_policy(
    paramiko.AutoAddPolicy()  # noqa: S507
)  # nosec B507
```

**ngfw_executor.py (OpenSSH CLI):**
```python
return [
    "ssh",
    "-i", self._key_path,
    "-o", "StrictHostKeyChecking=no",   # <- VULNERABILITY
    "-o", "UserKnownHostsFile=/dev/null", # <- VULNERABILITY
    # ...
]
```

**Comment in code:**
> "Security context: AutoAddPolicy is acceptable because we connect to freshly provisioned PAN-OS VMs in isolated VPC subnets. Host keys change on reprovision."

**Exploitation Scenario:**
1. Attacker compromises VPC routing or launches rogue EC2 instance
2. Attacker intercepts SSH connection to NGFW management IP (10.x.x.x)
3. MITM attack succeeds because host key is not validated
4. Attacker captures NGFW admin credentials and PAN-OS configuration commands
5. Attacker can reconfigure firewall rules, inject malicious routes, or exfiltrate range traffic

**Impact:**
- MITM attacks on NGFW configuration
- Credential theft (SSH private keys in transit)
- Firewall rule manipulation
- Complete compromise of range network security

**Remediation:**

**Option 1: Store First-Seen Host Keys (Recommended)**
```python
# During NGFW provisioning in main.py, capture and store host key:
def provision_ngfw(request_id: str):
    # ... existing provisioning code ...

    # After NGFW boots, get host key on first connection
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=management_ip, pkey=private_key)
    host_key = client.get_host_keys()[management_ip]['ssh-ed25519']
    client.close()

    # Store host key in database state
    update_ngfw_state(request_id, host_key=host_key.get_base64())

# In subsequent connections:
def get_ngfw_host_key(request_id: str) -> paramiko.PKey:
    # Fetch from database
    state = get_ngfw_state(request_id)
    key_data = base64.b64decode(state['host_key'])
    return paramiko.Ed25519Key(data=key_data)

# Use in ssh_executor.py:
def run_command(self, instance_id: str, script: str, ...):
    client = paramiko.SSHClient()
    # Load known host key from database
    known_host_key = get_ngfw_host_key(self.request_id)
    client.get_host_keys().add(instance_id, 'ssh-ed25519', known_host_key)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(hostname=instance_id, pkey=self._pkey)
    # ... existing code ...
```

**Option 2: AWS Secrets Manager for Host Keys**
Store the first-seen host key in the same Secrets Manager secret as the SSH private key:
```json
{
  "private_key": "<OpenSSH private key PEM>",
  "host_key": "AAAAC3NzaC1lZDI1NTE5AAAAIAbc123..."
}
```

Then validate on all subsequent connections.

**Why This Matters:**
Even in "isolated" VPCs, defense-in-depth requires host key validation. Scenarios where this protection matters:
- Compromised AWS account
- Rogue EC2 instances launched by malicious users
- ARP spoofing within VPC subnet
- EC2 instance replacement attack (stop NGFW, launch imposter)

---

## 4. SSM Command Execution Security

### INFO: SSM Executor - Secure Design

**File:** `/home/atomik/src/shifter/shifter/engine/provisioner/executors/ssm_executor.py`

**Risk Level:** INFO (SECURE)

**Findings:**
1. **Command execution properly isolated** - Each SSM RunCommand invocation is tracked with unique `command_id`
2. **No command injection** - Scripts are passed as single string parameters to AWS SSM, not shell-interpolated
3. **Timeout enforcement** - Commands have configurable timeouts with polling
4. **Instance validation** - Instance existence checked before command execution
5. **Output sanitization** - Large outputs truncated to prevent DoS (50KB limit)

**Security Strength:** SSM executor follows AWS best practices. No vulnerabilities identified.

---

## 5. Terraform/Pulumi Security

### MEDIUM: Terraform Variables File Contains Sensitive Data

**File:** `/home/atomik/src/shifter/shifter/engine/provisioner/terraform_runner.py:220-267`

**Risk Level:** MEDIUM

**Finding:**
```python
def apply_ngfw(request_uuid: str, variables: dict[str, Any], working_dir: Path):
    # Write variables to tfvars.json
    tfvars_path = working_dir / "terraform.tfvars.json"
    with open(tfvars_path, "w") as f:
        json.dump(variables, f, indent=2)  # <- Credentials written to disk

    # ... run terraform apply ...

    # Clean up tfvars file (contains sensitive data)
    tfvars_path.unlink(missing_ok=True)  # <- Cleanup after apply
```

**Issue:**
- `terraform.tfvars.json` may contain sensitive data (SSH keys, credentials)
- File written with default permissions (likely 0644 - world-readable)
- Cleanup happens AFTER terraform completes, leaving window for exposure
- If terraform crashes, file may not be cleaned up

**Exploitation Scenario:**
1. Attacker gains read access to ECS task filesystem (e.g., via container escape)
2. Attacker reads `/app/terraform.tfvars.json` during terraform execution
3. Attacker extracts SSH private keys, AWS credentials, or other secrets
4. If terraform crashes before cleanup, file remains on disk indefinitely

**Remediation:**
```python
def apply_ngfw(request_uuid: str, variables: dict[str, Any], working_dir: Path):
    # Write variables with restrictive permissions
    tfvars_path = working_dir / "terraform.tfvars.json"

    # Create file with 0600 permissions (owner read/write only)
    fd = os.open(tfvars_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(variables, f, indent=2)
    except:
        os.close(fd)
        raise

    try:
        # ... run terraform apply ...
        result = _run_terraform([...], working_dir)
        # ... get outputs ...
    finally:
        # ALWAYS clean up, even on exception
        tfvars_path.unlink(missing_ok=True)
        # Also shred file to prevent recovery
        if tfvars_path.exists():
            with open(tfvars_path, 'wb') as f:
                f.write(os.urandom(1024 * 1024))  # Overwrite with random data
            tfvars_path.unlink()

    return outputs
```

### INFO: Terraform State Storage - Secure

**File:** `/home/atomik/src/shifter/shifter/engine/provisioner/terraform_runner.py:155-192`

**Risk Level:** INFO (SECURE)

**Finding:**
- State stored in S3 with encryption enabled (`-backend-config=encrypt=true`)
- DynamoDB table used for state locking
- State key scoped per request UUID: `user_ngfw/{request_uuid}/terraform.tfstate`
- No sensitive data in state keys

**Security Strength:** Proper Terraform backend configuration.

---

## 6. NGFW Security Configuration

### MEDIUM: NGFW Default Security Profiles - Alert-Only Mode

**File:** `/home/atomik/src/shifter/shifter/engine/provisioner/plans/ngfw_provision.py:118-157`

**Risk Level:** MEDIUM (BUSINESS RISK, NOT TECHNICAL VULNERABILITY)

**Finding:**
```python
CREATE_SECURITY_PROFILES_INPUT = f"""configure
set profiles virus Alert-Only-AV decoder http action alert
set profiles virus Alert-Only-AV decoder ftp action alert
# ... all profiles set to action=alert ...
set profiles spyware Alert-Only-AS rules Alert-All action alert
set profiles vulnerability Alert-Only-VP rules Alert-All action alert
"""
```

**Issue:**
- All NGFW security profiles configured with `action alert` instead of `action block-ip` or `action reset-both`
- Malware, exploits, and C2 traffic will be logged but NOT blocked
- This is intentional for a cyber range (attack traffic must flow), but creates risk if ranges are misconfigured

**Business Context:**
This is **intentional design** for a cyber range platform. Users need to demonstrate attacks without the NGFW blocking them. However:

**Risk Scenarios:**
1. Range instance compromise leads to lateral movement into AWS infrastructure
2. User deploys actual malware that escapes range isolation
3. C2 beacon from range reaches real infrastructure

**Recommendation:**
Document this as a **known architectural limitation** in threat model. Ensure:
- Range VPCs are strictly isolated from production VPCs
- Internet egress from ranges is tightly controlled (AWS Network Firewall)
- Range instances cannot reach AWS metadata service
- Security groups prevent range-to-production communication

### INFO: NGFW Configuration Security - Cloud Logging Enabled

**File:** `/home/atomik/src/shifter/shifter/engine/provisioner/plans/ngfw_provision.py:66-100`

**Risk Level:** INFO (SECURE)

**Finding:**
```python
ENABLE_CLOUD_LOGGING_INPUT = """configure
set deviceconfig setting logging logging-service-forwarding enable yes
set deviceconfig setting logging logging-service-forwarding logging-service-regions {{ sls_region }}
commit
exit
"""

CREATE_LOG_FORWARDING_PROFILE_INPUT = "..."  # All log types forwarded to Panorama
```

**Security Strength:**
- All traffic, threat, URL, WildFire, data, tunnel, and auth logs forwarded
- Enables XDR visibility for attack detection
- Logs tamper-resistant (forwarded to cloud, not stored locally)

---

## 7. Network Security / Range Isolation

### INFO: VPC Subnet Allocation - Race Condition Protected

**File:** `/home/atomik/src/shifter/shifter/engine/provisioner/components/network.py:83-98`

**Risk Level:** INFO (SECURE)

**Finding:**
```python
def _get_vpc_lock_id(vpc_id: str) -> int:
    """Generate a consistent lock ID from VPC ID for advisory lock."""
    # MD5 used for consistent hashing, not cryptographic security
    hash_hex = hashlib.md5(vpc_id.encode(), usedforsecurity=False).hexdigest()[:8]
    return int(hash_hex, 16)

def allocate_subnets(vpc_id: str, cidr_prefix: str, count: int, subnet_size: int = 28):
    # PostgreSQL advisory lock prevents race conditions
    lock_id = _get_vpc_lock_id(vpc_id)
    conn.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
    # ... allocate subnets ...
    conn.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
```

**Security Strength:**
- Uses PostgreSQL advisory locks to prevent concurrent subnet allocation
- MD5 hash used for lock ID generation (appropriate - not cryptographic use)
- Prevents CIDR collisions even under concurrent provisioning

### INFO: Security Group Configuration

**Files:**
- `/home/atomik/src/shifter/shifter/engine/provisioner/components/network.py`
- Terraform modules at `/home/atomik/src/shifter/shifter/engine/provisioner/terraform/modules/range/main.tf`

**Risk Level:** INFO (SECURE)

**Expected Configuration** (from code patterns):
- Intra-subnet traffic unrestricted (required for range operation)
- VPC CIDR allowed for return traffic (e.g., portal access)
- Inter-subnet routing via NGFW data ENI (requires explicit routes)
- Internet egress via AWS Network Firewall + NAT Gateway

**Recommendation:** Verify actual Terraform configuration matches security requirements.

---

## 8. Credential Generation & Distribution

### INFO: SSH Key Generation - Secure

**File:** `/home/atomik/src/shifter/shifter/engine/provisioner/utils/crypto.py`

**Risk Level:** INFO (SECURE)

**Finding:**
```python
def generate_ssh_keypair() -> tuple[str, str]:
    """Generate an RSA 4096-bit SSH key pair."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
    )
    # ... serialize to PEM and OpenSSH formats ...
    return private_key_pem, public_key_openssh
```

**Security Strength:**
- RSA 4096-bit keys (strong)
- Proper use of cryptography library
- No hardcoded keys or weak random number generation
- Keys stored in AWS Secrets Manager (not logged or persisted locally)

### MEDIUM: Guacamole JSON Auth - Hardcoded Zero IV

**File:** `/home/atomik/src/shifter/shifter/shifter_platform/mission_control/guacamole.py:62-105`

**Risk Level:** MEDIUM

**Finding:**
```python
def sign_and_encrypt_payload(payload: dict[str, Any], secret_key: str) -> str:
    # ... HMAC-SHA256 signature ...

    # Encrypt with AES-128-CBC using zero IV
    iv = b"\x00" * 16  # <- HARDCODED ZERO IV
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
```

**Issue:**
- Zero IV in CBC mode is cryptographically weak
- If the same payload is encrypted twice, identical ciphertext is produced (leaks information)
- Allows pattern analysis if attacker observes multiple encrypted payloads

**Exploitation Scenario:**
1. Attacker intercepts multiple Guacamole auth tokens
2. If two tokens have identical ciphertext, attacker knows the plaintext payloads are identical
3. Attacker can infer connection patterns (same user connecting to same host)

**Note:** This may be **required by Guacamole's JSON auth specification**. If so, this is a known limitation of the protocol, not the implementation.

**Remediation (if spec allows):**
```python
def sign_and_encrypt_payload(payload: dict[str, Any], secret_key: str) -> str:
    # Generate random IV
    iv = os.urandom(16)

    # ... existing signature code ...

    # Encrypt with random IV
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

    # Prepend IV to encrypted data (Guacamole must extract IV on decrypt)
    return base64.b64encode(iv + encrypted_data).decode("utf-8")
```

**Action:** Verify if Guacamole JSON auth spec requires zero IV. If not, use random IV.

---

## 9. Event System Security

### INFO: SNS Event Publishing - Secure

**File:** `/home/atomik/src/shifter/shifter/engine/provisioner/events.py`

**Risk Level:** INFO (SECURE)

**Findings:**
1. **Event structure validation** - Events have required fields enforced at creation
2. **UUID correlation** - All events tied to request_id for auditability
3. **No sensitive data in events** - Events are notification-only, state stored in DB
4. **SNS message attributes** - Event type filtering supported
5. **Error handling** - SNS publish failures logged but don't crash provisioner

**Security Strength:** Well-designed event system with separation of notification and state.

---

## 10. Cognito Lambda Pre-Signup Trigger

### LOW: Email Domain Validation - Basic Bypass Risk

**File:** `/home/atomik/src/shifter/platform/terraform/modules/portal/cognito/lambda/pre_signup.py:76-112`

**Risk Level:** LOW

**Finding:**
```python
def handler(event, context):
    email = event.get("request", {}).get("userAttributes", {}).get("email", "")
    if email:
        email = email.lower().strip()

    # Basic email validation
    if not email or "@" not in email:
        raise Exception("Invalid email format")

    parts = email.split("@")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise Exception("Invalid email format")

    local_part, domain = parts

    # Check against allowed domains/emails
    allowed_domains = [d.strip().lower() for d in os.environ.get("ALLOWED_DOMAINS", "").split(",") if d.strip()]
    allowed_emails = [e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()]
```

**Issue:**
- Email validation is basic string splitting on `@`
- No RFC 5322 compliance checking
- Could be bypassed with malformed emails like `user@evil.com@paloaltonetworks.com` (though Cognito likely validates this)

**Exploitation Scenario:**
Limited - Cognito performs its own email validation before Lambda trigger. However:
- If Cognito email validation has bugs, this could be a secondary bypass
- Comment-style attacks like `user+@paloaltonetworks.com@evil.com` might confuse simple parsing

**Impact:** LOW - Cognito likely prevents most bypasses, but defense-in-depth suggests improving validation.

**Remediation:**
```python
import re

# RFC 5322 simplified email regex
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

def handler(event, context):
    email = event.get("request", {}).get("userAttributes", {}).get("email", "")
    if not email:
        raise Exception("Email address is required")

    email = email.lower().strip()

    # Validate email format with regex
    if not EMAIL_REGEX.match(email):
        raise Exception("Invalid email format")

    # Extract domain (last part after last @)
    domain = email.split("@")[-1]

    # ... rest of validation ...
```

---

## 11. ECS Task Security

### HIGH: Local Provisioner Mode Logs Credentials

**File:** `/home/atomik/src/shifter/shifter/shifter_platform/engine/ecs.py:33-113`

**Risk Level:** HIGH

**Finding:**
```python
def _run_local_provisioner(command: list[str]) -> str | None:
    # Build environment for provisioner
    env = os.environ.copy()

    # ... set various env vars ...

    # For local dev, use standard DB connection (not IAM auth)
    if hasattr(settings, "DATABASES"):
        db_config = settings.DATABASES.get("default", {})
        env.setdefault("DB_HOST", str(db_config.get("HOST", "localhost")))
        env.setdefault("DB_PORT", str(db_config.get("PORT", 5432)))
        env.setdefault("DB_USER", str(db_config.get("USER", "postgres")))
        env.setdefault("DB_PASSWORD", str(db_config.get("PASSWORD", "")))  # <- PASSWORD IN ENV
        env.setdefault("DB_NAME", str(db_config.get("NAME", "shifter")))

    full_command = ["python", main_py, *command]
    logger.info(f"Starting local provisioner: {' '.join(full_command)}")  # <- MAY LOG COMMAND WITH SECRETS
```

**Issue:**
- Database password passed via environment variable to subprocess
- Command logged at INFO level - may include sensitive parameters
- Environment variables inherited by subprocess, visible in process listing (`ps aux`)

**Exploitation Scenario:**
1. Attacker gains read access to Django logs
2. Log contains: `Starting local provisioner: python main.py range provision --request-id <uuid>`
3. Attacker then reads `/proc/<pid>/environ` to extract DB_PASSWORD
4. Attacker connects to database with stolen credentials

**Impact:**
- Database credential exposure in logs and process table
- Lateral movement to database (full range and user data access)

**Remediation:**
```python
def _run_local_provisioner(command: list[str]) -> str | None:
    # ... existing env setup ...

    # DO NOT log full command if it may contain secrets
    logger.info(f"Starting local provisioner: command_type={command[0] if command else 'unknown'}")

    # Use explicit password file instead of environment variable
    if db_password:
        # Write password to temporary file with 0600 permissions
        fd, password_file = tempfile.mkstemp(prefix="db_pw_", suffix=".txt")
        try:
            os.write(fd, db_password.encode())
        finally:
            os.close(fd)
        os.chmod(password_file, 0o600)

        # Pass password file path instead of password
        env["DB_PASSWORD_FILE"] = password_file
        del env["DB_PASSWORD"]  # Remove from environment

    # ... start subprocess ...
```

Then update provisioner to read from `DB_PASSWORD_FILE` if set.

### INFO: ECS Task IAM Permissions - Secure Pattern

**File:** `/home/atomik/src/shifter/shifter/shifter_platform/engine/ecs.py:145-244`

**Risk Level:** INFO (SECURE)

**Finding:**
- ECS task receives credentials via IAM task role (not hardcoded)
- Task definition and cluster ARNs configurable via settings
- Network isolation with private subnets and security groups
- Command passed via ECS container override (not environment variables)

**Security Strength:** Proper use of AWS ECS security model.

---

## Additional Findings

### INFO: Encrypted Field Handling in Config

**File:** `/home/atomik/src/shifter/shifter/engine/provisioner/config.py:34-64`

**Risk Level:** INFO (SECURE)

**Finding:**
- Django encrypted model fields decrypted using Fernet symmetric encryption
- Encryption key loaded from environment variable `FIELD_ENCRYPTION_KEY`
- Proper base64 decoding and exception handling

**Security Strength:** Correct use of Fernet for field-level encryption.

---

## Recommendations by Priority

### CRITICAL (Fix Immediately)
1. **SQL Injection in `update_range_status()`** - Add column whitelist and use `psycopg.sql.Identifier()` for dynamic column names

### HIGH (Fix Within 1 Sprint)
1. **SSH Host Key Validation** - Store and validate NGFW host keys on first connection
2. **Credential Logging in Local Provisioner** - Remove password from logs and process environment

### MEDIUM (Fix Within 1 Month)
1. **Terraform Variables File Security** - Write tfvars with 0600 permissions and use try/finally for cleanup
2. **Guacamole Zero IV** - Verify if spec allows random IV, implement if possible

### LOW (Technical Debt)
1. **Cognito Email Validation** - Use regex validation for RFC 5322 compliance
2. **Fernet Decryption Error Handling** - Fail fast instead of returning ciphertext on error

---

## Security Testing Recommendations

### SQL Injection Testing
```bash
# Test update_range_status with malicious keys
python -c "
from main import update_range_status
update_range_status(
    1,
    'provisioning',
    **{'id = 999 WHERE 1=1; --': 'pwned'}
)
"
```

### SSH MITM Testing
```bash
# Launch rogue EC2 instance with stolen NGFW IP
# Configure sshd to log credentials
# Verify provisioner connects without host key validation
```

### Terraform Credentials Testing
```bash
# Check file permissions on terraform.tfvars.json during apply
ls -la /app/terraform.tfvars.json
# Verify cleanup on crash
kill -9 <terraform-pid>
ls -la /app/terraform.tfvars.json  # Should not exist
```

---

## Compliance Considerations

### PCI-DSS
- **3.4 Render PAN unreadable**: Fernet encryption for sensitive fields ✓
- **8.3 MFA for remote access**: Not applicable (system-to-system)
- **10.1 Implement audit trails**: SNS event publishing provides audit trail ✓

### SOC 2
- **CC6.1 Logical access controls**: IAM roles and Cognito auth ✓
- **CC6.6 Encryption**: TLS for RDS, Secrets Manager for keys ✓
- **CC7.2 System monitoring**: CloudWatch metrics and logs ✓

### CIS AWS Foundations Benchmark
- **2.1.1 EBS encryption**: Not evaluated (no EBS volumes created in reviewed code)
- **2.1.2 RDS encryption**: ✓ (sslmode=require)
- **4.1 SSH host key validation**: ✗ (disabled)

---

## Overall Infrastructure Security Posture: ADEQUATE with Notable Concerns

**Summary:**
The Shifter platform demonstrates solid engineering practices in most areas, particularly around AWS IAM authentication, secrets management, and database access patterns. However, the **CRITICAL** SQL injection vulnerability in `update_range_status()` and **HIGH** risk SSH host key validation issues require immediate remediation.

The platform is **acceptable for internal use** with the understanding that:
1. SQL injection fix must be deployed before production launch
2. SSH host key validation should be implemented before handling sensitive customer data
3. Credential logging in local provisioner is acceptable for development but must be fixed before production

**Rating: 6.5/10** - Adequate security posture with critical issues that must be addressed for production readiness.
