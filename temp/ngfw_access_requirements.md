# NGFW Access Requirements & Architecture Analysis

**Date:** 2026-02-16

---

## Codebase Architecture Facts

### NGFW Lifecycle & Relationships

1. **NGFW is independent from ranges:**
   ```python
   # From engine/models.py Range class
   ngfw_instance = models.ForeignKey(
       "Instance",
       on_delete=models.SET_NULL,
       related_name="attached_ranges",
       null=True,
       blank=True,
       help_text="NGFW Instance this range is attached to (for egress filtering)",
   )
   ```
   - Range → NGFW FK is **nullable** (ranges can exist without NGFWs)
   - Related name "attached_ranges" means **one NGFW can serve multiple ranges**
   - NGFW is an `Instance` with `role=NGFW` and `os_type=panos`

2. **NGFW has its own Request:**
   - NGFWs are provisioned independently via their own Request
   - Users can provision NGFW once, reuse across multiple ranges
   - NGFW lifecycle independent of range lifecycle

3. **NGFW States:**
   ```
   provisioning → awaiting_association → ready → (reusable)
   ```

### Network Topology

1. **VPC Architecture:**
   ```python
   # Range VPC uses 10.1.0.0/16 with /28 subnets (16 IPs each)
   # Capacity: 253 third octets (2-254) x 16 /28 blocks = 4048 subnets
   ```

2. **All instances use private IPs:**
   ```python
   # From services.py connect_terminal
   host = instance.get("private_ip")  # e.g., 10.1.5.10
   ```

3. **No direct internet access to instances**

### Existing Access Pattern: Guacamole Proxy

**How users access ranges currently:**

```
User Browser → Guacamole Server → Private Instance (10.1.x.x)
               (public endpoint)     (SSH/RDP via private IP)
```

**From guacamole.py:**
- Guacamole supports SSH, RDP, VNC protocols
- Uses JSON authentication with HMAC-SHA256 signing
- Creates signed URLs that expire in 5 minutes
- Server-to-server API call to Guacamole, returns browser URL

**Settings:**
```python
GUACAMOLE_BASE_URL = "/guacamole"  # Public browser URL
GUACAMOLE_API_BASE_URL = ...       # Internal API URL
GUACAMOLE_JSON_AUTH_SECRET = ...   # 128-bit signing key
```

### NGFW Specific Details

**NGFW Instance structure:**
```python
role = "ngfw"
os_type = "panos"
state = {
    "management_ip": "10.1.x.x",     # Private management IP
    "ssh_key_secret_arn": "arn:...",  # SSH key in Secrets Manager
    ...
}
```

**NGFW Access Requirements (from user description):**
- Users need CLI access (SSH to PAN-OS)
- Users need GUI access (HTTPS web interface)
- Access needed independent of ranges (NGFW reusable)
- Access needed for tuning rules, debugging, trying features
- Association with XDR is irrelevant to management access

---

## PAN-OS Management Capabilities

**From general firewall knowledge:**
- PAN-OS has HTTPS web GUI on port 443 (management interface)
- PAN-OS has SSH CLI on port 22 (admin user)
- Management interface is separate from dataplane
- Web GUI requires modern browser, HTTPS only

---

## Access Requirements

### CLI Access (SSH)

**Use Case:** Users need PAN-OS CLI for:
- Advanced configuration commands
- Debugging (show commands, logs)
- Running operational commands

**Requirements:**
- SSH to management IP (port 22)
- Admin user authentication
- SSH key from Secrets Manager

**Implementation:**
```
User Browser → Guacamole SSH → NGFW mgmt IP (10.1.x.x:22)
```

**Guacamole supports SSH:**
- Already has `create_guacamole_rdp_url()` for RDP
- Need `create_guacamole_ssh_url()` for SSH (similar pattern)
- SSH connection params: hostname, port, username, private_key

### GUI Access (HTTPS)

**Use Case:** Users need PAN-OS web interface for:
- Visual rule configuration
- Policy objects management
- Dashboard viewing
- Most users prefer GUI over CLI

**Technical Challenge:**
- PAN-OS web GUI is HTTPS on port 443
- Guacamole doesn't have native HTTPS proxy protocol
- Guacamole protocols: SSH, RDP, VNC, Telnet

**Possible Solutions:**

#### Option 1: VNC to Browser (Kali-mediated) - Branch A approach
```
User → Guacamole RDP → Kali Desktop → Firefox → NGFW Web UI
```
**Pros:**
- Uses existing Guacamole RDP capability
- Browser runs in Kali, handles HTTPS natively
**Cons:**
- Requires active range with Kali instance
- Extra hop (user RDPs, then opens browser manually)
- Violates NGFW independence from ranges

#### Option 2: Direct Guacamole to Web Interface
Guacamole doesn't support proxying HTTPS web interfaces.
Not viable without custom Guacamole extension.

#### Option 3: SSH Tunneling
```
User → Guacamole SSH → NGFW → Port forward 443 → ???
```
Still requires browser on client side, complex setup.

#### Option 4: VNC Server on NGFW (not viable)
PAN-OS doesn't support VNC server.

#### Option 5: Instructions Only
Provide management_ip and credentials, let users use:
- Their own browser + VPN
- AWS Session Manager port forwarding
- Direct network access (if available)

**Most practical:** Option 5 with clear documentation

---

## Correct Architecture

### Direct NGFW Access (No Range Dependency)

**For CLI:**
```python
def connect_ngfw_terminal(user, ngfw_uuid):
    # 1. Look up NGFW Instance by UUID
    ngfw = Instance.objects.get(uuid=ngfw_uuid, role=Instance.Role.NGFW)

    # 2. Validate user ownership via Request
    if ngfw.request.user_id != user.id:
        raise PermissionError()

    # 3. Get management IP and SSH key
    mgmt_ip = ngfw.state["management_ip"]
    ssh_key = get_ssh_key(ngfw.state["ssh_key_secret_arn"])

    # 4. Return SSHConnection for Guacamole
    return SSHConnection(
        host=mgmt_ip,
        username="admin",
        private_key=ssh_key,
    )
```

**For GUI:**
```python
def get_ngfw_management_info(user, ngfw_uuid):
    # 1. Look up NGFW, validate ownership
    ngfw = Instance.objects.get(uuid=ngfw_uuid, role=Instance.Role.NGFW)
    if ngfw.request.user_id != user.id:
        raise PermissionError()

    # 2. Return connection details
    return {
        "management_ip": ngfw.state["management_ip"],
        "web_url": f"https://{ngfw.state['management_ip']}",
        "username": "admin",
        "ssh_key_arn": ngfw.state["ssh_key_secret_arn"],
        "note": "Access via VPN or direct network connection"
    }
```

### Access Patterns

**CLI Access:**
- Direct via Guacamole SSH proxy
- No range dependency
- Works anytime NGFW is provisioned

**GUI Access:**
- Provide management_ip and instructions
- Users access via:
  - VPN to VPC (if configured)
  - AWS Session Manager port forwarding
  - Kali desktop from active range (optional convenience)

---

## Issues with Branch A

**Branch A forces Kali dependency:**
```python
# From get_ngfw_gui_info()
range_obj = Range.get_active_for_user(user)
if not range_obj:
    raise ValueError("No active range found. Launch a range to access NGFW GUI")
```

**Architectural problems:**
1. **Violates independence:** NGFW is reusable, shouldn't require range
2. **Forces cost:** User must keep Kali running to manage NGFW
3. **Poor UX:** Must spin up/down ranges just to tune firewall rules
4. **Doesn't match lifecycle:** NGFW persists across multiple range lifecycles

**When Branch A makes sense:**
- If NGFW was tightly coupled to range (it's not)
- If Kali was the only way to access private IPs (Guacamole SSH works)
- If web GUI was critical vs. nice-to-have (CLI is primary)

---

## Issues with Branch B

**Branch B has right architecture but:**
1. ❌ No tests
2. ❌ Removes pause/resume safety (unexplained)
3. ⚠️ Assumes web portal is directly accessible (may not be)

**Pause/resume regression:**
```python
# Branch B removes:
- select_for_update() locks
- transaction.atomic() wrapper
- ClientError exception handling
- Status rollback on failure
```
These were added specifically to prevent race conditions.
Removing them without justification is a regression.

---

## Recommendations

### Phase 1: CLI Access (Essential)

**Implement:**
1. `connect_ngfw_terminal(user, ngfw_uuid)` - SSH connection
2. `api_ngfw_ssh_url(request, ngfw_uuid)` - Generate Guacamole SSH URL
3. Add "CLI Access" button to NGFW detail page
4. Tests for ownership, status validation, SSH key retrieval

**No range dependency, works immediately.**

### Phase 2: GUI Access (Nice-to-have)

**Approach:**
1. Display management_ip on NGFW detail page
2. Provide instructions for access methods:
   - VPN to VPC (requires infrastructure setup)
   - SSH tunnel via Guacamole terminal
   - Kali desktop (if user has active range)

3. Document access patterns in help docs

**Don't force Kali dependency.**

### Phase 3: Enhanced GUI (Future)

If direct web access is critical:
1. Set up VPN infrastructure
2. Provide bastion host
3. Or: Add VNC-to-browser proxy (complex)

---

## Correct Implementation Spec

### Services Layer

```python
def connect_ngfw_terminal(user: User, ngfw_uuid: str) -> SSHConnection:
    """SSH connection to NGFW management interface.

    No range dependency - NGFW is independent resource.
    """
    ngfw = Instance.objects.get(uuid=ngfw_uuid, role=Instance.Role.NGFW)

    # Validate ownership via Request
    if not ngfw.request or ngfw.request.user_id != user.id:
        raise PermissionError(f"User does not own NGFW {ngfw_uuid}")

    # Validate status (ready or awaiting_association both allow management)
    if ngfw.status not in ["ready", "awaiting_association"]:
        raise ValueError(f"NGFW not accessible (status: {ngfw.status})")

    mgmt_ip = ngfw.state.get("management_ip")
    if not mgmt_ip:
        raise ValueError("NGFW has no management IP")

    ssh_key_arn = ngfw.state.get("ssh_key_secret_arn")
    if not ssh_key_arn:
        raise ValueError("NGFW has no SSH key")

    ssh_key = get_ssh_key(ssh_key_arn)

    return SSHConnection(
        host=mgmt_ip,
        username="admin",  # PAN-OS default admin user
        private_key=ssh_key,
        session_id=None,   # PAN-OS doesn't support tmux
    )
```

### Views Layer

```python
@login_required
@require_POST
def api_ngfw_ssh_url(request, ngfw_uuid):
    """Generate Guacamole SSH URL for NGFW CLI access."""
    try:
        conn = connect_ngfw_terminal(request.user, ngfw_uuid)
    except (ValueError, PermissionError) as e:
        return JsonResponse({"error": str(e)}, status=400)

    # Generate Guacamole SSH URL (need to implement helper)
    url = create_guacamole_ssh_url(
        base_url=settings.GUACAMOLE_BASE_URL,
        secret_key=settings.GUACAMOLE_JSON_AUTH_SECRET,
        username=request.user.email,
        connection_name=f"ngfw-cli-{ngfw_uuid[:8]}",
        hostname=conn.host,
        port=22,
        ssh_username="admin",
        ssh_private_key=conn.private_key,
        api_base_url=settings.GUACAMOLE_API_BASE_URL,
    )

    return JsonResponse({"url": url})
```

### Template Changes

```html
<!-- ngfw/detail.html -->
{% if ngfw.status in 'ready,awaiting_association' %}
<div class="card">
    <h2>Management Access</h2>

    <!-- CLI Access -->
    <div class="access-option">
        <h3>CLI Access</h3>
        <p>Open PAN-OS command line interface</p>
        <button onclick="openNGFWCLI('{{ ngfw.instance_id }}')">
            Open CLI
        </button>
    </div>

    <!-- GUI Access Info -->
    <div class="access-option">
        <h3>Web Interface</h3>
        <p>Management IP: <code>{{ ngfw.management_ip }}</code></p>
        <p>Web URL: <code>https://{{ ngfw.management_ip }}</code></p>
        <p>Access the web interface via:</p>
        <ul>
            <li>VPN to VPC (if configured)</li>
            <li>SSH tunnel: <code>ssh -L 8443:{{ ngfw.management_ip }}:443 ...</code></li>
            <li>Kali desktop (if you have an active range)</li>
        </ul>
    </div>
</div>
{% endif %}
```

---

## Conclusion

**Neither branch is correct as-is:**

- **Branch A:** Wrong architecture (forces Kali dependency)
- **Branch B:** Right architecture but critical flaws (no tests, pause/resume regression)

**Correct approach:**
1. Implement CLI access via Guacamole SSH (like Branch B's architecture)
2. Display GUI access info without forcing Kali (just provide instructions)
3. Do NOT remove pause/resume safety features
4. Write comprehensive tests
5. Follow TDD principles

**Start fresh with clear requirements and proper architecture.**
