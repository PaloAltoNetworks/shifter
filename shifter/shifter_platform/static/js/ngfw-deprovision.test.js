/**
 * Mission Control NGFW deprovision page tests.
 *
 * Covers enabling the deprovision button when the confirmation name matches,
 * the guarded click handler, the destroy POST, and its success/server-error/
 * network-error branches. fetch and alert are mocked; the success-path
 * navigation (location.href assignment) is a jsdom no-op that the console.error
 * spy silences. The source self-runs initNgfwDeprovision() on require (readyState
 * is 'complete' under jsdom), so the DOM fixture is built before each require and
 * jest.resetModules() re-runs it per test.
 */

const NGFW_NAME = 'prod-fw-01';
const NGFW_ID = 'ngfw-42';
const LIST_URL = '/mission-control/ngfw/';

const buildMarkup = ({ button = true } = {}) => {
    if (!button) return '';
    return (
        '<input id="confirm-input" type="text">' +
        `<button id="deprovision-btn" disabled data-csrf-token="test-csrf"` +
        ` data-ngfw-id="${NGFW_ID}" data-ngfw-name="${NGFW_NAME}"` +
        ` data-list-url="${LIST_URL}">Deprovision NGFW</button>`
    );
};

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function load(opts) {
    document.body.innerHTML = buildMarkup(opts);
    require('./ngfw-deprovision.js');
}

describe('ngfw-deprovision', () => {
    let fetchMock;

    beforeEach(() => {
        jest.resetModules();
        jest.spyOn(console, 'error').mockImplementation(() => {});
        fetchMock = jest.fn();
        globalThis.fetch = fetchMock;
        globalThis.alert = jest.fn();
    });

    afterEach(() => {
        jest.restoreAllMocks();
        document.body.innerHTML = '';
    });

    test('no-ops when the confirm input and button are absent', () => {
        expect(() => load({ button: false })).not.toThrow();
    });

    test('enables the button only when the typed name matches', () => {
        load();
        const input = document.getElementById('confirm-input');
        const btn = document.getElementById('deprovision-btn');

        input.value = 'wrong-name';
        input.dispatchEvent(new Event('input'));
        expect(btn.disabled).toBe(true);

        input.value = `  ${NGFW_NAME}  `;
        input.dispatchEvent(new Event('input'));
        expect(btn.disabled).toBe(false);
    });

    test('click is a no-op when the confirmation text does not match', () => {
        load();
        const input = document.getElementById('confirm-input');
        const btn = document.getElementById('deprovision-btn');

        // Enable the button (matching value), then change the value without firing
        // another input event so the button stays enabled but the text no longer
        // matches when the guarded click handler re-checks it.
        input.value = NGFW_NAME;
        input.dispatchEvent(new Event('input'));
        input.value = 'not-the-name';
        btn.click();

        expect(fetchMock).not.toHaveBeenCalled();
    });

    test('POSTs the destroy request and navigates to the list on success', async () => {
        fetchMock.mockResolvedValue({ json: () => Promise.resolve({ status: 'ok' }) });
        load();
        const input = document.getElementById('confirm-input');
        const btn = document.getElementById('deprovision-btn');

        input.value = NGFW_NAME;
        input.dispatchEvent(new Event('input'));
        btn.click();

        expect(btn.disabled).toBe(true);
        expect(btn.textContent).toBe('Deprovisioning...');

        await flush();

        expect(fetchMock).toHaveBeenCalledWith(
            `/api/v1/mission-control/ngfw/${NGFW_ID}/destroy/`,
            expect.objectContaining({
                method: 'POST',
                headers: expect.objectContaining({
                    'Content-Type': 'application/json',
                    'X-CSRFToken': 'test-csrf',
                }),
                body: JSON.stringify({ confirm_name: NGFW_NAME }),
            }),
        );
        // Success path assigns location.href (a jsdom navigation no-op); no alert.
        expect(globalThis.alert).not.toHaveBeenCalled();
    });

    test('alerts the server error and re-enables the button', async () => {
        fetchMock.mockResolvedValue({
            json: () => Promise.resolve({ error: 'still has attachments' }),
        });
        load();
        const input = document.getElementById('confirm-input');
        const btn = document.getElementById('deprovision-btn');

        input.value = NGFW_NAME;
        input.dispatchEvent(new Event('input'));
        btn.click();
        await flush();

        expect(globalThis.alert).toHaveBeenCalledWith('still has attachments');
        expect(btn.disabled).toBe(false);
        expect(btn.textContent).toBe('Deprovision NGFW');
    });

    test('alerts a generic message and re-enables the button on network failure', async () => {
        fetchMock.mockRejectedValue(new Error('boom'));
        load();
        const input = document.getElementById('confirm-input');
        const btn = document.getElementById('deprovision-btn');

        input.value = NGFW_NAME;
        input.dispatchEvent(new Event('input'));
        btn.click();
        await flush();

        expect(globalThis.alert).toHaveBeenCalledWith('An error occurred. Please try again.');
        expect(btn.disabled).toBe(false);
        expect(btn.textContent).toBe('Deprovision NGFW');
    });

    test('registers a DOMContentLoaded handler while the document is still loading', () => {
        Object.defineProperty(document, 'readyState', {
            configurable: true,
            get: () => 'loading',
        });
        try {
            load();
            document.dispatchEvent(new Event('DOMContentLoaded'));

            const input = document.getElementById('confirm-input');
            const btn = document.getElementById('deprovision-btn');
            input.value = NGFW_NAME;
            input.dispatchEvent(new Event('input'));
            expect(btn.disabled).toBe(false);
        } finally {
            Object.defineProperty(document, 'readyState', {
                configurable: true,
                get: () => 'complete',
            });
        }
    });
});
