require('./ngfw.js');

describe('NGFWWizardManager', () => {
    let wizard;

    const buildWizardMarkup = () => `
        <div class="wizard-step"></div>
        <div class="wizard-step"></div>
        <div class="wizard-step"></div>
        <div class="wizard-panel" id="step-1"></div>
        <div class="wizard-panel" id="step-2"></div>
        <div class="wizard-panel" id="step-3"></div>
        <div class="wizard-panel" id="step-4"></div>
        <input id="ngfw-name" type="text">
        <div class="radio-option" data-method="otp"><input type="radio" name="registration_method" value="otp"></div>
        <div class="radio-option" data-method="pin"><input type="radio" name="registration_method" value="pin"></div>
        <input id="otp-value" type="text">
        <input id="otp-folder" type="text">
        <div id="otp-fields"></div>
        <div id="pin-fields"></div>
        <div id="profile-dropdown">
            <button class="xdr-dropdown-trigger"><span class="xdr-dropdown-value placeholder">Select</span></button>
            <div class="xdr-dropdown-panel">
                <div class="xdr-dropdown-item" data-value="1" data-name="Profile 1"><span class="item-label">Profile 1</span></div>
            </div>
            <input type="hidden">
        </div>
        <div id="scm-dropdown">
            <button class="xdr-dropdown-trigger"><span class="xdr-dropdown-value placeholder">Select</span></button>
            <div class="xdr-dropdown-panel">
                <div class="xdr-dropdown-item" data-value="1" data-name="Cred 1" data-region="americas"><span class="item-label">Cred 1</span></div>
            </div>
            <input type="hidden">
        </div>
        <div id="region-dropdown">
            <button class="xdr-dropdown-trigger"><span class="xdr-dropdown-value placeholder">Select</span></button>
            <div class="xdr-dropdown-panel">
                <div class="xdr-dropdown-item" data-value="americas"><span class="item-label">Americas</span></div>
            </div>
            <input type="hidden">
        </div>
        <span id="summary-name"></span>
        <span id="summary-profile"></span>
        <span id="summary-method"></span>
        <span id="summary-credential"></span>
        <span id="summary-folder"></span>
        <span id="summary-region"></span>
        <div id="summary-credential-row"></div>
        <div id="summary-folder-row"></div>
        <div id="provisioning-progress"></div>
        <div id="success-state" style="display: none;"></div>
        <a id="view-ngfw-btn" href="#"></a>
        <button id="step1-next"></button>
        <button id="step2-back"></button>
        <button id="step2-next"></button>
        <button id="step3-back"></button>
        <button id="step3-provision"></button>
    `;

    beforeEach(() => {
        document.body.innerHTML = buildWizardMarkup();
        global.alert = jest.fn();
        global.fetch = jest.fn();


        wizard = new window.NGFWWizardManager({
            csrfToken: 'test-csrf',
            provisionUrl: '/api/ngfw/provision/',
            statusUrlTemplate: '/api/ngfw/{id}/status/',
            detailUrlTemplate: '/ngfw/{id}/',
        });
        wizard.init();
    });

    afterEach(() => {
        jest.clearAllMocks();
    });

    describe('constructor', () => {
        test('initializes with default form data', () => {
            expect(wizard.formData.name).toBe('');
            expect(wizard.formData.deployment_profile_id).toBeNull();
            expect(wizard.formData.registration_method).toBe('pin');
            expect(wizard.formData.sls_region).toBe('americas');
        });

        test('initializes at step 1', () => {
            expect(wizard.currentStep).toBe(1);
        });
    });

    describe('validateStep1', () => {
        test('returns false without name', () => {
            wizard.formData.name = '';
            wizard.formData.deployment_profile_id = '1';

            expect(wizard.validateStep1()).toBe(false);
        });

        test('returns false without deployment profile', () => {
            wizard.formData.name = 'My NGFW';
            wizard.formData.deployment_profile_id = null;

            expect(wizard.validateStep1()).toBe(false);
        });

        test('returns true with valid data', () => {
            wizard.formData.name = 'My NGFW';
            wizard.formData.deployment_profile_id = '1';

            expect(wizard.validateStep1()).toBe(true);
        });

        test('enables next button when valid', () => {
            wizard.formData.name = 'My NGFW';
            wizard.formData.deployment_profile_id = '1';

            wizard.validateStep1();

            expect(document.getElementById('step1-next').disabled).toBe(false);
        });

        test('disables next button when invalid', () => {
            wizard.formData.name = '';
            wizard.formData.deployment_profile_id = null;

            wizard.validateStep1();

            expect(document.getElementById('step1-next').disabled).toBe(true);
        });
    });

    describe('validateStep2', () => {
        test('OTP method returns false without OTP value', () => {
            wizard.formData.registration_method = 'otp';
            wizard.formData.otp_value = '';
            wizard.formData.otp_folder = 'My Folder';

            expect(wizard.validateStep2()).toBe(false);
        });

        test('OTP method returns false without folder', () => {
            wizard.formData.registration_method = 'otp';
            wizard.formData.otp_value = 'ABC123';
            wizard.formData.otp_folder = '';

            expect(wizard.validateStep2()).toBe(false);
        });

        test('OTP method returns true with valid data', () => {
            wizard.formData.registration_method = 'otp';
            wizard.formData.otp_value = 'ABC123';
            wizard.formData.otp_folder = 'My Folder';

            expect(wizard.validateStep2()).toBe(true);
        });

        test('PIN method returns false without credential', () => {
            wizard.formData.registration_method = 'pin';
            wizard.formData.scm_credential_id = null;

            expect(wizard.validateStep2()).toBe(false);
        });

        test('PIN method returns true with credential', () => {
            wizard.formData.registration_method = 'pin';
            wizard.formData.scm_credential_id = '1';

            expect(wizard.validateStep2()).toBe(true);
        });
    });

    describe('goToStep', () => {
        test('updates currentStep', () => {
            wizard.goToStep(2);
            expect(wizard.currentStep).toBe(2);
        });

        test('activates correct panel', () => {
            wizard.goToStep(2);

            expect(document.getElementById('step-2').classList.contains('active')).toBe(true);
            expect(document.getElementById('step-1').classList.contains('active')).toBe(false);
        });
    });

    describe('updateSummary', () => {
        test('displays OTP summary correctly', () => {
            wizard.formData.name = 'Test NGFW';
            wizard.formData.deployment_profile_name = 'Test Profile';
            wizard.formData.registration_method = 'otp';
            wizard.formData.otp_folder = 'My Folder';
            wizard.formData.sls_region = 'americas';

            wizard.updateSummary();

            expect(document.getElementById('summary-name').textContent).toBe('Test NGFW');
            expect(document.getElementById('summary-profile').textContent).toBe('Test Profile');
            expect(document.getElementById('summary-method').textContent).toBe('One-Time Password');
            expect(document.getElementById('summary-folder').textContent).toBe('My Folder');
            expect(document.getElementById('summary-region').textContent).toBe('Americas');
        });

        test('displays PIN summary correctly', () => {
            wizard.formData.name = 'Test NGFW';
            wizard.formData.deployment_profile_name = 'Test Profile';
            wizard.formData.registration_method = 'pin';
            wizard.formData.scm_credential_name = 'My SCM Cred';
            wizard.formData.sls_region = 'europe';

            wizard.updateSummary();

            expect(document.getElementById('summary-method').textContent).toBe('Stored PIN');
            expect(document.getElementById('summary-credential').textContent).toBe('My SCM Cred');
            expect(document.getElementById('summary-region').textContent).toBe('Europe');
        });

        test('shows credential row for PIN method', () => {
            wizard.formData.registration_method = 'pin';
            wizard.updateSummary();

            expect(document.getElementById('summary-credential-row').style.display).toBe('');
            expect(document.getElementById('summary-folder-row').style.display).toBe('none');
        });

        test('shows folder row for OTP method', () => {
            wizard.formData.registration_method = 'otp';
            wizard.updateSummary();

            expect(document.getElementById('summary-credential-row').style.display).toBe('none');
            expect(document.getElementById('summary-folder-row').style.display).toBe('');
        });
    });

    describe('WebSocket', () => {
        let mockWebSocket;

        beforeEach(() => {
            mockWebSocket = {
                send: jest.fn(),
                close: jest.fn(),
                onopen: null,
                onmessage: null,
                onclose: null,
                onerror: null,
            };
            global.WebSocket = jest.fn(() => mockWebSocket);
        });

        test('connectWebSocket creates WebSocket with correct URL', () => {
            wizard.ngfwId = 42;
            wizard.connectWebSocket();

            expect(global.WebSocket).toHaveBeenCalledWith('ws://localhost/ws/ngfw-status/42/');
        });

        test('WebSocket onmessage shows success on ready status', () => {
            wizard.ngfwId = 42;
            wizard.connectWebSocket();

            // Simulate ready message
            mockWebSocket.onmessage({ data: JSON.stringify({ status: 'ready' }) });

            expect(document.getElementById('success-state').style.display).toBe('block');
            expect(document.getElementById('provisioning-progress').style.display).toBe('none');
            expect(mockWebSocket.close).toHaveBeenCalled();
        });

        test('WebSocket onmessage shows success on ready status', () => {
            wizard.ngfwId = 42;
            wizard.connectWebSocket();

            mockWebSocket.onmessage({ data: JSON.stringify({ status: 'ready' }) });

            expect(document.getElementById('success-state').style.display).toBe('block');
        });

        test('WebSocket onmessage alerts on failed status', () => {
            wizard.ngfwId = 42;
            wizard.connectWebSocket();

            // Suppress JSDOM navigation error
            const originalError = console.error;
            console.error = jest.fn();

            mockWebSocket.onmessage({ data: JSON.stringify({ status: 'failed', error: 'Test error' }) });

            expect(global.alert).toHaveBeenCalledWith('Provisioning failed: Test error');

            console.error = originalError;
        });
    });

    describe('showSuccess', () => {
        test('hides progress and shows success state', () => {
            wizard.showSuccess();

            expect(document.getElementById('provisioning-progress').style.display).toBe('none');
            expect(document.getElementById('success-state').style.display).toBe('block');
        });
    });
});
