/**
 * Mission Control NGFW wizard bootstrap tests.
 *
 * Covers reading the CSRF token from the #ngfw-wizard-config json_script,
 * constructing NGFWWizardManager with the fixed provision/detail URLs, calling
 * init(), and wiring the debug helpers onto globalThis. NGFWWizardManager is
 * stubbed as a global constructor. The source registers a DOMContentLoaded
 * handler unconditionally, so the module is required once and DOMContentLoaded is
 * dispatched per test after building the fixture.
 */

require('./ngfw-wizard-init.js');

function setConfig(json) {
    document.body.innerHTML =
        `<script id="ngfw-wizard-config" type="application/json">${json}</script>`;
}

describe('ngfw-wizard-init', () => {
    let wizardInstance;

    beforeEach(() => {
        wizardInstance = {
            init: jest.fn(),
            debugShowSuccess: jest.fn(),
            debugGoToStep: jest.fn(),
        };
        globalThis.NGFWWizardManager = jest.fn(() => wizardInstance);
    });

    afterEach(() => {
        delete globalThis.NGFWWizardManager;
        delete globalThis.debugShowSuccess;
        delete globalThis.debugGoToStep;
        document.body.innerHTML = '';
    });

    test('constructs the wizard with the config token and fixed URLs, then inits', () => {
        setConfig('{"csrfToken": "csrf-xyz"}');
        document.dispatchEvent(new Event('DOMContentLoaded'));

        expect(globalThis.NGFWWizardManager).toHaveBeenCalledWith({
            csrfToken: 'csrf-xyz',
            provisionUrl: '/api/v1/mission-control/ngfw/',
            detailUrlTemplate: '/mission-control/ngfw/{id}/',
        });
        expect(wizardInstance.init).toHaveBeenCalled();
    });

    test('falls back to an empty config when the json_script is absent', () => {
        document.body.innerHTML = '';
        document.dispatchEvent(new Event('DOMContentLoaded'));

        expect(globalThis.NGFWWizardManager).toHaveBeenCalledWith(
            expect.objectContaining({ csrfToken: undefined }),
        );
        expect(wizardInstance.init).toHaveBeenCalled();
    });

    test('exposes debug helpers that delegate to the wizard instance', () => {
        setConfig('{"csrfToken": "csrf-xyz"}');
        document.dispatchEvent(new Event('DOMContentLoaded'));

        globalThis.debugShowSuccess();
        expect(wizardInstance.debugShowSuccess).toHaveBeenCalled();

        globalThis.debugGoToStep(4);
        expect(wizardInstance.debugGoToStep).toHaveBeenCalledWith(4);
    });
});
