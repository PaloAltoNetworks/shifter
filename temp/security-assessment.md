# Shifter Security Assessment

**Date:** 2026-02-07 | **Rating: ADEQUATE (6.5/10)** | **Trajectory: Solid foundations, specific high-risk gaps**

---

## Executive Summary

Shifter's security posture is split: the Django platform demonstrates strong security awareness (proper OIDC, consistent `@login_required`, HMAC upload tokens, field encryption, bleach HTML sanitization), while the provisioner has specific high-risk vulnerabilities (SQL injection via dynamic column names, disabled SSH host key validation, credential exposure in logs).

For a platform that provisions attack infrastructure and gives users access to live machines with admin credentials, the bar must be higher than "adequate." The critical SQL injection finding in `update_range_status()` and the disabled SSH host key validation on NGFW connections are the highest-priority items.

No authentication bypass, IDOR, or XSS vulnerabilities were found. The OIDC/Cognito integration is correctly implemented. All views are protected by `@login_required`. Ownership checks are delegated to the service layer and consistently enforced.

---

## Critical & High Findings

### CRITICAL: SQL Injection in Provisioner `update_range_status()`
**File:** `provisioner/main.py:274-302`

Dynamic column names are constructed via f-strings from `**kwargs` keys:
```python
for key, value in kwargs.items():
    updates.append(f"{key} = %s")     # Column name from caller kwargs
sql = f"UPDATE mission_control_range SET {', '.join(updates)} WHERE id = %s"
```

While callers currently pass hardcoded kwargs, there is no whitelist or validation of column names. Any future caller passing user-derived keys would enable SQL injection. The `# nosec B608` comment suppresses security scanners, creating false confidence.

**Fix:** Add an `ALLOWED_COLUMNS` whitelist and use `psycopg.sql.Identifier()` for column names.

### HIGH: SSH Host Key Validation Disabled
**Files:** `executors/ssh_executor.py:136-142`, `executors/ngfw_executor.py:73-90`

Both Paramiko (`AutoAddPolicy()`) and OpenSSH (`StrictHostKeyChecking=no`) connections to NGFWs skip host key validation. The code comment argues this is acceptable because "we connect to freshly provisioned VMs in isolated VPC subnets."

This is insufficient defense-in-depth. In a cyber range platform where attack infrastructure is being managed, MITM on NGFW management connections could allow firewall rule manipulation, credential theft, or traffic interception.

**Fix:** Store first-seen host key during NGFW provisioning, validate on all subsequent connections.

### HIGH: Local Provisioner Logs Database Credentials
**File:** `engine/ecs.py:33-113`

The local provisioner mode passes database password via environment variable and logs the full command at INFO level. The password is visible in process table (`ps aux`) and potentially in log output.

**Fix:** Use a temporary password file with 0600 permissions, redact sensitive values from logs.

---

## Medium Findings

### MEDIUM: Dev Auth Bypass Relies Only on DEBUG Flag
**File:** `config/dev_auth.py:22-23`

The development login endpoint is guarded solely by `settings.DEBUG`. While Django's URL routing also conditionally includes the route (defense in depth), a DEBUG=True misconfiguration in production would enable complete authentication bypass.

**Fix:** Add ENVIRONMENT check, IP whitelist (localhost only), and prominent logging.

### MEDIUM: Terraform Variables Written with Default Permissions
**File:** `provisioner/terraform_runner.py:220-267`

`terraform.tfvars.json` containing potentially sensitive data is written with default file permissions (likely 0644) and only cleaned up in the happy path. If Terraform crashes, the file persists.

**Fix:** Write with 0600 permissions, use try/finally for cleanup.

### MEDIUM: Guacamole Zero IV in AES-CBC
**File:** `mission_control/guacamole.py:62-105`

AES-128-CBC encryption uses a hardcoded zero IV. This may be required by the Guacamole JSON auth specification, but it enables ciphertext pattern analysis if an attacker observes multiple tokens.

**Fix:** Verify if Guacamole spec mandates zero IV. If not, use random IV.

### MEDIUM: CSRF Exemption on cancel_upload
**File:** `mission_control/views.py:347-361`

`@csrf_exempt` is used for `navigator.sendBeacon()` compatibility. While mitigated by `@login_required` and HMAC upload token verification, it violates CSRF protection principles. Impact is limited to canceling the user's own upload.

**Fix:** Consider alternative approaches (GET endpoint, CSRF token in JSON body).

### MEDIUM: No Rate Limiting
No rate limiting observed on authentication endpoints, upload initiation, API endpoints, or WebSocket connections. A valid user could exhaust resources through rapid API calls.

**Fix:** Implement `django-ratelimit` on key endpoints.

---

## Low & Informational Findings

| Finding | Risk | Location |
|---------|------|----------|
| Missing HSTS enforcement | Low | `config/settings.py` |
| No API key lifetime/rotation policy | Low | `risk_register/api/` |
| Fernet decryption returns ciphertext on failure | Low | `provisioner/config.py:34-64` |
| Basic email validation in Cognito Lambda | Low | `cognito/lambda/pre_signup.py` |
| No dependency vulnerability scanning | Info | Project-wide |
| NGFW security profiles in alert-only mode | Info (intentional) | `plans/ngfw_provision.py` |

---

## What's Done Well

### Authentication (Strong)
- OIDC/Cognito integration is correctly implemented via `mozilla-django-oidc`
- Custom backend properly stores Cognito `sub` in user profile
- Logout correctly clears both Django session and Cognito IdP session
- OIDC exempt URLs are minimal (only `/`, `/health`)
- Dev auth routes are conditionally included in URL routing

### Authorization (Strong)
- All views consistently use `@login_required` (verified across ~40 views)
- Risk Register uses `@staff_member_required` for admin-only access
- DRF permissions properly separate `IsAdminUser` from `IsAuthenticatedOrAPIKey`
- `IsOwnerOrAdmin` permission class provides proper ownership checks
- WebSocket consumers verify ownership via CMS service layer before joining channel groups

### Input Validation (Strong)
- JSON parsing with error handling on all POST endpoints
- `os.path.basename()` for filename sanitization
- Magic byte validation for file uploads (defense in depth)
- `bleach.clean()` for rendered markdown (XSS prevention)
- Path traversal prevention with `..` detection and excluded folder blocking
- S3 key sanitization (control chars, path separators, length limits)

### Credential Handling (Strong)
- Field-level Fernet encryption for sensitive data
- AWS Secrets Manager for SSH keys (not persisted locally)
- HMAC-SHA256 signed upload tokens with timing-safe comparison
- No secrets in log output (verified across reviewed files)
- RSA 4096-bit SSH key generation

### Data at Rest & Transit (Strong)
- RDS IAM authentication in production (no stored passwords)
- Terraform state encrypted in S3
- DynamoDB state locking
- SSL/TLS enforced for database connections (`sslmode=require`)
- SNS events contain notification only (no sensitive data)

---

## Attack Surface Summary

### Highest Risk Endpoints
1. **Provisioner DB operations** - SQL injection via `update_range_status()` kwargs
2. **NGFW SSH connections** - No host key validation, MITM possible
3. **Local provisioner mode** - Credentials in env vars and logs

### Defended Endpoints
1. **All views** - `@login_required` enforced
2. **S3 uploads** - Presigned URLs + HMAC tokens + file validation
3. **WebSocket connections** - Auth + ownership verification + origin validation
4. **Risk Register API** - API key + staff permission checks
5. **Documentation** - Path traversal prevention + HTML sanitization

---

## Remediation Priority

### Immediate (This Sprint)
1. **Fix SQL injection** in `update_range_status()` - Add column whitelist
2. **Add HSTS enforcement** - Configuration change, high impact
3. **Redact credentials from provisioner logs**

### Short-Term (1 Month)
4. **Implement SSH host key validation** for NGFW connections
5. **Implement rate limiting** on key endpoints
6. **Fix Terraform tfvars file permissions** and cleanup

### Medium-Term (1 Quarter)
7. **Strengthen dev auth bypass** with IP whitelist and environment checks
8. **Add automated dependency scanning** to CI/CD
9. **Implement API key lifetime policies**
10. **Commission penetration test** focusing on provisioner and NGFW management

---

## Contextual Note

Shifter is a **cyber range platform that provisions attack infrastructure**. This means:
- Users intentionally run malware and exploit tools
- NGFW profiles are alert-only (by design, to allow attacks to flow)
- Range isolation is the primary security boundary
- Compromise of range management (provisioner, NGFW config) is the highest-impact scenario

The security review findings should be prioritized with this context: anything that could allow a range user to escape isolation, manipulate another user's range, or compromise the management plane is critical.

---

## Raw Data
- Auth/access/data security details: `temp/raw-sec-auth-data.md`
- Infrastructure security details: `temp/raw-sec-infra.md`
