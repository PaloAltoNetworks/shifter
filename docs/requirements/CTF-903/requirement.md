---
id: CTF-903
title: "Browser-Based Range Access"
status: ACTIVE
type: INTERFACE
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:23.534781Z
updated_at: 2026-03-26T06:10:26.923031Z
---

# CTF-903: Browser-Based Range Access

## Statement

CTF participants shall access their range VMs via the existing Mission Control terminal page, which provides browser-based RDP and SSH access through Guacamole. No CTF-specific browser access implementation is needed. Browser-based remote access connections are automatically configured when ranges are provisioned via CMS, mapping each participant to their specific VM instances. The CTF layer shall not duplicate Guacamole URL generation or connection info assembly.

## Rationale

Browser-based access is non-negotiable for Shifter's target users, PANW consultants cannot install VPN clients, RDP tools, or SSH clients on their corporate laptops. Guacamole provides zero-install access to VMs via the browser. This already exists in Mission Control and must extend to CTF events so participants can seamlessly access their attack boxes.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTF Models - CTFParticipant range fields)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/guacamole.py` (Guacamole integration - RDP and SSH URL generation)
- IMPLEMENTS → CODE_FILE `mission_control/views.py` (mission_control guacamole_rdp_url endpoint - browser-based RDP access)
- IMPLEMENTS → CODE_FILE `templates/mission_control/terminal.html` (Terminal page - browser-based RDP/SSH UI for range access)
- IMPLEMENTS → CODE_FILE `engine/services.py` (engine get_rdp_connection_info - connection info for Guacamole)
- TESTS → TEST `tests/mission_control/test_guacamole_ssh.py` (Guacamole SSH/RDP URL generation tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#543` (CTF-903: Browser-Based Range Access)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#848` (Guacamole URL bootstrap blocks portal requests on synchronous token API call)
- IMPLEMENTS → PULL_REQUEST `Brad-Edwards/shifter#854` (Fix Guacamole bootstrap request blocking)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/guacamole_bootstrap.py` (Async Guacamole bootstrap runner)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/views/_guacamole_bootstrap.py` (Guacamole bootstrap polling views)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/models.py` (GuacamoleBootstrapRequest pollable state model)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/static/js/terminal-guacamole.js` (Terminal Guacamole bootstrap polling client)
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_views_guacamole.py` (Guacamole bootstrap view tests)
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_api_instance_ssh_url.py` (Range instance Guacamole bootstrap API tests)
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_api_ngfw_ssh_url.py` (NGFW Guacamole bootstrap API tests)
- TESTS → TEST `shifter/shifter_platform/static/js/terminal-guacamole.test.js` (Terminal Guacamole polling client tests)
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_guacamole_readiness.py` (Guacamole token-exchange readiness retry tests (issue #395))
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_guacamole_ssh.py` (Guacamole SSH URL generation unit tests)
- DOCUMENTS → DOCUMENTATION `docs/architecture/guacamole-first-click-rdp-preflight-395.md` (First-click Guacamole RDP preflight design note (issue #395))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/api/ranges.py` (CTF Views - api_range_access endpoint)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/guacamole_session.py` (Guacamole remote-access session service (browser-based range access orchestration))
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_guacamole_session.py` (Behavior tests for the Guacamole remote-access session service)
