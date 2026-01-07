require('./ngfw.js');

describe('NGFWWizardManager', () => {
    let wizard;

    const buildWizardMarkup = () => `
        <div class="wizard-step" id="step-1"></div>
        <div class="wizard-step" id="step-2"></div>
        <div class="wizard-step" id="step-3"></div>
        <div class="wizard-panel" id="step-1"></div>
        <div class="wizard-panel" id="step-2"></div>
        <div class="wizard-panel" id="step-3"></div>
        <div class="wizard-panel" id="step-4"></div>
        <div class="wizard-panel" id="step-5"></div>
        <input id="ngfw-name" type="text">
        <input type="radio" name="registration_method" value="otp">
        <input type="radio" name="registration_method" value="pin">
        <input id="otp-value" type="text">
        <input id="otp-folder" type="text">
        <select id="otp-sls-region"><option value="americas">Americas</option></select>
        <div id="otp-fields"></div>
        <div id="pin-option"></div>
        <div id="deployment-profile-dropdown">
            <button class="xdr-dropdown-trigger"><span class="xdr-dropdown-value placeholder">Select</span></button>
            <div class="xdr-dropdown-panel">
                <div class="xdr-dropdown-item" data-value="1"><span class="item-label">Profile 1</span></div>
            </div>
        </div>
        <input id="deployment-profile-value" type="hidden">
        <div id="scm-credential-dropdown">
            <button class="xdr-dropdown-trigger"><span class="xdr-dropdown-value placeholder">Select</span></button>
            <div class="xdr-dropdown-panel">
                <div class="xdr-dropdown-item" data-value="1"><span class="item-label">Cred 1</span></div>
            </div>
        </div>
        <input id="scm-credential-value" type="hidden">
        <span id="confirm-name"></span>
        <span id="confirm-profile"></span>
        <span id="confirm-registration"></span>
        <span id="confirm-folder"></span>
        <span id="confirm-sls"></span>
        <span id="ngfw-serial"></span>
        <span id="serial-in-steps"></span>
        <div id="progress-fill"></div>
        <div id="progress-status"></div>
        <div id="pstep-ec2"></div>
        <div id="pstep-ssh"></div>
        <div id="pstep-license"></div>
        <div id="pstep-cert"></div>
        <div id="pstep-xdr"></div>
        <div id="pstep-gwlb"></div>
        <a id="view-ngfw-btn" href="#"></a>
    `;

    beforeEach(() => {
        document.body.innerHTML = buildWizardMarkup();
        global.alert = jest.fn();

        wizard = new window.NGFWWizardManager({
            csrfToken: 'test-csrf',
            provisionUrl: '/ngfw/1/',
            statusWsUrl: 'ws://localhost/ws/ngfw/',
        });
    });

    afterEach(() => {
        jest.clearAllMocks();
    });

    describe('validateStep', () => {
        test('step 1 fails without name', () => {
            wizard.formData.name = '';
            wizard.formData.deploymentProfileId = '1';

            expect(wizard.validateStep(1)).toBe(false);
            expect(global.alert).toHaveBeenCalledWith('Please enter an NGFW name');
        });

        test('step 1 fails without deployment profile', () => {
            wizard.formData.name = 'My NGFW';
            wizard.formData.deploymentProfileId = null;

            expect(wizard.validateStep(1)).toBe(false);
            expect(global.alert).toHaveBeenCalledWith('Please select a deployment profile');
        });

        test('step 1 passes with valid data', () => {
            wizard.formData.name = 'My NGFW';
            wizard.formData.deploymentProfileId = '1';

            expect(wizard.validateStep(1)).toBe(true);
            expect(global.alert).not.toHaveBeenCalled();
        });

        test('step 2 OTP fails without OTP value', () => {
            wizard.formData.registrationMethod = 'otp';
            wizard.formData.otpValue = '';
            wizard.formData.otpFolder = 'My Folder';

            expect(wizard.validateStep(2)).toBe(false);
            expect(global.alert).toHaveBeenCalledWith('Please enter the OTP value');
        });

        test('step 2 OTP fails without folder', () => {
            wizard.formData.registrationMethod = 'otp';
            wizard.formData.otpValue = 'ABC123';
            wizard.formData.otpFolder = '';

            expect(wizard.validateStep(2)).toBe(false);
            expect(global.alert).toHaveBeenCalledWith('Please enter the SCM folder name');
        });

        test('step 2 OTP passes with valid data', () => {
            wizard.formData.registrationMethod = 'otp';
            wizard.formData.otpValue = 'ABC123';
            wizard.formData.otpFolder = 'My Folder';

            expect(wizard.validateStep(2)).toBe(true);
        });

        test('step 2 PIN always passes', () => {
            wizard.formData.registrationMethod = 'pin';

            expect(wizard.validateStep(2)).toBe(true);
        });

        test('step 3 always passes', () => {
            expect(wizard.validateStep(3)).toBe(true);
        });
    });

    describe('toggleOtpFields', () => {
        test('shows OTP fields when method is otp', () => {
            wizard.formData.registrationMethod = 'otp';
            wizard.toggleOtpFields();

            expect(document.getElementById('otp-fields').style.display).toBe('block');
        });

        test('hides OTP fields when method is pin', () => {
            wizard.formData.registrationMethod = 'pin';
            wizard.toggleOtpFields();

            expect(document.getElementById('otp-fields').style.display).toBe('none');
        });
    });

    describe('updateConfirmation', () => {
        test('displays OTP confirmation correctly', () => {
            wizard.formData.name = 'Test NGFW';
            wizard.formData.deploymentProfileName = 'Test Profile';
            wizard.formData.registrationMethod = 'otp';
            wizard.formData.otpFolder = 'My Folder';
            wizard.formData.slsRegion = 'americas';

            wizard.updateConfirmation();

            expect(document.getElementById('confirm-name').textContent).toBe('Test NGFW');
            expect(document.getElementById('confirm-profile').textContent).toBe('Test Profile');
            expect(document.getElementById('confirm-registration').textContent).toBe('One-Time Password');
            expect(document.getElementById('confirm-folder').textContent).toBe('My Folder');
            expect(document.getElementById('confirm-sls').textContent).toBe('Americas');
        });

        test('displays PIN confirmation correctly', () => {
            wizard.formData.name = 'Test NGFW';
            wizard.formData.deploymentProfileName = 'Test Profile';
            wizard.formData.registrationMethod = 'pin';
            wizard.formData.scmCredentialName = 'My SCM Cred';
            wizard.formData.slsRegion = 'europe';

            wizard.updateConfirmation();

            expect(document.getElementById('confirm-registration').textContent).toBe('Auto-Registration PIN');
            expect(document.getElementById('confirm-folder').textContent).toBe('My SCM Cred');
            expect(document.getElementById('confirm-sls').textContent).toBe('Europe');
        });
    });

    describe('WebSocket methods', () => {
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
            wizard.connectWebSocket(42);

            expect(global.WebSocket).toHaveBeenCalledWith('ws://localhost/ws/ngfw/');
            expect(wizard.ngfwId).toBe(42);
        });

        test('handleStatusUpdate updates progress bar', () => {
            wizard.handleStatusUpdate({ progress: 50 });

            expect(document.getElementById('progress-fill').style.width).toBe('50%');
        });

        test('handleStatusUpdate updates status text', () => {
            wizard.handleStatusUpdate({ status: 'Creating EC2...' });

            expect(document.getElementById('progress-status').textContent).toBe('Creating EC2...');
        });

        test('handleStatusUpdate updates serial number', () => {
            wizard.handleStatusUpdate({ serial_number: '007958001234' });

            expect(document.getElementById('ngfw-serial').textContent).toBe('007958001234');
            expect(document.getElementById('serial-in-steps').textContent).toBe('007958001234');
        });

        test('handleStatusUpdate closes WebSocket on complete', () => {
            wizard.ws = mockWebSocket;
            wizard.handleStatusUpdate({ step: 'complete' });

            expect(mockWebSocket.close).toHaveBeenCalled();
        });

        test('disconnectWebSocket closes and nulls connection', () => {
            wizard.ws = mockWebSocket;
            wizard.disconnectWebSocket();

            expect(mockWebSocket.close).toHaveBeenCalled();
            expect(wizard.ws).toBeNull();
        });
    });
});
