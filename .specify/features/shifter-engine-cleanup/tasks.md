# Shifter Engine Cleanup - Tasks

## Phase 1: Issue 1 - Consolidate KaliSetupPlan into LinuxBootstrapPlan

### Tests First (RED)

- [ ] **T1.1** Add test: `test_get_context_works_for_kali_user` in `test_linux_bootstrap_plan.py`
  - Verify LinuxBootstrapPlan.get_context() works with ssh_user="kali"

- [ ] **T1.2** Add test: `test_attacker_uses_linux_bootstrap_plan` in `test_instance_component.py`
  - Mock SSM orchestrator
  - Verify attacker role uses LinuxBootstrapPlan (not KaliSetupPlan)
  - Verify context has ssh_user="kali"

- [ ] **T1.3** Run tests, verify T1.2 fails (attacker currently uses KaliSetupPlan)

### Implementation (GREEN)

- [ ] **I1.1** Update `instance.py:run_setup()` attacker branch (line ~614-623)
  - Replace `KaliSetupPlan()` with `LinuxBootstrapPlan()`
  - Set `ctx.ssh_user = "kali"` before calling get_context()

- [ ] **I1.2** Run tests, verify T1.1 and T1.2 pass

### Refactor (REFACTOR)

- [ ] **R1.1** Add deprecation warning to `kali_setup.py` module
  - `warnings.warn("KaliSetupPlan is deprecated. Use LinuxBootstrapPlan with ssh_user='kali'", DeprecationWarning)`

- [ ] **R1.2** Update `test_kali_setup_plan.py` to expect deprecation warning on import

- [ ] **R1.3** Run all tests, verify pass

---

## Phase 2: Issue 2 - Remove Duplicate Hostname Setup from user_data

### Tests First (RED)

- [ ] **T2.1** Update `test_victim_linux_template_valid_bash` in `test_user_data.py`
  - Remove assertion: `assert "hostnamectl set-hostname" in result`
  - Add assertion: `assert "hostnamectl" not in result`

- [ ] **T2.2** Update `test_victim_windows_template_valid_powershell` in `test_user_data.py`
  - Remove assertion: `assert "Rename-Computer" in result`
  - Add assertion: `assert "Rename-Computer" not in result`

- [ ] **T2.3** Run tests, verify T2.1 and T2.2 fail

### Implementation (GREEN)

- [ ] **I2.1** Update `templates/victim_linux.sh.j2`
  - Remove lines 8-12 (hostname setup block)
  - Update comment to explain SSM handles hostname

- [ ] **I2.2** Update `templates/victim_windows.ps1.j2`
  - Remove Rename-Computer call (line ~20)
  - Update comment to explain SSM handles hostname

- [ ] **I2.3** Run tests, verify T2.1 and T2.2 pass

### Refactor (REFACTOR)

- [ ] **R2.1** Update conftest.py temp templates to match new structure
  - Remove hostname setup from temp victim templates

- [ ] **R2.2** Clean up instance.py._generate_user_data()
  - Remove `hostname` from context for victim templates (no longer needed)

- [ ] **R2.3** Run all tests, verify pass

---

## Phase 3: Issue 3 - Remove Orphaned `_generate_secure_password()` Method

### Tests First (RED)

- [ ] **T3.1** Add test: `test_no_orphaned_generate_password_method` in `test_instance_component.py`
  - `assert not hasattr(InstanceComponent, '_generate_secure_password')`

- [ ] **T3.2** Run test, verify fails

### Implementation (GREEN)

- [ ] **I3.1** Delete `_generate_secure_password()` method from `instance.py` (lines 761-778)

- [ ] **I3.2** Run tests, verify T3.1 passes

### Refactor (REFACTOR)

- [ ] **R3.1** Search codebase for any remaining references to this method
- [ ] **R3.2** Run all tests, verify pass

---

## Phase 4: Issue 4 - Fix DCSetupPlan Docstring

### Tests First (RED)

- [ ] **T4.1** Add test: `test_dc_setup_plan_docstring_accurate` in `test_dc_setup_plan.py`
  - Verify docstring does NOT claim "AFTER BootstrapPlan"

- [ ] **T4.2** Run test, verify fails

### Implementation (GREEN)

- [ ] **I4.1** Update DCSetupPlan docstring (dc_setup.py:78-91)
  - Remove "This plan runs AFTER BootstrapPlan completes"
  - Add accurate description: "DC uses prebaked AMI; hostname/SSH configured via user_data"

- [ ] **I4.2** Run tests, verify T4.1 passes

### Refactor (REFACTOR)

- [ ] **R4.1** Review other plan docstrings for accuracy
- [ ] **R4.2** Run all tests, verify pass

---

## Phase 5: Final Cleanup

- [ ] **F5.1** Run full test suite: `python -m pytest tests/ -v`
- [ ] **F5.2** Verify all 550+ tests pass
- [ ] **F5.3** Run linter: `ruff check components/ tests/`
- [ ] **F5.4** Run type checker if available
- [ ] **F5.5** Manual smoke test: Deploy to dev and launch a range

---

## Completion Checklist

- [ ] All tests pass
- [ ] No new warnings in test output
- [ ] Code review completed
- [ ] Changes documented in CHANGELOG.md
- [ ] PR created for dev branch
