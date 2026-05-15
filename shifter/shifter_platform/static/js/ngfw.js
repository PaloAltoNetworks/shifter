/**
 * NGFW Wizard Manager
 *
 * Handles the multi-step wizard for NGFW provisioning.
 * Manages form state, validation, API calls, and status polling.
 */
class NGFWWizardManager {
    constructor(options) {
        this.csrfToken = options.csrfToken;
        this.provisionUrl = options.provisionUrl;
        this.statusUrlTemplate = options.statusUrlTemplate;
        this.detailUrlTemplate = options.detailUrlTemplate;

        this.currentStep = 1;
        this.formData = {
            name: '',
            deployment_profile_id: null,
            deployment_profile_name: '',
            registration_method: 'pin',  // Default to PIN (OTP hidden in UI for now)
            scm_credential_id: null,
            scm_credential_name: '',
            otp_value: '',
            otp_folder: '',
            sls_region: 'americas'
        };

        this.ngfwId = null;
        this.ws = null;
    }

    init() {
        this.cacheElements();
        this.initDropdowns();
        this.bindEvents();
        this.setInitialState();
    }

    cacheElements() {
        this.elements = {
            steps: document.querySelectorAll('.wizard-step'),
            panels: document.querySelectorAll('.wizard-panel'),
            nameInput: document.getElementById('ngfw-name'),
            profileDropdown: document.getElementById('profile-dropdown'),
            scmDropdown: document.getElementById('scm-dropdown'),
            regionDropdown: document.getElementById('region-dropdown'),
            radioOptions: document.querySelectorAll('.radio-option'),
            pinFields: document.getElementById('pin-fields'),
            otpFields: document.getElementById('otp-fields'),
            otpValueInput: document.getElementById('otp-value'),
            otpFolderInput: document.getElementById('otp-folder'),
            provisioningProgress: document.getElementById('provisioning-progress'),
            successState: document.getElementById('success-state'),
            viewNgfwBtn: document.getElementById('view-ngfw-btn'),
            step1NextBtn: document.getElementById('step1-next'),
        };
    }

    initDropdowns() {
        // Deployment Profile dropdown
        this.initDropdown('profile-dropdown', (value, el) => {
            this.formData.deployment_profile_id = value;
            this.formData.deployment_profile_name = el.dataset.name;
            this.validateStep1();
        });

        // SCM Credential dropdown
        this.initDropdown('scm-dropdown', (value, el) => {
            this.formData.scm_credential_id = value;
            this.formData.scm_credential_name = el.dataset.name;
            this.formData.sls_region = el.dataset.region || 'americas';
        });

        // Region dropdown
        this.initDropdown('region-dropdown', (value) => {
            this.formData.sls_region = value;
        });
    }

    initDropdown(id, onChange) {
        const dropdown = document.getElementById(id);
        if (!dropdown) return;

        const trigger = dropdown.querySelector('.shifter-dropdown-trigger');
        const items = dropdown.querySelectorAll('.shifter-dropdown-item');
        const valueDisplay = dropdown.querySelector('.shifter-dropdown-value');
        const hiddenInput = dropdown.querySelector('input[type="hidden"]');

        trigger?.addEventListener('click', (e) => {
            e.preventDefault();
            dropdown.classList.toggle('open');
        });

        items.forEach((item) => {
            item.addEventListener('click', () => {
                const value = item.dataset.value;
                const label = item.querySelector('.item-label')?.textContent || item.textContent;

                items.forEach(i => i.classList.remove('selected'));
                item.classList.add('selected');

                if (valueDisplay) {
                    valueDisplay.textContent = label;
                    valueDisplay.classList.remove('placeholder');
                }
                if (hiddenInput) hiddenInput.value = value;

                dropdown.classList.remove('open');

                if (onChange) onChange(value, item);
            });
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target)) {
                dropdown.classList.remove('open');
            }
        });
    }

    bindEvents() {
        // Step navigation
        document.getElementById('step1-next')?.addEventListener('click', () => {
            if (this.validateStep1()) this.goToStep(2);
        });
        document.getElementById('step2-back')?.addEventListener('click', () => this.goToStep(1));
        document.getElementById('step2-next')?.addEventListener('click', () => {
            if (this.validateStep2()) {
                this.updateSummary();
                this.goToStep(3);
            }
        });
        document.getElementById('step3-back')?.addEventListener('click', () => this.goToStep(2));
        document.getElementById('step3-provision')?.addEventListener('click', () => this.startProvisioning());

        // Name input
        this.elements.nameInput?.addEventListener('input', (e) => {
            this.formData.name = e.target.value.trim();
            this.validateStep1();
        });

        // Registration method toggle
        this.elements.radioOptions.forEach((option) => {
            option.addEventListener('click', () => {
                const method = option.dataset.method;
                this.formData.registration_method = method;

                this.elements.radioOptions.forEach(o => o.classList.remove('selected'));
                option.classList.add('selected');
                option.querySelector('input').checked = true;

                this.elements.pinFields?.classList.toggle('visible', method === 'pin');
                this.elements.otpFields?.classList.toggle('visible', method === 'otp');
            });
        });

        // OTP inputs
        this.elements.otpValueInput?.addEventListener('input', (e) => {
            this.formData.otp_value = e.target.value.trim();
        });
        this.elements.otpFolderInput?.addEventListener('input', (e) => {
            this.formData.otp_folder = e.target.value.trim();
        });
    }

    setInitialState() {
        // PIN is the default method (set in HTML as selected/checked)
        // Nothing extra needed here since OTP option is hidden
    }

    goToStep(step) {
        this.currentStep = step;

        // Update step indicators
        this.elements.steps.forEach((s, i) => {
            const stepNum = i + 1;
            s.classList.remove('active', 'completed');
            if (stepNum < step) {
                s.classList.add('completed');
            } else if (stepNum === step) {
                s.classList.add('active');
            }
        });

        // Show panel
        this.elements.panels.forEach((p) => {
            p.classList.remove('active');
        });
        const targetPanel = document.getElementById('step-' + step);
        if (targetPanel) {
            targetPanel.classList.add('active');
        }
    }

    validateStep1() {
        const nameValid = this.formData.name.length > 0;
        const profileValid = this.formData.deployment_profile_id !== null;

        if (this.elements.step1NextBtn) {
            this.elements.step1NextBtn.disabled = !(nameValid && profileValid);
        }
        return nameValid && profileValid;
    }

    validateStep2() {
        if (this.formData.registration_method === 'pin') {
            return this.formData.scm_credential_id !== null;
        } else {
            return this.formData.otp_value.length > 0 && this.formData.otp_folder.length > 0;
        }
    }

    updateSummary() {
        const setTextContent = (id, text) => {
            const el = document.getElementById(id);
            if (el) el.textContent = text;
        };

        setTextContent('summary-name', this.formData.name);
        setTextContent('summary-profile', this.formData.deployment_profile_name);

        const credentialRow = document.getElementById('summary-credential-row');
        const folderRow = document.getElementById('summary-folder-row');

        if (this.formData.registration_method === 'pin') {
            setTextContent('summary-method', 'Stored PIN');
            setTextContent('summary-credential', this.formData.scm_credential_name);
            if (credentialRow) credentialRow.style.display = '';
            if (folderRow) folderRow.style.display = 'none';
        } else {
            setTextContent('summary-method', 'One-Time Password');
            if (credentialRow) credentialRow.style.display = 'none';
            setTextContent('summary-folder', this.formData.otp_folder);
            if (folderRow) folderRow.style.display = '';
        }

        const regionNames = {
            americas: 'Americas',
            europe: 'Europe',
            japan: 'Japan',
            asiapacific: 'Asia Pacific'
        };
        setTextContent('summary-region', regionNames[this.formData.sls_region] || this.formData.sls_region);
    }

    async startProvisioning() {
        this.goToStep(4);

        // Build request payload
        const payload = {
            name: this.formData.name,
            deployment_profile_id: this.formData.deployment_profile_id,
            registration_method: this.formData.registration_method
        };

        if (this.formData.registration_method === 'pin') {
            payload.scm_credential_id = this.formData.scm_credential_id;
        } else {
            payload.otp_value = this.formData.otp_value;
            payload.otp_folder = this.formData.otp_folder;
            payload.sls_region = this.formData.sls_region;
        }

        try {
            const response = await fetch(this.provisionUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken
                },
                body: JSON.stringify(payload)
            });

            const data = await response.json();

            if (data.error) {
                alert('Error: ' + data.error);
                this.goToStep(3);
                return;
            }

            // Connect WebSocket for status updates
            this.ngfwId = data.id;
            if (this.elements.viewNgfwBtn) {
                this.elements.viewNgfwBtn.href = this.detailUrlTemplate.replace('{id}', this.ngfwId);
            }
            this.connectWebSocket();

        } catch (err) {
            console.error('Provisioning error:', err);
            alert('An error occurred. Please try again.');
            this.goToStep(3);
        }
    }

    connectWebSocket() {
        const wsProtocol = globalThis.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${globalThis.location.host}/ws/ngfw-status/${this.ngfwId}/`;

        console.log('Connecting to WebSocket:', wsUrl);
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('NGFW status WebSocket connected');
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                console.log('NGFW status update:', data);

                if (data.status === 'ready') {
                    this.showSuccess();
                    this.ws.close();
                } else if (data.status === 'failed') {
                    alert('Provisioning failed: ' + (data.error || 'Unknown error'));
                    globalThis.location.href = this.detailUrlTemplate.replace('{id}', this.ngfwId);
                }
                // For other statuses (pending, provisioning, stopped), just wait for next message
            } catch (err) {
                console.error('Error parsing WebSocket message:', err);
            }
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };

        this.ws.onclose = (event) => {
            console.log('WebSocket closed:', event.code, event.reason);
        };
    }

    showSuccess() {
        if (this.elements.provisioningProgress) {
            this.elements.provisioningProgress.style.display = 'none';
        }
        if (this.elements.successState) {
            this.elements.successState.style.display = 'block';
        }
    }

    // Debug helpers - call from console: wizard.debugShowSuccess() or wizard.debugGoToStep(4)
    debugShowSuccess() {
        this.goToStep(4);
        this.showSuccess();
    }

    debugGoToStep(step) {
        this.goToStep(step);
    }
}

// Export for use in templates
globalThis.NGFWWizardManager = NGFWWizardManager;
