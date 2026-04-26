# Health Check Implementation Checklist

Deep health checks with secure token-based URL for ALB-only access.

**Goal:** Replace shallow health check middleware with django-health-check using token validation.

**TDD Contract:** Every function MUST test all five aspects: Inputs, Outputs, Side Effects, Errors, Logging per SKILL.md

---

## Phase 1: Terraform Infrastructure (Token Generation & Secret Storage)

### Phase 1.1: Add health check token to dev environment
- [ ] Phase 1.1 PREP: Review terraform test patterns and existing secret structure
- [ ] Phase 1.1 IMPLEMENT: Add random_id.health_check_token to dev/portal/main.tf
- [ ] Phase 1.1 IMPLEMENT: Add health_check_token to aws_secretsmanager_secret_version.app JSON
- [ ] Phase 1.1 IMPLEMENT: Update module.alb health_check_path to use token
- [ ] Phase 1.1 VERIFY: Run terraform fmt -check platform/terraform/environments/dev/portal/main.tf
- [ ] Phase 1.1 VERIFY: Run terraform validate in platform/terraform/environments/dev/portal/
- [ ] Phase 1.1 VERIFY: Run terraform plan, confirm creates random_id and updates secret

### Phase 1.2: Add health check token to prod environment
- [ ] Phase 1.2 IMPLEMENT: Add random_id.health_check_token to prod/portal/main.tf
- [ ] Phase 1.2 IMPLEMENT: Add health_check_token to aws_secretsmanager_secret_version.app JSON
- [ ] Phase 1.2 IMPLEMENT: Update module.alb health_check_path to use token
- [ ] Phase 1.2 VERIFY: Run terraform fmt -check platform/terraform/environments/prod/portal/main.tf
- [ ] Phase 1.2 VERIFY: Run terraform validate in platform/terraform/environments/prod/portal/
- [ ] Phase 1.2 VERIFY: Run terraform plan, confirm creates random_id and updates secret

### Phase 1.FINAL: Verify Terraform consistency
- [ ] Phase 1.FINAL VERIFY: Run terraform fmt -check -recursive platform/terraform/
- [ ] Phase 1.FINAL VERIFY: Confirm dev and prod implementations are consistent
- [ ] Phase 1.FINAL VERIFY: Review terraform plan output for both environments

---

## Phase 2: Django URL Configuration (Token-Based Health Check Endpoint)

### Phase 2.1: Test URL module configuration loading (urls.py module-level code)
- [ ] Phase 2.1 PREP: Read .claude/skills/tdd/SKILL.md sections on testing module initialization
- [ ] Phase 2.1 RED: Write failing tests in tests/test_urls_configuration.py::TestHealthCheckURLLoading

  **Happy Path - Outputs & Side Effects:**
  - test_loads_health_check_token_from_environment_variable
  - test_creates_url_pattern_with_token_in_path
  - test_url_pattern_includes_django_health_check_routes
  - test_urlpatterns_list_contains_health_check_entry

  **Input Validation - Minimum Required Data:**
  - test_succeeds_with_alphanumeric_token_string
  - test_succeeds_with_32_char_hex_token
  - test_raises_value_error_when_HEALTH_CHECK_TOKEN_missing_production
  - test_raises_value_error_when_HEALTH_CHECK_TOKEN_empty_production
  - test_raises_value_error_when_HEALTH_CHECK_TOKEN_none_production
  - test_allows_missing_token_when_DEBUG_true

  **Error Handling - Dependency Failures:**
  - test_propagates_import_error_from_health_check_module
  - test_logs_error_when_token_validation_fails_production
  - test_raises_value_error_with_clear_message_missing_token
  - test_raises_value_error_with_clear_message_empty_token

  **Logging - Observability:**
  - test_logs_info_when_health_check_url_configured_successfully
  - test_logs_warning_when_token_missing_debug_mode
  - test_logs_token_length_not_token_value
  - test_logs_error_when_configuration_fails

  **Boundary Conditions:**
  - test_handles_token_with_forward_slash_characters
  - test_handles_token_with_special_url_chars
  - test_handles_128_char_token_string
  - test_handles_whitespace_in_token_value

- [ ] Phase 2.1 VERIFY RED: Run pytest tests/test_urls_configuration.py::TestHealthCheckURLLoading -v, confirm NotImplementedError or failures
- [ ] Phase 2.1 GREEN: Implement token loading and URL pattern creation in config/urls.py
  - Load HEALTH_CHECK_TOKEN from os.environ
  - Validate token (non-empty, required in production)
  - Create path(f"ht/{token}/", include("health_check.urls"))
  - Add logging statements
- [ ] Phase 2.1 VERIFY GREEN: Run pytest tests/test_urls_configuration.py::TestHealthCheckURLLoading -v, confirm all pass

### Phase 2.2: Test health check endpoint HTTP behavior
- [ ] Phase 2.2 PREP: Read .claude/skills/tdd/SKILL.md sections on integration testing
- [ ] Phase 2.2 RED: Write failing tests in tests/test_health_check_endpoint.py::TestHealthCheckHTTPBehavior

  **Happy Path - Outputs & Side Effects:**
  - test_returns_200_status_with_valid_token_url
  - test_returns_json_content_type_header
  - test_response_contains_status_field
  - test_response_contains_db_check_result
  - test_response_contains_cache_check_result
  - test_response_contains_storage_check_result

  **Input Validation:**
  - test_returns_404_with_incorrect_token
  - test_returns_404_with_partial_token
  - test_returns_404_with_no_token_in_path
  - test_returns_404_for_old_health_endpoint
  - test_returns_404_for_old_health_slash_endpoint

  **Error Handling:**
  - test_returns_503_when_database_unavailable
  - test_returns_503_when_cache_unavailable
  - test_returns_200_when_storage_fails_noncritical
  - test_logs_error_when_database_check_fails
  - test_logs_error_when_cache_check_fails

  **Logging:**
  - test_logs_info_on_health_check_request
  - test_logs_debug_on_successful_check
  - test_does_not_log_token_value_in_any_log_message

  **Boundary Conditions:**
  - test_handles_concurrent_health_check_requests
  - test_handles_health_check_during_database_connection_spike
  - test_handles_health_check_timeout_scenarios

- [ ] Phase 2.2 VERIFY RED: Run pytest tests/test_health_check_endpoint.py::TestHealthCheckHTTPBehavior -v, confirm failures
- [ ] Phase 2.2 GREEN: Verify django-health-check works with token URL (no implementation needed if package correct)
- [ ] Phase 2.2 VERIFY GREEN: Run pytest tests/test_health_check_endpoint.py::TestHealthCheckHTTPBehavior -v, confirm all pass

### Phase 2.FINAL: Verify URL configuration
- [ ] Phase 2.FINAL VERIFY: Run pytest tests/test_urls_configuration.py tests/test_health_check_endpoint.py -v
- [ ] Phase 2.FINAL VERIFY: Confirm all URL tests pass

---

## Phase 3: Middleware Removal

### Phase 3.1: Test middleware configuration (settings.py MIDDLEWARE list)
- [ ] Phase 3.1 PREP: Read .claude/skills/tdd/SKILL.md to refresh TDD protocol
- [ ] Phase 3.1 RED: Write failing tests in tests/test_middleware_configuration.py::TestHealthCheckMiddlewareRemoval

  **Happy Path - Outputs:**
  - test_health_check_middleware_not_in_middleware_list
  - test_middleware_list_contains_only_expected_entries
  - test_middleware_order_preserved_after_removal

  **Input Validation:**
  - test_allowed_hosts_validation_active_for_all_requests
  - test_invalid_host_header_returns_400_bad_request
  - test_valid_host_header_passes_validation

  **Error Handling:**
  - test_disallowed_host_returns_400_not_500
  - test_logs_warning_on_disallowed_host_attempt

  **Logging:**
  - test_logs_debug_when_middleware_loads_successfully

  **Boundary Conditions:**
  - test_empty_host_header_returns_400
  - test_extremely_long_host_header_handled_safely

- [ ] Phase 3.1 VERIFY RED: Run pytest tests/test_middleware_configuration.py::TestHealthCheckMiddlewareRemoval -v
- [ ] Phase 3.1 GREEN: Remove "config.middleware.HealthCheckMiddleware" from MIDDLEWARE list in settings.py
- [ ] Phase 3.1 VERIFY GREEN: Run pytest tests/test_middleware_configuration.py::TestHealthCheckMiddlewareRemoval -v

### Phase 3.2: Verify middleware file deletion safety
- [ ] Phase 3.2 PREP: Read .claude/skills/tdd/SKILL.md to refresh protocol
- [ ] Phase 3.2 RED: Write failing tests in tests/test_middleware_configuration.py::TestMiddlewareFileRemoval

  **Happy Path:**
  - test_middleware_module_not_importable_after_deletion
  - test_no_import_errors_in_settings_module

  **Error Handling:**
  - test_import_error_raised_if_middleware_imported_explicitly

  **Side Effects:**
  - test_middleware_file_does_not_exist_at_expected_path

- [ ] Phase 3.2 VERIFY RED: Run pytest tests/test_middleware_configuration.py::TestMiddlewareFileRemoval -v
- [ ] Phase 3.2 GREEN: Delete shifter/shifter_platform/config/middleware.py
- [ ] Phase 3.2 VERIFY GREEN: Run pytest tests/test_middleware_configuration.py::TestMiddlewareFileRemoval -v

### Phase 3.FINAL: Verify middleware changes
- [ ] Phase 3.FINAL VERIFY: Run pytest tests/test_middleware_configuration.py -v
- [ ] Phase 3.FINAL VERIFY: Run grep -r "HealthCheckMiddleware" shifter/shifter_platform/ --exclude-dir=tests
- [ ] Phase 3.FINAL VERIFY: Confirm no imports found (exit code 1 from grep)

---

## Phase 4: Entrypoint Script (Token Extraction from Secrets)

### Phase 4.1: Add token extraction bash function to entrypoint.sh
- [ ] Phase 4.1 PREP: Review entrypoint.sh existing secret extraction pattern
- [ ] Phase 4.1 IMPLEMENT: Add HEALTH_CHECK_TOKEN extraction in entrypoint.sh

  **Implementation Requirements:**
  ```bash
  # After APP_SECRET fetch (around line 40):
  export HEALTH_CHECK_TOKEN=$(echo "$APP_SECRET" | python -c "import sys, json; print(json.load(sys.stdin)['health_check_token'])")
  ```

  **Must match pattern:**
  - Extract from APP_SECRET JSON
  - Use python -c one-liner like django_secret_key
  - Export as HEALTH_CHECK_TOKEN
  - No error handling needed (fails fast if key missing)

- [ ] Phase 4.1 VERIFY: Run shellcheck entrypoint.sh (if available)
- [ ] Phase 4.1 VERIFY: Visually confirm extraction matches django_secret_key pattern
- [ ] Phase 4.1 VERIFY: Run manual test with sample JSON to confirm extraction works

---

## Phase 5: Django Health Check Configuration

### Phase 5.1: Test HEALTH_CHECK settings configuration
- [ ] Phase 5.1 PREP: Read django-health-check documentation for available settings
- [ ] Phase 5.1 RED: Write failing tests in tests/test_settings_health_check.py::TestHealthCheckSettings

  **Happy Path - Outputs:**
  - test_health_check_setting_exists_in_settings_module
  - test_health_check_is_dictionary_type
  - test_health_check_contains_disk_usage_max_key
  - test_health_check_contains_memory_min_key

  **Input Validation:**
  - test_health_check_disk_usage_max_is_integer
  - test_health_check_memory_min_is_integer
  - test_health_check_disk_usage_max_reasonable_value
  - test_health_check_memory_min_reasonable_value

  **Error Handling:**
  - test_django_health_check_module_installed_in_installed_apps
  - test_health_check_db_module_installed
  - test_health_check_cache_module_installed
  - test_health_check_storage_module_installed

  **Logging:**
  - test_logs_debug_when_health_check_settings_loaded

  **Boundary Conditions:**
  - test_health_check_settings_work_with_minimal_config
  - test_health_check_settings_optional_keys_absent_ok

- [ ] Phase 5.1 VERIFY RED: Run pytest tests/test_settings_health_check.py::TestHealthCheckSettings -v
- [ ] Phase 5.1 GREEN: Add HEALTH_CHECK dictionary to settings.py
  ```python
  HEALTH_CHECK = {
      'DISK_USAGE_MAX': 90,  # Fail if disk >90% full
      'MEMORY_MIN': 100,      # Fail if <100MB RAM free
  }
  ```
- [ ] Phase 5.1 VERIFY GREEN: Run pytest tests/test_settings_health_check.py::TestHealthCheckSettings -v

---

## Phase 6: Integration Testing (Full End-to-End Flow)

### Phase 6.1: Test complete health check flow with all components
- [ ] Phase 6.1 PREP: Read .claude/skills/tdd/SKILL.md integration testing section
- [ ] Phase 6.1 RED: Write failing tests in tests/test_health_check_integration.py::TestHealthCheckIntegration

  **Happy Path - Full Flow:**
  - test_health_check_with_token_validates_database_successfully
  - test_health_check_with_token_validates_cache_successfully
  - test_health_check_with_token_validates_storage_successfully
  - test_health_check_returns_all_subsystem_statuses
  - test_health_check_response_matches_expected_json_schema

  **Input Validation:**
  - test_wrong_token_returns_404_not_health_check_response
  - test_missing_token_returns_404_not_health_check_response

  **Error Handling:**
  - test_database_failure_returns_503_service_unavailable
  - test_database_failure_includes_error_details_in_response
  - test_cache_failure_returns_503_service_unavailable
  - test_cache_failure_includes_error_details_in_response
  - test_storage_failure_marked_unhealthy_but_not_critical
  - test_logs_error_with_full_context_on_subsystem_failure

  **Logging:**
  - test_logs_info_on_health_check_start
  - test_logs_debug_for_each_subsystem_check
  - test_logs_summary_with_all_results
  - test_does_not_log_sensitive_credentials

  **Boundary Conditions:**
  - test_health_check_completes_within_timeout
  - test_concurrent_health_checks_do_not_interfere
  - test_health_check_during_high_database_load
  - test_health_check_with_slow_database_response

- [ ] Phase 6.1 VERIFY RED: Run pytest tests/test_health_check_integration.py::TestHealthCheckIntegration -v
- [ ] Phase 6.1 GREEN: Verify all components integrate correctly (no additional code needed if tests pass)
- [ ] Phase 6.1 VERIFY GREEN: Run pytest tests/test_health_check_integration.py::TestHealthCheckIntegration -v

---

## Phase 7: Documentation

### Phase 7.1: Update secrets documentation
- [ ] Phase 7.1 IMPLEMENT: Add health_check_token to documentation/docs/dev/secrets.md

  **Add to "Portal Secrets" table:**
  ```markdown
  | `shifter-{env}-portal-app` | Django SECRET_KEY, field_encryption_key, health_check_token |
  ```

  **Add new section "Health Check Token":**
  ```markdown
  ### Health Check Token

  **Purpose:** Secure token embedded in health check URL path to prevent public access.
  Only the ALB knows this token value.

  **Generation:** Terraform generates using `random_id` resource (32 bytes, hex-encoded).

  **Usage:**
  - Stored in `shifter-{env}-portal-app` secret as `health_check_token`
  - Loaded by entrypoint.sh into `HEALTH_CHECK_TOKEN` environment variable
  - Used in config/urls.py to create path: `/ht/{token}/`
  - ALB health check configured to use this path

  **Security:** Token value must never be logged or exposed. Logs should only include token length.
  ```

- [ ] Phase 7.1 VERIFY: Review documentation for accuracy, completeness, clarity
- [ ] Phase 7.1 VERIFY: Confirm no token values included in documentation

---

## Phase 8: Final Verification & Quality Gates

- [ ] Phase 8.1 VERIFY: Run full Django test suite
  ```bash
  cd shifter/shifter_platform && python -m pytest tests/ -v --tb=short
  ```
- [ ] Phase 8.2 VERIFY: Run pre-commit on all modified files
  ```bash
  pre-commit run --files \
    shifter/shifter_platform/config/urls.py \
    shifter/shifter_platform/config/settings.py \
    shifter/shifter_platform/entrypoint.sh \
    platform/terraform/environments/dev/portal/main.tf \
    platform/terraform/environments/prod/portal/main.tf \
    shifter/shifter_platform/documentation/docs/dev/secrets.md
  ```
- [ ] Phase 8.3 VERIFY: Run linter on all test files
  ```bash
  cd shifter/shifter_platform && python -m ruff check tests/test_*health*.py tests/test_*middleware*.py tests/test_*settings*.py
  ```
- [ ] Phase 8.4 VERIFY: Terraform plan for dev shows expected changes
  ```bash
  cd platform/terraform/environments/dev/portal && terraform plan | grep -A5 -B5 "health_check"
  ```
- [ ] Phase 8.5 VERIFY: Terraform plan for prod shows expected changes
  ```bash
  cd platform/terraform/environments/prod/portal && terraform plan | grep -A5 -B5 "health_check"
  ```
- [ ] Phase 8.6 VERIFY: Search for old /health references
  ```bash
  grep -rn '"/health"' shifter/shifter_platform/ --exclude-dir=tests
  grep -rn "'/health'" shifter/shifter_platform/ --exclude-dir=tests
  # Should find ZERO matches outside tests
  ```
- [ ] Phase 8.7 VERIFY: Search for HealthCheckMiddleware references
  ```bash
  grep -rn "HealthCheckMiddleware" shifter/shifter_platform/ --exclude-dir=tests
  # Should find ZERO matches outside tests
  ```
- [ ] Phase 8.8 VERIFY: Confirm test coverage for all modified modules
  ```bash
  cd shifter/shifter_platform && python -m pytest --cov=config.urls --cov=config.settings --cov-report=term-missing
  ```

---

## Phase 9: Deployment Preparation

### Phase 9.1: Create deployment runbook
- [ ] Phase 9.1 DOCUMENT: Create temp/health-check-deployment-runbook.md with:

  **Pre-deployment checklist:**
  - All tests passing
  - All linters passing
  - Terraform plans reviewed

  **Deployment steps:**
  1. Apply Terraform to dev environment (generates token, updates ALB)
  2. Wait for Terraform apply to complete
  3. Verify secret in Secrets Manager contains health_check_token
  4. Deploy new Docker image to dev
  5. Monitor CloudWatch for health check requests
  6. Monitor ALB target health status
  7. Test health check endpoint manually with token
  8. Repeat for prod environment

  **Rollback plan:**
  - If health checks fail: Revert Terraform (removes token from secret)
  - If containers fail: Redeploy previous image tag
  - If ALB marks targets unhealthy: Check CloudWatch logs for errors

  **Monitoring:**
  - CloudWatch log group: `/aws/ecs/{env}-portal`
  - ALB target health: AWS Console > EC2 > Target Groups
  - Health check endpoint response time: <2s expected

- [ ] Phase 9.1 VERIFY: Review runbook with user
- [ ] Phase 9.1 VERIFY: Confirm rollback steps are clear and tested

### Phase 9.2: Final review and approval
- [ ] Phase 9.2 REVIEW: Present all changes to user
- [ ] Phase 9.2 REVIEW: Confirm test coverage meets requirements (all 5 aspects per function)
- [ ] Phase 9.2 REVIEW: Confirm deployment approach acceptable
- [ ] Phase 9.2 APPROVAL: Get explicit go-ahead before deployment

---

## Risk Mitigation

**If ALB health checks fail after deploy:**
1. Check CloudWatch logs: `aws logs tail /aws/ecs/{env}-portal --follow`
2. Verify token in container: `docker exec portal env | grep HEALTH_CHECK_TOKEN`
3. Verify ALB path matches: Compare ALB health_check_path to secret token value
4. Test endpoint manually: `curl -v https://{domain}/ht/{token}/`
5. Rollback: `git revert` and redeploy previous commit

**If tests fail during implementation:**
1. Create new Phase X.Y+1 with RED/GREEN/VERIFY cycle
2. Write test for the specific regression
3. Fix the issue
4. Re-run quality gates
5. Do not proceed until all tests pass

**If Terraform plan shows unexpected changes:**
1. Review plan output line by line
2. Confirm only health_check_token additions
3. Confirm no resource replacements (only updates)
4. If unsure, halt and discuss with user

---

## Expected Outcomes

**Functionality:**
- ✓ ALB health checks validate DB, cache, storage connectivity
- ✓ Health check endpoint only accessible via secure token
- ✓ Token only known to ALB (in terraform state and secrets manager)
- ✓ ALLOWED_HOSTS validation active for all non-health-check requests

**Code Quality:**
- ✓ Zero test regressions
- ✓ Zero linter errors
- ✓ 100% test coverage of modified code
- ✓ All tests follow SKILL.md five-aspect contract

**Security:**
- ✓ No custom middleware bypassing Django security
- ✓ Token never logged or exposed in plain text
- ✓ Public cannot access health check endpoint

**Operational:**
- ✓ Failed health checks detected within 30 seconds (ALB interval)
- ✓ Clear logs for debugging health check failures
- ✓ Deployment runbook created and tested

---

## Test Count Summary

**Per SKILL.md Contract (5 aspects per function):**

- Phase 2.1 (URL Loading): 20 tests
- Phase 2.2 (HTTP Behavior): 18 tests
- Phase 3.1 (Middleware Config): 10 tests
- Phase 3.2 (File Removal): 4 tests
- Phase 5.1 (Settings): 14 tests
- Phase 6.1 (Integration): 18 tests

**Total: 84 tests minimum**

Each test validates one specific aspect of the contract. No test validates multiple concerns.

---

## Files Modified

**Terraform:**
- `platform/terraform/environments/dev/portal/main.tf` (add random_id, update secret)
- `platform/terraform/environments/prod/portal/main.tf` (add random_id, update secret)

**Django:**
- `shifter/shifter_platform/config/urls.py` (add token loading, create health check URL)
- `shifter/shifter_platform/config/settings.py` (remove middleware, add HEALTH_CHECK dict)
- `shifter/shifter_platform/config/middleware.py` (DELETE entirely)
- `shifter/shifter_platform/entrypoint.sh` (add token extraction from secret)

**Tests (NEW - 84+ tests total):**
- `shifter/shifter_platform/tests/test_urls_configuration.py` (20 tests)
- `shifter/shifter_platform/tests/test_health_check_endpoint.py` (18 tests)
- `shifter/shifter_platform/tests/test_middleware_configuration.py` (14 tests)
- `shifter/shifter_platform/tests/test_settings_health_check.py` (14 tests)
- `shifter/shifter_platform/tests/test_health_check_integration.py` (18 tests)

**Documentation:**
- `shifter/shifter_platform/documentation/docs/dev/secrets.md` (add health_check_token section)
- `temp/health-check-deployment-runbook.md` (NEW - deployment procedures)
