/**
 * @jest-environment jsdom
 * @jest-environment-options {"url": "https://example.com/ctf/register/"}
 */

// Tests for the CTF magic-link token-exchange page script.
//
// ctf-register.js is an IIFE that runs on require: it reads the token from the
// URL fragment, scrubs it from history, and POSTs it to the CSRF-protected
// exchange endpoint. Each test sets up the DOM, location hash, and fetch BEFORE
// requiring the module fresh. jsdom's window.location (and its replace method)
// cannot be redefined, so we mutate location.hash directly; on the success path
// the real location.replace runs (jsdom logs an unimplemented-navigation notice,
// which we suppress) and behaviour is asserted via fetch + the status message.

const SCRIPT = './ctf-register.js';
const EXCHANGE_URL = '/ctf/register/exchange/';

function flush() {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

function loadScript(hash) {
    globalThis.location.hash = hash;
    jest.resetModules();
    require(SCRIPT);
}

function statusText() {
    return document.getElementById('ctf-register-status').textContent;
}

describe('ctf-register token exchange', () => {
    let replaceStateSpy;
    let consoleErrorSpy;

    beforeEach(() => {
        document.body.innerHTML =
            `<p id="ctf-register-status" data-exchange-url="${EXCHANGE_URL}">Validating</p>`;
        document.cookie = 'csrftoken=test-csrf';
        replaceStateSpy = jest
            .spyOn(globalThis.history, 'replaceState')
            .mockImplementation(() => {});
        // Swallow jsdom's "Not implemented: navigation" notice from location.replace.
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    });

    afterEach(() => {
        replaceStateSpy.mockRestore();
        consoleErrorSpy.mockRestore();
        globalThis.location.hash = '';
        jest.clearAllMocks();
    });

    test('POSTs the fragment token to the exchange endpoint with the CSRF header', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ redirect: '/mission-control/' }),
        });

        loadScript('#token=abc123');
        await flush();

        expect(globalThis.fetch).toHaveBeenCalledWith(EXCHANGE_URL, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': 'test-csrf',
            },
            body: JSON.stringify({ token: 'abc123' }),
        });
        // Success path does not write an error message.
        expect(statusText()).toBe('Validating');
    });

    test('scrubs the token fragment from history before navigating', () => {
        globalThis.fetch = jest.fn().mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ redirect: '/mission-control/' }),
        });

        loadScript('#token=abc123');

        expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/ctf/register/');
    });

    test('shows an error and does not POST when no token is present', () => {
        globalThis.fetch = jest.fn();

        loadScript('');

        expect(globalThis.fetch).not.toHaveBeenCalled();
        expect(statusText()).toBe('Missing invite token.');
    });

    test('shows the authored error from a rejected exchange', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue({
            ok: false,
            json: () => Promise.resolve({ error: 'Invite token has expired.' }),
        });

        loadScript('#token=expired');
        await flush();

        expect(statusText()).toBe('Invite token has expired.');
    });

    test('shows a generic error when the request fails', async () => {
        globalThis.fetch = jest.fn().mockRejectedValue(new Error('network'));

        loadScript('#token=abc123');
        await flush();

        expect(statusText()).toBe('Unable to complete sign-in. Please try again.');
    });
});
