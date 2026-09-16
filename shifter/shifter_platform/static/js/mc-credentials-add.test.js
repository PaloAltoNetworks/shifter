// Tests for mc-credentials-add.js — the Mission Control add-credential form:
// type-driven field visibility, live validation, credential creation, and the
// togglePassword helper.
//
// The module wires everything up on DOMContentLoaded: it reads config from a
// #mc-credentials-add-config json_script, initialises two ShifterDropdown
// widgets, and binds change/input/submit handlers. Each scenario builds a fresh
// DOM fixture, mocks globalThis.ShifterDropdown, then requires the module and
// dispatches DOMContentLoaded.

const CONFIG = {
    csrfToken: 'tok-1',
    createUrl: '/api/v1/mission-control/credentials/create/',
    listUrl: '/mission-control/credentials/',
};

function fixture(config) {
    const configScript =
        config === null
            ? ''
            : `<script id="mc-credentials-add-config" type="application/json">${JSON.stringify(
                  config
              )}</script>`;
    return `
        ${configScript}
        <div id="type-dropdown"></div>
        <div id="region-dropdown"></div>
        <input type="hidden" id="region-select-value" value="">
        <div id="common-fields"></div>
        <div id="scm-fields"></div>
        <div id="profile-fields"></div>
        <div id="optional-fields"></div>
        <div id="info-scm"></div>
        <div id="info-profile"></div>
        <button id="submit-btn" disabled>Create</button>
        <form id="credentialForm">
            <input id="name" value="">
            <input id="scm_folder_name" value="">
            <input id="scm_pin_id" value="">
            <input type="password" id="scm_pin_value" value="">
            <input id="authcode" value="">
            <input id="expires_at" value="">
        </form>
    `;
}

function loadModule(config = CONFIG) {
    jest.resetModules();
    document.body.innerHTML = fixture(config);
    globalThis.ShifterDropdown = { init: jest.fn() };
    require('./mc-credentials-add.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
}

function selectType(value) {
    document
        .getElementById('type-dropdown')
        .dispatchEvent(new CustomEvent('change', { detail: { value } }));
}

function setInput(id, value) {
    const el = document.getElementById(id);
    el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('mc-credentials-add', () => {
    let fetchMock;
    let alertMock;
    let errSpy;

    beforeEach(() => {
        fetchMock = jest.fn();
        globalThis.fetch = fetchMock;
        alertMock = jest.fn();
        globalThis.alert = alertMock;
        // location.href assignment triggers a jsdom navigation notice.
        errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    });

    afterEach(() => {
        jest.restoreAllMocks();
    });

    test('initialises both dropdowns and tolerates a missing config element', () => {
        loadModule(null);
        expect(globalThis.ShifterDropdown.init).toHaveBeenCalledTimes(2);
    });

    describe('type-driven field visibility', () => {
        test('selecting SCM reveals SCM fields and callout and sets the placeholder', () => {
            loadModule();

            selectType('scm');

            expect(document.getElementById('info-scm').classList.contains('active')).toBe(true);
            expect(document.getElementById('info-profile').classList.contains('active')).toBe(false);
            expect(document.getElementById('common-fields').classList.contains('active')).toBe(true);
            expect(document.getElementById('optional-fields').classList.contains('active')).toBe(true);
            expect(document.getElementById('scm-fields').classList.contains('active')).toBe(true);
            expect(document.getElementById('profile-fields').classList.contains('active')).toBe(false);
            expect(document.getElementById('name').placeholder).toBe('e.g., Production SCM Registration');
        });

        test('selecting deployment profile reveals profile fields and its placeholder', () => {
            loadModule();

            selectType('deployment_profile');

            expect(document.getElementById('info-profile').classList.contains('active')).toBe(true);
            expect(document.getElementById('profile-fields').classList.contains('active')).toBe(true);
            expect(document.getElementById('scm-fields').classList.contains('active')).toBe(false);
            expect(document.getElementById('name').placeholder).toBe('e.g., Production VM-Series License');
        });
    });

    describe('validateForm', () => {
        test('keeps submit disabled until an SCM form is fully filled', () => {
            loadModule();
            const submitBtn = document.getElementById('submit-btn');

            // No type chosen yet.
            setInput('name', 'My Cred');
            expect(submitBtn.disabled).toBe(true);

            selectType('scm');
            // Type chosen but name still blank in validateForm's re-read? name is set.
            // Now clear name to exercise the empty-name branch.
            setInput('name', '');
            expect(submitBtn.disabled).toBe(true);

            setInput('name', 'My Cred');
            // SCM requires pin id, pin value, and a region.
            expect(submitBtn.disabled).toBe(true);

            setInput('scm_pin_id', 'pin-1');
            setInput('scm_pin_value', 'secret');
            expect(submitBtn.disabled).toBe(true); // region still empty

            document.getElementById('region-select-value').value = 'us-east-2';
            document
                .getElementById('region-dropdown')
                .dispatchEvent(new CustomEvent('change', { detail: { value: 'us-east-2' } }));
            expect(submitBtn.disabled).toBe(false);
        });

        test('enables submit for a deployment profile once name and authcode are set', () => {
            loadModule();
            const submitBtn = document.getElementById('submit-btn');

            selectType('deployment_profile');
            setInput('name', 'Prod License');
            expect(submitBtn.disabled).toBe(true);

            setInput('authcode', 'AUTH-123');
            expect(submitBtn.disabled).toBe(false);
        });
    });

    describe('form submission', () => {
        test('POSTs the SCM payload and redirects on success', async () => {
            loadModule();
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({ id: 5 }) });

            selectType('scm');
            setInput('name', 'My Cred');
            setInput('scm_folder_name', 'folder');
            setInput('scm_pin_id', 'pin-1');
            setInput('scm_pin_value', 'secret');
            document.getElementById('region-select-value').value = 'us-east-2';
            setInput('expires_at', '2027-01-01');

            document
                .getElementById('credentialForm')
                .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
            await flush();
            await flush();

            const [url, opts] = fetchMock.mock.calls[0];
            expect(url).toBe(CONFIG.createUrl);
            expect(opts.method).toBe('POST');
            expect(opts.headers['X-CSRFToken']).toBe('tok-1');
            const body = JSON.parse(opts.body);
            expect(body).toEqual({
                name: 'My Cred',
                credential_type: 'scm',
                expires_at: '2027-01-01',
                scm_folder_name: 'folder',
                scm_pin_id: 'pin-1',
                scm_pin_value: 'secret',
                sls_region: 'us-east-2',
            });
            expect(alertMock).not.toHaveBeenCalled();
        });

        test('POSTs the deployment-profile payload with a null expiry', async () => {
            loadModule();
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({ id: 7 }) });

            selectType('deployment_profile');
            setInput('name', 'Prod License');
            setInput('authcode', 'AUTH-123');

            document
                .getElementById('credentialForm')
                .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
            await flush();
            await flush();

            const body = JSON.parse(fetchMock.mock.calls[0][1].body);
            expect(body).toEqual({
                name: 'Prod License',
                credential_type: 'deployment_profile',
                expires_at: null,
                authcode: 'AUTH-123',
            });
        });

        test('alerts the server-provided error and does not redirect', async () => {
            loadModule();
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({ error: 'duplicate name' }) });

            selectType('deployment_profile');
            setInput('name', 'Prod License');
            setInput('authcode', 'AUTH-123');

            document
                .getElementById('credentialForm')
                .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
            await flush();
            await flush();

            expect(alertMock).toHaveBeenCalledWith('duplicate name');
        });

        test('alerts a generic message when the create fetch rejects', async () => {
            loadModule();
            fetchMock.mockRejectedValue(new Error('network down'));

            selectType('deployment_profile');
            setInput('name', 'Prod License');
            setInput('authcode', 'AUTH-123');

            document
                .getElementById('credentialForm')
                .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
            await flush();
            await flush();

            expect(alertMock).toHaveBeenCalledWith('An error occurred. Please try again.');
        });
    });

    describe('togglePassword', () => {
        test('flips the input type between password and text', () => {
            loadModule();
            const input = document.getElementById('scm_pin_value');
            expect(input.type).toBe('password');

            globalThis.togglePassword('scm_pin_value');
            expect(input.type).toBe('text');

            globalThis.togglePassword('scm_pin_value');
            expect(input.type).toBe('password');
        });
    });
});
