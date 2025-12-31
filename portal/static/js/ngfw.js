/**
 * NGFW Wizard Manager
 *
 * Handles the multi-step wizard for NGFW provisioning.
 * Supports WebSocket for real-time provisioning status updates.
 */
class NGFWWizardManager {
    constructor(options) {
        this.csrfToken = options.csrfToken;
        this.provisionUrl = options.provisionUrl;
        this.statusWsUrl = options.statusWsUrl;

        this.currentStep = 1;
        this.formData = {
            name: '',
            deploymentProfileId: null,
            deploymentProfileName: '',
            scmCredentialId: null,
            scmCredentialName: '',
            registrationMethod: 'otp',
            otpValue: '',
            otpFolder: '',
            slsRegion: 'americas',
        };

        this.ws = null;
        this.ngfwId = null;
    }

    init() {
        this.bindEvents();
        this.initDropdowns();
    }

    bindEvents() {
        // Step navigation
        document.getElementById('step-1-next')?.addEventListener('click', () => this.goToStep(2));
        document.getElementById('step-2-back')?.addEventListener('click', () => this.goToStep(1));
        document.getElementById('step-2-next')?.addEventListener('click', () => this.goToStep(3));
        document.getElementById('step-3-back')?.addEventListener('click', () => this.goToStep(2));
        document.getElementById('step-3-provision')?.addEventListener('click', () => this.startProvisioning());

        // Form inputs
        document.getElementById('ngfw-name')?.addEventListener('input', (e) => {
            this.formData.name = e.target.value;
        });

        // Registration method toggle
        document.querySelectorAll('input[name="registration_method"]').forEach(radio => {
            radio.addEventListener('change', (e) => {
                this.formData.registrationMethod = e.target.value;
                this.toggleOtpFields();
            });
        });

        // OTP fields
        document.getElementById('otp-value')?.addEventListener('input', (e) => {
            this.formData.otpValue = e.target.value;
        });
        document.getElementById('otp-folder')?.addEventListener('input', (e) => {
            this.formData.otpFolder = e.target.value;
        });
        document.getElementById('otp-sls-region')?.addEventListener('change', (e) => {
            this.formData.slsRegion = e.target.value;
        });
    }

    initDropdowns() {
        // Deployment Profile dropdown
        this.initDropdown('deployment-profile', (value, label) => {
            this.formData.deploymentProfileId = value;
            this.formData.deploymentProfileName = label;
        });

        // SCM Credential dropdown
        this.initDropdown('scm-credential', (value, label) => {
            this.formData.scmCredentialId = value;
            this.formData.scmCredentialName = label;
            this.updateRegistrationOptions();
        });
    }

    initDropdown(prefix, onChange) {
        const dropdown = document.getElementById(`${prefix}-dropdown`);
        if (!dropdown) return;

        const trigger = dropdown.querySelector('.xdr-dropdown-trigger');
        const panel = dropdown.querySelector('.xdr-dropdown-panel');
        const items = dropdown.querySelectorAll('.xdr-dropdown-item');
        const valueInput = document.getElementById(`${prefix}-value`);
        const valueDisplay = trigger.querySelector('.xdr-dropdown-value');

        trigger.addEventListener('click', () => {
            panel.classList.toggle('open');
        });

        items.forEach(item => {
            item.addEventListener('click', () => {
                const value = item.dataset.value;
                const label = item.querySelector('.item-label').textContent;

                valueInput.value = value;
                valueDisplay.textContent = label;
                valueDisplay.classList.remove('placeholder');

                items.forEach(i => i.classList.remove('selected'));
                item.classList.add('selected');

                panel.classList.remove('open');
                onChange(value, label);
            });
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target)) {
                panel.classList.remove('open');
            }
        });
    }

    updateRegistrationOptions() {
        const pinOption = document.getElementById('pin-option');
        const otpRadio = document.getElementById('otp-radio');

        if (this.formData.scmCredentialId) {
            pinOption.style.display = 'block';
            this.formData.registrationMethod = 'pin';
            document.querySelector('input[value="pin"]').checked = true;
        } else {
            pinOption.style.display = 'none';
            this.formData.registrationMethod = 'otp';
            otpRadio.checked = true;
        }
        this.toggleOtpFields();
    }

    toggleOtpFields() {
        const otpFields = document.getElementById('otp-fields');
        if (this.formData.registrationMethod === 'otp') {
            otpFields.style.display = 'block';
        } else {
            otpFields.style.display = 'none';
        }
    }

    goToStep(step) {
        // Validate current step before proceeding
        if (step > this.currentStep && !this.validateStep(this.currentStep)) {
            return;
        }

        // Update step indicators
        document.querySelectorAll('.wizard-step').forEach((el, idx) => {
            const stepNum = idx + 1;
            el.classList.remove('active', 'complete');
            if (stepNum < step) {
                el.classList.add('complete');
            } else if (stepNum === step) {
                el.classList.add('active');
            }
        });

        // Show/hide panels
        document.querySelectorAll('.wizard-panel').forEach(panel => {
            panel.style.display = 'none';
        });
        document.getElementById(`step-${step}`).style.display = 'block';

        // Update confirmation summary for step 3
        if (step === 3) {
            this.updateConfirmation();
        }

        this.currentStep = step;
    }

    validateStep(step) {
        if (step === 1) {
            if (!this.formData.name.trim()) {
                alert('Please enter an NGFW name');
                return false;
            }
            if (!this.formData.deploymentProfileId) {
                alert('Please select a deployment profile');
                return false;
            }
            return true;
        }
        if (step === 2) {
            if (this.formData.registrationMethod === 'otp') {
                if (!this.formData.otpValue.trim()) {
                    alert('Please enter the OTP value');
                    return false;
                }
                if (!this.formData.otpFolder.trim()) {
                    alert('Please enter the SCM folder name');
                    return false;
                }
            }
            return true;
        }
        return true;
    }

    updateConfirmation() {
        document.getElementById('confirm-name').textContent = this.formData.name;
        document.getElementById('confirm-profile').textContent = this.formData.deploymentProfileName;
        document.getElementById('confirm-registration').textContent =
            this.formData.registrationMethod === 'pin' ? 'Auto-Registration PIN' : 'One-Time Password';
        document.getElementById('confirm-folder').textContent =
            this.formData.registrationMethod === 'pin'
                ? this.formData.scmCredentialName
                : this.formData.otpFolder;
        document.getElementById('confirm-sls').textContent =
            this.formData.slsRegion.charAt(0).toUpperCase() + this.formData.slsRegion.slice(1);
    }

    async startProvisioning() {
        this.goToStep(4);

        // TODO: Replace with actual API call when backend is ready
        // For now, simulate provisioning progress
        this.simulateProvisioning();
    }

    simulateProvisioning() {
        const steps = ['pstep-ec2', 'pstep-ssh', 'pstep-license', 'pstep-cert', 'pstep-xdr', 'pstep-gwlb'];
        const statusMessages = [
            'Launching EC2 instance...',
            'Waiting for SSH to become available...',
            'Activating license...',
            'Obtaining device certificate...',
            'Configuring XDR integration...',
            'Setting up Gateway Load Balancer...',
        ];

        let currentIdx = 0;
        const progressFill = document.getElementById('progress-fill');
        const progressStatus = document.getElementById('progress-status');

        const interval = setInterval(() => {
            if (currentIdx > 0) {
                document.getElementById(steps[currentIdx - 1]).classList.remove('active');
                document.getElementById(steps[currentIdx - 1]).classList.add('complete');
            }

            if (currentIdx >= steps.length) {
                clearInterval(interval);
                this.onProvisioningComplete();
                return;
            }

            document.getElementById(steps[currentIdx]).classList.add('active');
            progressStatus.textContent = statusMessages[currentIdx];
            progressFill.style.width = `${((currentIdx + 1) / steps.length) * 100}%`;

            currentIdx++;
        }, 2000); // Simulate 2 seconds per step
    }

    onProvisioningComplete() {
        // Simulated serial number - will be returned by actual API
        const serialNumber = '0012345' + Math.floor(Math.random() * 100000);

        document.getElementById('ngfw-serial').textContent = serialNumber;
        document.getElementById('serial-in-steps').textContent = serialNumber;

        // Update view button URL (will be actual NGFW ID from API response)
        const viewBtn = document.getElementById('view-ngfw-btn');
        viewBtn.href = this.provisionUrl; // Placeholder

        this.goToStep(5);
    }

    // WebSocket methods for real-time status updates
    connectWebSocket(ngfwId) {
        this.ngfwId = ngfwId;
        this.ws = new WebSocket(this.statusWsUrl);

        this.ws.onopen = () => {
            console.log('NGFW status WebSocket connected');
            this.ws.send(JSON.stringify({ type: 'subscribe', ngfw_id: ngfwId }));
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleStatusUpdate(data);
        };

        this.ws.onclose = () => {
            console.log('NGFW status WebSocket closed');
        };

        this.ws.onerror = (error) => {
            console.error('NGFW status WebSocket error:', error);
        };
    }

    handleStatusUpdate(data) {
        // Update progress based on status updates from backend
        const { step, status, progress, serial_number } = data;

        if (progress) {
            document.getElementById('progress-fill').style.width = `${progress}%`;
        }

        if (status) {
            document.getElementById('progress-status').textContent = status;
        }

        if (serial_number) {
            document.getElementById('ngfw-serial').textContent = serial_number;
            document.getElementById('serial-in-steps').textContent = serial_number;
        }

        if (step === 'complete') {
            this.goToStep(5);
            this.ws?.close();
        }
    }

    disconnectWebSocket() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }
}

// Export for use in templates
window.NGFWWizardManager = NGFWWizardManager;
