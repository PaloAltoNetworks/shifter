# Checklist: Implement SSH Host Key Validation for NGFW Connections

**Priority:** HIGH | **Effort:** Medium (3-5 days) | **Risk if deferred:** MITM on NGFW management plane

---

## Context

Two executors connect to NGFWs via SSH with host key validation disabled:

1. **NGFWExecutor** (`executors/ngfw_executor.py:73-90`) - subprocess-based SSH:
   ```
   StrictHostKeyChecking=no
   UserKnownHostsFile=/dev/null
   ```

2. **SSHExecutor** (`executors/ssh_executor.py:136-142`) - Paramiko-based:
   ```python
   client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # noqa: S507
   ```

Both have a second usage point:
- `ssh_executor.py:330` - AutoAddPolicy in a different method
- `plans/ngfw_deprovision.py:26,51` - StrictHostKeyChecking=no in inline shell scripts

**NGFW lifecycle:** Terraform creates EC2 instance -> SSH becomes available -> host key silently accepted -> provisioning proceeds. The host key is generated at EC2 launch and is never recorded.

**Why this matters:** Shifter is a cyber range platform managing attack infrastructure. A MITM on the NGFW management connection could allow firewall rule manipulation, credential theft, or traffic interception. The NGFW controls traffic flow for ALL ranges.

---

## Pre-Work

- [ ] Read `ngfw_terraform.py` to understand the full NGFW provisioning flow
- [ ] Identify the exact point where the NGFW first becomes SSH-reachable (after Terraform apply)
- [ ] Read `executors/ngfw_executor.py` fully - understand `_build_ssh_args()` and all SSH entry points
- [ ] Read `executors/ssh_executor.py` fully - understand both AutoAddPolicy locations
- [ ] Read `plans/ngfw_deprovision.py` - understand the inline SSH commands
- [ ] Determine where NGFW metadata is stored (Instance model state JSON field)
- [ ] Check if the NGFW EC2 instance has a stable private IP across stop/start cycles
- [ ] Check if PAN-OS regenerates SSH host keys on reboot (it shouldn't, but verify)

## Design Decision: TOFU vs Pre-Provisioned Keys

### Option A: Trust-On-First-Use (TOFU) - Recommended
- Capture the host key fingerprint on first SSH connection (during NGFW provisioning)
- Store the fingerprint alongside other NGFW metadata
- Validate the fingerprint on all subsequent connections

### Option B: Pre-Provisioned Host Keys
- Generate SSH host key pair before NGFW provisioning
- Inject host key into NGFW via cloud-init/user-data
- Store public key fingerprint in metadata
- More secure but more complex and may not work with PAN-OS

- [ ] Decide on approach (recommend Option A for practicality)

## Implementation: Host Key Capture

### Capture During NGFW Provisioning
- [ ] In `ngfw_terraform.py`, after the NGFW first becomes SSH-reachable:
    - Use `ssh-keyscan` to capture the host key:
      ```
      ssh-keyscan -p <port> -T 10 <management_ip>
      ```
    - Parse the output to extract the host key type and fingerprint
    - Store in a known format (e.g., `ssh-rsa AAAA...` or fingerprint hash)
- [ ] Add the captured host key to the NGFW instance state JSON:
    ```python
    state["ssh_host_key"] = "<key_type> <base64_key>"
    state["ssh_host_key_fingerprint"] = "<SHA256:...>"
    ```
- [ ] Write a helper function `capture_host_key(host, port)` in a shared location
- [ ] Log the captured fingerprint at INFO level for audit trail

### Store Host Key in Instance State
- [ ] Verify the Instance model's `state` JSONField can accommodate the host key
- [ ] Add the host key to the `update_instance_state()` call during NGFW provisioning
- [ ] Verify the host key persists across NGFW stop/start cycles (state JSON shouldn't change)

## Implementation: Host Key Validation

### NGFWExecutor (subprocess SSH)
- [ ] Modify `__init__()` to accept an optional `host_key` parameter
- [ ] When `host_key` is provided:
    - Write it to a temporary known_hosts file (alongside the temp key file)
    - Format: `[<host>]:<port> <key_type> <base64_key>`
- [ ] Modify `_build_ssh_args()`:
    - Replace `StrictHostKeyChecking=no` with `StrictHostKeyChecking=yes`
    - Replace `UserKnownHostsFile=/dev/null` with `UserKnownHostsFile=<temp_known_hosts>`
- [ ] When `host_key` is NOT provided (backward compatibility during migration):
    - Keep current behavior but log a WARNING
    - This allows existing NGFWs without stored keys to still work
- [ ] Clean up the temp known_hosts file in `close()`
- [ ] Update the test at `test_ngfw_executor.py:92` (`test_strict_host_key_checking_off`) to test BOTH behaviors

### SSHExecutor (Paramiko)
- [ ] Modify the class to accept an optional `host_key` parameter
- [ ] When `host_key` is provided:
    - Parse into a `paramiko.RSAKey` (or appropriate key type)
    - Use `client.get_host_keys().add(hostname, keytype, key)` instead of AutoAddPolicy
    - Set `client.set_missing_host_key_policy(paramiko.RejectPolicy())`
- [ ] When `host_key` is NOT provided:
    - Keep AutoAddPolicy but log a WARNING
- [ ] Apply to BOTH AutoAddPolicy locations (lines 141 and 330)
- [ ] Remove `# noqa: S507` and `# nosec B507` once RejectPolicy is the default

### Inline SSH in Plans
- [ ] Read `plans/ngfw_deprovision.py` lines 26 and 51
- [ ] Determine if these can use NGFWExecutor instead of inline SSH
- [ ] If not, modify the inline scripts to use a known_hosts file
- [ ] If the deprovision plans run against an NGFW about to be destroyed, document that host key validation is less critical here (the NGFW is being deleted)

## Implementation: Pass Host Key Through Call Chain

- [ ] Trace every code path that creates an NGFWExecutor or SSHExecutor for NGFW connections
- [ ] For each, determine how to pass the stored host key from DB/state to the executor
- [ ] Key call chains to trace:
    - `ngfw_terraform.py` provisioning flow (first use - capture, not validate)
    - `ngfw_terraform.py` deprovision flow (validate)
    - `main.py:configure_ngfw_subnets()` (validate)
    - `main.py:remove_ngfw_subnets()` (validate)
    - `range_ops.py` pause/resume NGFW operations (validate)
    - Any plan that uses SSHExecutor against an NGFW
- [ ] For each call chain, add the host key parameter

## Migration: Handle Existing NGFWs

- [ ] Existing NGFWs in the database won't have stored host keys
- [ ] Add a migration path:
    - On first connection to an NGFW without a stored key, capture and store it (TOFU)
    - Log at WARN level: "No stored host key for NGFW <id>, capturing via TOFU"
    - All subsequent connections validate against the stored key
- [ ] Consider a management command or script to backfill host keys for running NGFWs:
    ```
    For each active NGFW:
        ssh-keyscan the management IP
        Store the key in instance state
    ```

## Verification

- [ ] Run provisioner tests: `cd provisioner && python -m pytest`
- [ ] Write unit test: NGFWExecutor with valid host key - connection succeeds
- [ ] Write unit test: NGFWExecutor with wrong host key - connection rejected
- [ ] Write unit test: NGFWExecutor with no host key - falls back to TOFU with warning
- [ ] Write unit test: SSHExecutor with valid host key - connection succeeds
- [ ] Write unit test: SSHExecutor with wrong host key - connection rejected
- [ ] Test in dev environment:
    - Provision new NGFW, verify host key captured in instance state
    - Run a range provision against that NGFW, verify host key validated
    - Stop/start NGFW, verify host key still valid
    - Destroy NGFW, verify cleanup
- [ ] Verify no `StrictHostKeyChecking=no` remains in the codebase (except with documented justification)
- [ ] Verify no `AutoAddPolicy` remains without a fallback warning log
- [ ] Run `bandit -r provisioner/` and confirm S507 findings are resolved or properly documented
