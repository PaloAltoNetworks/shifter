// Tests for ctf-participant-range.js — openRdpSession POSTs an RDP request with
// the CSRF token, polls the returned status URL until the broker hands back a
// session URL, and drives the pre-opened popup window (or a fresh popup).
//
// The module reads its config from a #ctf-participant-range-config json_script
// element and exposes openRdpSession on globalThis, so each scenario reloads the
// module against a fresh DOM.

const CONFIG = { rdpUrl: '/api/rdp/' };

function loadModule({ config = CONFIG, withConfig = true } = {}) {
    jest.resetModules();
    document.body.innerHTML = '';
    if (withConfig) {
        const script = document.createElement('script');
        script.id = 'ctf-participant-range-config';
        script.type = 'application/json';
        script.textContent = JSON.stringify(config);
        document.body.appendChild(script);
    }
    require('./ctf-participant-range.js');
}

function clearCookies() {
    document.cookie.split(';').forEach((c) => {
        document.cookie = c.replace(/=.*/, '=;expires=' + new Date(0).toUTCString());
    });
}

function makeButton() {
    const btn = document.createElement('button');
    btn.textContent = 'Open';
    document.body.appendChild(btn);
    return btn;
}

function makeSessionWindow() {
    return { opener: {}, location: { replace: jest.fn() }, close: jest.fn() };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('ctf-participant-range openRdpSession', () => {
    let fetchMock;
    let alertMock;
    let openMock;

    beforeEach(() => {
        clearCookies();
        fetchMock = jest.fn();
        globalThis.fetch = fetchMock;
        alertMock = jest.fn();
        globalThis.alert = alertMock;
        openMock = jest.fn();
        globalThis.open = openMock;
        jest.spyOn(console, 'error').mockImplementation(() => {});
    });

    afterEach(() => {
        jest.restoreAllMocks();
        jest.useRealTimers();
    });

    test('exposes openRdpSession and reads config from the json_script element', () => {
        loadModule();
        expect(typeof globalThis.openRdpSession).toBe('function');
    });

    test('tolerates a missing config element', () => {
        loadModule({ withConfig: false });
        expect(typeof globalThis.openRdpSession).toBe('function');
    });

    test('alerts and does not fetch when instance UUID is missing', () => {
        loadModule();
        const btn = makeButton();

        globalThis.openRdpSession(btn, '');

        expect(alertMock).toHaveBeenCalledWith('Instance not available');
        expect(fetchMock).not.toHaveBeenCalled();
    });

    test('POSTs with the CSRF token, polls, and replaces the popup location', async () => {
        loadModule();
        document.cookie = 'csrftoken=tok-123';
        const sessionWindow = makeSessionWindow();
        openMock.mockReturnValue(sessionWindow);
        fetchMock
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status_url: '/status/' }) })
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ url: '/session/' }) });
        const btn = makeButton();

        globalThis.openRdpSession(btn, 'uuid-1');
        await flush();
        await flush();

        expect(sessionWindow.opener).toBeNull();
        const [postUrl, postOpts] = fetchMock.mock.calls[0];
        expect(postUrl).toBe('/api/rdp/');
        expect(postOpts.method).toBe('POST');
        expect(postOpts.headers['X-CSRFToken']).toBe('tok-123');
        expect(JSON.parse(postOpts.body)).toEqual({ instance_uuid: 'uuid-1' });

        const [statusUrl, statusOpts] = fetchMock.mock.calls[1];
        expect(statusUrl).toBe('/status/');
        expect(statusOpts.credentials).toBe('same-origin');

        expect(sessionWindow.location.replace).toHaveBeenCalledWith('/session/');
        expect(btn.disabled).toBe(false);
        expect(btn.textContent).toBe('Open');
    });

    test('sends a null CSRF token when no csrftoken cookie is present', async () => {
        loadModule();
        document.cookie = 'other=1';
        openMock.mockReturnValue(makeSessionWindow());
        fetchMock
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status_url: '/status/' }) })
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ url: '/session/' }) });
        const btn = makeButton();

        globalThis.openRdpSession(btn, 'uuid-1');
        await flush();
        await flush();

        expect(fetchMock.mock.calls[0][1].headers['X-CSRFToken']).toBeNull();
    });

    test('opens a fresh popup when the pre-opened window was blocked', async () => {
        loadModule();
        openMock.mockReturnValue(null);
        fetchMock
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status_url: '/status/' }) })
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ url: '/session/' }) });
        const btn = makeButton();

        globalThis.openRdpSession(btn, 'uuid-1');
        await flush();
        await flush();

        expect(openMock).toHaveBeenCalledWith('/session/', '_blank', 'noopener,noreferrer');
        expect(alertMock).not.toHaveBeenCalled();
    });

    test('closes the popup and alerts when the POST returns an error', async () => {
        loadModule();
        const sessionWindow = makeSessionWindow();
        openMock.mockReturnValue(sessionWindow);
        fetchMock.mockResolvedValueOnce({ ok: false, json: () => Promise.resolve({ error: 'boom' }) });
        const btn = makeButton();

        globalThis.openRdpSession(btn, 'uuid-1');
        await flush();
        await flush();

        expect(sessionWindow.close).toHaveBeenCalled();
        expect(alertMock).toHaveBeenCalledWith('Failed to open session: boom');
        expect(btn.disabled).toBe(false);
    });

    test('alerts when the POST response omits a status URL', async () => {
        loadModule();
        openMock.mockReturnValue(makeSessionWindow());
        fetchMock.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });
        const btn = makeButton();

        globalThis.openRdpSession(btn, 'uuid-1');
        await flush();
        await flush();

        expect(alertMock).toHaveBeenCalledWith(
            'Failed to open session: Session request did not return a status URL'
        );
    });

    test('alerts when a poll response reports an error', async () => {
        loadModule();
        openMock.mockReturnValue(makeSessionWindow());
        fetchMock
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status_url: '/status/' }) })
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ error: 'poll error' }) });
        const btn = makeButton();

        globalThis.openRdpSession(btn, 'uuid-1');
        await flush();
        await flush();

        expect(alertMock).toHaveBeenCalledWith('Failed to open session: poll error');
    });

    test('alerts when a poll response is not ok', async () => {
        loadModule();
        openMock.mockReturnValue(makeSessionWindow());
        fetchMock
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status_url: '/status/' }) })
            .mockResolvedValueOnce({ ok: false, json: () => Promise.resolve({ error: 'poll fail' }) });
        const btn = makeButton();

        globalThis.openRdpSession(btn, 'uuid-1');
        await flush();
        await flush();

        expect(alertMock).toHaveBeenCalledWith('Failed to open session: poll fail');
    });

    test('waits and retries when the broker is not ready yet', async () => {
        jest.useFakeTimers();
        loadModule();
        const sessionWindow = makeSessionWindow();
        openMock.mockReturnValue(sessionWindow);
        fetchMock
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status_url: '/status/' }) })
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
            .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ url: '/session/' }) });
        const btn = makeButton();

        globalThis.openRdpSession(btn, 'uuid-1');
        // Drain the POST + first poll, fire the 1s retry timer, then the second poll.
        await jest.advanceTimersByTimeAsync(1000);
        await jest.advanceTimersByTimeAsync(0);

        expect(fetchMock).toHaveBeenCalledTimes(3);
        expect(sessionWindow.location.replace).toHaveBeenCalledWith('/session/');
    });
});
