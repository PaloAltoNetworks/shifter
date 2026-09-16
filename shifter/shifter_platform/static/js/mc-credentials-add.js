/* global ShifterDropdown */
// Mission Control add-credential form: type-driven field visibility, live
// validation, and credential creation.
//
// Extracted from the inline <script> block in
// templates/mission_control/credentials/add.html so the template stays
// within Sonar's Web:LongJavaScriptCheck limit. The CSRF token and the
// create / list URLs are passed in via the #mc-credentials-add-config
// json_script payload. ShifterDropdown is provided by dropdown.js.

document.addEventListener('DOMContentLoaded', function () {
    const configEl = document.getElementById('mc-credentials-add-config');
    const config = configEl ? JSON.parse(configEl.textContent) : {};
    const csrfToken = config.csrfToken;

    // State
    let selectedType = null;

    // Elements
    const typeDropdownEl = document.getElementById('type-dropdown');
    const regionDropdownEl = document.getElementById('region-dropdown');
    const commonFields = document.getElementById('common-fields');
    const scmFields = document.getElementById('scm-fields');
    const profileFields = document.getElementById('profile-fields');
    const optionalFields = document.getElementById('optional-fields');
    const infoScm = document.getElementById('info-scm');
    const infoProfile = document.getElementById('info-profile');
    const submitBtn = document.getElementById('submit-btn');

    // Initialize dropdowns using global Dropdown class
    ShifterDropdown.init(typeDropdownEl);
    ShifterDropdown.init(regionDropdownEl);

    // Type dropdown change handler
    typeDropdownEl.addEventListener('change', function (e) {
        const value = e.detail.value;
        selectedType = value;

        // Show/hide info callouts
        infoScm.classList.toggle('active', value === 'scm');
        infoProfile.classList.toggle('active', value === 'deployment_profile');

        // Show common fields
        commonFields.classList.add('active');
        optionalFields.classList.add('active');

        // Focus the name input
        document.getElementById('name').focus();

        // Show type-specific fields
        scmFields.classList.toggle('active', value === 'scm');
        profileFields.classList.toggle('active', value === 'deployment_profile');

        // Update submit button state
        validateForm();

        // Update placeholder
        const nameInput = document.getElementById('name');
        if (value === 'scm') {
            nameInput.placeholder = 'e.g., Production SCM Registration';
        } else if (value === 'deployment_profile') {
            nameInput.placeholder = 'e.g., Production VM-Series License';
        }
    });

    // Region dropdown change handler
    regionDropdownEl.addEventListener('change', function () {
        validateForm();
    });

    // Form validation on input
    document.querySelectorAll('input').forEach(function (input) {
        input.addEventListener('input', validateForm);
    });

    function validateForm() {
        if (!selectedType) {
            submitBtn.disabled = true;
            return;
        }

        const name = document.getElementById('name').value.trim();
        if (!name) {
            submitBtn.disabled = true;
            return;
        }

        if (selectedType === 'scm') {
            const pinId = document.getElementById('scm_pin_id').value.trim();
            const pinValue = document.getElementById('scm_pin_value').value.trim();
            const region = document.getElementById('region-select-value').value;

            submitBtn.disabled = !(pinId && pinValue && region);
        } else if (selectedType === 'deployment_profile') {
            const authcode = document.getElementById('authcode').value.trim();
            submitBtn.disabled = !authcode;
        }
    }

    // Form submission
    document.getElementById('credentialForm').addEventListener('submit', function (e) {
        e.preventDefault();

        const data = {
            name: document.getElementById('name').value.trim(),
            credential_type: selectedType,
            expires_at: document.getElementById('expires_at').value || null
        };

        if (selectedType === 'scm') {
            data.scm_folder_name = document.getElementById('scm_folder_name').value.trim();
            data.scm_pin_id = document.getElementById('scm_pin_id').value.trim();
            data.scm_pin_value = document.getElementById('scm_pin_value').value;
            data.sls_region = document.getElementById('region-select-value').value;
        } else if (selectedType === 'deployment_profile') {
            data.authcode = document.getElementById('authcode').value;
        }

        fetch(config.createUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if (result.error) {
                alert(result.error);
            } else {
                // config.listUrl is a server-rendered path; validate same-origin
                // so a tampered DOM value can't redirect off-origin or via a
                // javascript: URI.
                const listTarget = new URL(config.listUrl, globalThis.location.origin);
                if (listTarget.origin === globalThis.location.origin) {
                    globalThis.location.href = listTarget.href;
                }
            }
        })
        .catch(() => {
            alert('An error occurred. Please try again.');
        });
    });
});

function togglePassword(inputId) {
    const input = document.getElementById(inputId);
    input.type = input.type === 'password' ? 'text' : 'password';
}

globalThis.togglePassword = togglePassword;
