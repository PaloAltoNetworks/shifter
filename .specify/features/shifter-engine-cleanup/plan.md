# Shifter Engine Cleanup - TDD Remediation Plan

## Overview

This plan remediates incomplete migrations and duplicate code paths discovered in the 371-shifter-engine refactoring. Following TDD methodology: write/update tests first, verify they fail, then refactor.

---

## Issue 1: Duplicate Hostname+SSH Setup Code (HIGH)

### Problem
The same hostname and SSH configuration logic exists in 3 separate plan files:
- `bootstrap.py` (Windows - PowerShell)
- `kali_setup.py` (Kali - Bash, hardcoded `/home/kali`)
- `linux_bootstrap.py` (Linux - Bash, parameterized `ssh_user`)

KaliSetupPlan duplicates LinuxBootstrapPlan but hardcodes `kali` user instead of parameterizing.

### Solution
Delete `KaliSetupPlan` and use `LinuxBootstrapPlan` with `ssh_user="kali"` instead.

### TDD Steps

#### Step 1: Write new test that KaliSetupPlan is DEPRECATED
**File:** `tests/test_kali_setup_plan.py`

```python
# Add deprecation test
def test_kali_setup_plan_is_deprecated():
    """KaliSetupPlan should be deprecated - use LinuxBootstrapPlan with ssh_user='kali'."""
    with pytest.warns(DeprecationWarning):
        from components.plans.kali_setup import KaliSetupPlan
```

#### Step 2: Write test that LinuxBootstrapPlan works for Kali
**File:** `tests/test_linux_bootstrap_plan.py`

```python
def test_get_context_works_for_kali_user(self):
    """LinuxBootstrapPlan should work with ssh_user='kali' for Kali instances."""
    plan = LinuxBootstrapPlan()
    instance = MockLinuxInstance(hostname="shifter-kali-1", public_key="ssh-key", ssh_user="kali")
    context = plan.get_context(instance)
    assert context["ssh_user"] == "kali"
    assert context["hostname"] == "shifter-kali-1"
```

#### Step 3: Write test that instance.py uses LinuxBootstrapPlan for Kali
**File:** `tests/test_instance_component.py`

```python
def test_attacker_uses_linux_bootstrap_plan_with_kali_user(self):
    """Attacker (Kali) instances should use LinuxBootstrapPlan with ssh_user='kali'."""
    # Mock the orchestrator and verify LinuxBootstrapPlan is used
    # with ssh_user='kali' context
```

#### Step 4: Verify tests fail (KaliSetupPlan exists, not deprecated)

#### Step 5: Refactor
1. Add deprecation warning to `kali_setup.py`
2. Update `instance.py` to use `LinuxBootstrapPlan` for attacker role with `ssh_user="kali"`
3. Eventually delete `kali_setup.py` entirely

---

## Issue 2: Double Hostname Setup (MEDIUM)

### Problem
Hostname is set in TWO places:
1. user_data templates at boot (victim_linux.sh.j2, victim_windows.ps1.j2)
2. SSM plans after boot (LinuxBootstrapPlan, BootstrapPlan)

This is wasteful but harmless for hostname. However, it's inconsistent and should be cleaned up.

### Solution
Remove hostname setup from user_data templates. Let SSM plans handle it exclusively.

**Exception:** Keep hostname in user_data for Kali (attacker) since we might want it visible quickly in cloud-init logs.

### TDD Steps

#### Step 1: Update template tests to NOT expect hostname setup
**File:** `tests/test_user_data.py`

```python
def test_victim_linux_template_no_hostname_setup(self, linux_template):
    """victim_linux.sh.j2 should NOT set hostname - SSM plans do that."""
    result = linux_template.render(
        hostname="shifter-victim-42-0",
        public_key="ssh-ed25519 AAAA...",
    )
    # Should NOT have hostnamectl
    assert "hostnamectl" not in result
    # Comment should explain SSM handles it
    assert "SSM" in result or "LinuxBootstrapPlan" in result

def test_victim_windows_template_no_hostname_setup(self, windows_template):
    """victim_windows.ps1.j2 should NOT set hostname - SSM plans do that."""
    result = windows_template.render(
        hostname="shifter-victim-42-0",
        public_key="ssh-ed25519 AAAA...",
    )
    # Should NOT have Rename-Computer
    assert "Rename-Computer" not in result
```

#### Step 2: Verify tests fail (templates currently DO set hostname)

#### Step 3: Refactor templates
Remove hostname setup from:
- `templates/victim_linux.sh.j2`
- `templates/victim_windows.ps1.j2`

Keep only SSH setup in user_data (needed for emergency access if SSM fails).

---

## Issue 3: Orphaned `_generate_secure_password()` (LOW)

### Problem
`instance.py:761-778` defines `_generate_secure_password()` but it's never called.

### Solution
Remove the orphaned method.

### TDD Steps

#### Step 1: Write test that method doesn't exist
**File:** `tests/test_instance_component.py`

```python
def test_no_orphaned_generate_secure_password_method(self):
    """_generate_secure_password should not exist - DC uses env password."""
    from components.instance import InstanceComponent
    assert not hasattr(InstanceComponent, '_generate_secure_password')
```

#### Step 2: Verify test fails (method currently exists)

#### Step 3: Delete the method from instance.py

---

## Issue 4: DC Setup Documentation Mismatch (LOW)

### Problem
`dc_setup.py:79-83` comment says "This plan runs AFTER BootstrapPlan completes" but DC instances actually skip BootstrapPlan entirely. They get hostname/SSH from user_data.

### Solution
Update comments to reflect reality, or refactor DC to use BootstrapPlan.

Given DC uses prebaked AMI with AD DS, it makes sense to keep user_data for initial setup. Update docs only.

### TDD Steps

#### Step 1: Write docstring validation test
**File:** `tests/test_dc_setup_plan.py`

```python
def test_dc_setup_plan_docstring_accurate(self):
    """DCSetupPlan docstring should NOT claim BootstrapPlan runs first."""
    from components.plans.dc_setup import DCSetupPlan
    docstring = DCSetupPlan.__doc__
    # Should NOT claim BootstrapPlan runs first (it doesn't for DC)
    assert "AFTER BootstrapPlan" not in docstring
```

#### Step 2: Verify test fails

#### Step 3: Update DCSetupPlan docstring

---

## Issue 5: Inconsistent user_data Template Variables (LOW)

### Problem
Templates still receive `hostname` variable but don't need it after removing hostname setup.

### Solution
Clean up template variables in `instance.py._generate_user_data()`.

### TDD Steps

#### Step 1: Update conftest.py temp_templates to not require hostname
**File:** `tests/conftest.py`

Update the temp template fixtures to not use `{{ hostname }}` variable.

#### Step 2: Update instance.py to not pass hostname to victim templates

---

## Execution Order

| Priority | Issue | Est. LOC Changed | Risk |
|----------|-------|------------------|------|
| 1 | Issue 1: KaliSetupPlan dedup | ~50 | Low - just routing change |
| 2 | Issue 2: Double hostname | ~30 | Medium - behavior change |
| 3 | Issue 3: Orphaned method | ~20 | None - deletion |
| 4 | Issue 4: Doc mismatch | ~5 | None - comments only |
| 5 | Issue 5: Template vars | ~10 | Low - cleanup |

---

## Files to Modify

### Delete
- `components/plans/kali_setup.py` (after deprecation period)

### Modify
- `components/instance.py` - remove orphaned method, update attacker plan routing
- `components/plans/dc_setup.py` - fix docstring
- `templates/victim_linux.sh.j2` - remove hostname setup
- `templates/victim_windows.ps1.j2` - remove hostname setup
- `tests/test_kali_setup_plan.py` - add deprecation test
- `tests/test_linux_bootstrap_plan.py` - add kali user test
- `tests/test_instance_component.py` - add plan routing tests
- `tests/test_user_data.py` - update template expectations
- `tests/test_dc_setup_plan.py` - add docstring test
- `tests/conftest.py` - update temp templates

---

## Rollback Plan

If issues arise in production:
1. Revert to previous KaliSetupPlan routing in instance.py
2. Restore hostname setup in templates
3. All changes are backward compatible at plan level

---

## Verification

After all changes:
```bash
cd shifter-engine
source .venv/bin/activate
python -m pytest tests/ -v
```

All 550+ tests should pass.
