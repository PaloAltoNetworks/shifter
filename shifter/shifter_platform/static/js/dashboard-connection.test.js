require('./dashboard-connection.js');
require('./dashboard-tiles.js');
require('./dashboard-launch.js');
require('./dashboard.js');

/**
 * Coverage for the DashboardConnectionBase layer (dashboard-connection.js):
 * session-expiry detection/redirect, WebSocket connect/message/close handling,
 * reconnect backoff, provisioning timeout, and the _fetchJson wrapper. Exercised
 * through a DashboardManager instance so the full prototype chain is wired up,
 * matching the require() structure the browser script tags use.
 */
describe('DashboardConnectionBase (via DashboardManager)', () => {
    let manager;
    let mockSocket;
    let hidden;

    const buildManager = (opts = {}) =>
        new globalThis.DashboardManager({
            csrfToken: 'csrf',
            rangeUrl: '/range',
            loginUrl: '/login',
            ...opts,
        });

    beforeEach(() => {
        document.body.innerHTML = '<div id="range-tile-1"></div>';

        jest.spyOn(console, 'log').mockImplementation(() => {});
        jest.spyOn(console, 'warn').mockImplementation(() => {});
        jest.spyOn(console, 'error').mockImplementation(() => {});

        mockSocket = {
            close: jest.fn(),
            onopen: null,
            onmessage: null,
            onclose: null,
            onerror: null,
        };
        globalThis.WebSocket = jest.fn(() => mockSocket);

        hidden = false;
        Object.defineProperty(document, 'hidden', {
            configurable: true,
            get: () => hidden,
        });

        // jsdom's location is non-configurable and cannot be replaced, so tests
        // work against the real environment origin (http://localhost). Navigation
        // (href assignment, reload) is a jsdom no-op that does not throw.
        globalThis.fetch = jest.fn();
        manager = buildManager();
    });

    afterEach(() => {
        manager._closeStatusSocket();
        manager.currentRange = null;
        jest.restoreAllMocks();
        jest.clearAllMocks();
    });

    describe('_isSessionExpired', () => {
        test('true when redirected to a cognito origin', () => {
            expect(
                manager._isSessionExpired({ redirected: true, url: 'https://x.cognito.com/login' })
            ).toBe(true);
        });

        test('true for 401 and 403 responses', () => {
            expect(manager._isSessionExpired({ redirected: false, url: '', status: 401 })).toBe(true);
            expect(manager._isSessionExpired({ redirected: false, url: '', status: 403 })).toBe(true);
        });

        test('false for a normal 200 response', () => {
            expect(manager._isSessionExpired({ redirected: false, url: '/range', status: 200 })).toBe(
                false
            );
        });
    });

    describe('_handleSessionExpired', () => {
        test('closes the socket and navigates for a same-origin login target', () => {
            const closeSpy = jest.spyOn(manager, '_closeStatusSocket');
            // loginUrl '/login' resolves same-origin against http://localhost, so
            // the guarded href assignment runs (a jsdom navigation no-op).
            expect(() => manager._handleSessionExpired()).not.toThrow();
            expect(closeSpy).toHaveBeenCalled();
        });

        test('does not navigate for a cross-origin login target', () => {
            manager.loginUrl = 'https://evil.test/login';
            const closeSpy = jest.spyOn(manager, '_closeStatusSocket');
            expect(() => manager._handleSessionExpired()).not.toThrow();
            expect(closeSpy).toHaveBeenCalled();
        });
    });

    describe('_bindCleanup event handlers', () => {
        test('beforeunload closes the status socket', () => {
            const spy = jest.spyOn(manager, '_closeStatusSocket');
            globalThis.dispatchEvent(new Event('beforeunload'));
            expect(spy).toHaveBeenCalled();
        });

        test('visibilitychange closes socket when tab hidden', () => {
            const spy = jest.spyOn(manager, '_closeStatusSocket');
            hidden = true;
            document.dispatchEvent(new Event('visibilitychange'));
            expect(spy).toHaveBeenCalled();
        });

        test('visibilitychange reconnects when tab shown and range transitional', () => {
            const spy = jest.spyOn(manager, '_connectStatusSocket').mockImplementation(() => {});
            manager.currentRange = { request_id: 'r1', status: 'provisioning' };
            hidden = false;
            document.dispatchEvent(new Event('visibilitychange'));
            expect(spy).toHaveBeenCalledWith('r1');
        });
    });

    describe('_buildWebSocketUrl', () => {
        test('derives the ws URL from the page protocol and host', () => {
            // Real jsdom origin is http://localhost, so the ws (not wss) scheme.
            expect(manager._buildWebSocketUrl('req-1')).toBe(
                'ws://localhost/ws/range-status/req-1/'
            );
        });
    });

    describe('_connectStatusSocket', () => {
        test('creates a WebSocket and wires up handlers', () => {
            manager._connectStatusSocket('req-1');

            expect(globalThis.WebSocket).toHaveBeenCalledWith('ws://localhost/ws/range-status/req-1/');
            expect(manager.statusSocket).toBe(mockSocket);
            expect(manager.provisioningTimer).not.toBeNull();
            expect(manager.statusPollInterval).not.toBeNull();

            // Fire each handler to cover the callback bodies.
            manager.reconnectAttempts = 3;
            manager.reconnectDelay = 8000;
            mockSocket.onopen();
            expect(manager.reconnectAttempts).toBe(0);
            expect(manager.reconnectDelay).toBe(1000);

            manager.currentRange = { request_id: 'req-1', status: 'provisioning' };
            mockSocket.onmessage({ data: JSON.stringify({ type: 'status', status: 'provisioning' }) });
            mockSocket.onerror(new Error('boom'));
            mockSocket.onclose({ code: 1000, reason: 'done' });
        });
    });

    describe('_handleStatusMessage', () => {
        beforeEach(() => {
            manager.currentRange = { request_id: 'r1', status: 'provisioning' };
        });

        test('updates status without closing on a transitional status', () => {
            const closeSpy = jest.spyOn(manager, '_closeStatusSocket');
            manager._handleStatusMessage({
                data: JSON.stringify({ type: 'status', status: 'provisioning', error_message: 'x' }),
            });
            expect(manager.currentRange.status).toBe('provisioning');
            expect(manager.currentRange.error_message).toBe('x');
            expect(closeSpy).not.toHaveBeenCalled();
        });

        test('closes the socket when a stable status arrives', () => {
            const closeSpy = jest.spyOn(manager, '_closeStatusSocket');
            manager._handleStatusMessage({
                data: JSON.stringify({ type: 'status', status: 'ready' }),
            });
            expect(manager.currentRange.status).toBe('ready');
            expect(closeSpy).toHaveBeenCalled();
        });

        test('ignores non-status message types', () => {
            manager._handleStatusMessage({ data: JSON.stringify({ type: 'ping' }) });
            expect(manager.currentRange.status).toBe('provisioning');
        });

        test('swallows malformed JSON', () => {
            expect(() => manager._handleStatusMessage({ data: 'not-json' })).not.toThrow();
        });
    });

    describe('_handleSocketClose', () => {
        test('does not reconnect on normal/auth close codes', () => {
            manager.currentRange = { request_id: 'r1', status: 'provisioning' };
            for (const code of [1000, 4001, 4003]) {
                manager.reconnectAttempts = 0;
                manager._handleSocketClose({ code, reason: '' }, 'r1');
                expect(manager.reconnectAttempts).toBe(0);
            }
        });

        test('does not reconnect when range is missing or stable', () => {
            manager.currentRange = null;
            manager._handleSocketClose({ code: 1006, reason: '' }, 'r1');
            expect(manager.reconnectAttempts).toBe(0);

            manager.currentRange = { request_id: 'r1', status: 'ready' };
            manager._handleSocketClose({ code: 1006, reason: '' }, 'r1');
            expect(manager.reconnectAttempts).toBe(0);
        });

        test('schedules a backed-off reconnect while transitional', () => {
            jest.useFakeTimers();
            const connectSpy = jest.spyOn(manager, '_connectStatusSocket').mockImplementation(() => {});
            manager.currentRange = { request_id: 'r1', status: 'provisioning' };
            manager.reconnectAttempts = 0;
            manager.reconnectDelay = 1000;

            manager._handleSocketClose({ code: 1006, reason: 'lost' }, 'r1');

            expect(manager.reconnectAttempts).toBe(1);
            expect(manager.reconnectDelay).toBe(2000);

            jest.advanceTimersByTime(1000);
            expect(connectSpy).toHaveBeenCalledWith('r1', true);
            jest.useRealTimers();
        });

        test('falls back to a page reload after max reconnect attempts', () => {
            const connectSpy = jest.spyOn(manager, '_connectStatusSocket');
            manager.currentRange = { request_id: 'r1', status: 'provisioning' };
            manager.reconnectAttempts = manager.maxReconnectAttempts;
            // The else branch calls location.reload() (a jsdom no-op) instead of
            // scheduling another reconnect; it must not increment the counter.
            expect(() =>
                manager._handleSocketClose({ code: 1006, reason: 'lost' }, 'r1')
            ).not.toThrow();
            expect(manager.reconnectAttempts).toBe(manager.maxReconnectAttempts);
            expect(connectSpy).not.toHaveBeenCalled();
        });
    });

    describe('_closeStatusSocket / _clearProvisioningTimer', () => {
        test('closes an open socket and resets retry counters by default', () => {
            manager.statusSocket = mockSocket;
            manager.reconnectAttempts = 4;
            manager.reconnectDelay = 8000;

            manager._closeStatusSocket();

            expect(mockSocket.close).toHaveBeenCalledWith(1000, 'Client closing');
            expect(manager.statusSocket).toBeNull();
            expect(manager.reconnectAttempts).toBe(0);
            expect(manager.reconnectDelay).toBe(1000);
        });

        test('preserves retry counters when resetRetry is false', () => {
            manager.reconnectAttempts = 2;
            manager.reconnectDelay = 4000;
            manager._closeStatusSocket(false);
            expect(manager.reconnectAttempts).toBe(2);
            expect(manager.reconnectDelay).toBe(4000);
        });

        test('clears a pending provisioning timer', () => {
            manager.provisioningTimer = setTimeout(() => {}, 10000);
            manager._clearProvisioningTimer();
            expect(manager.provisioningTimer).toBeNull();
        });
    });

    describe('_handleProvisioningTimeout', () => {
        test('marks the current range failed and repaints', () => {
            const updateSpy = jest.spyOn(manager, '_updateUI');
            manager.currentRange = { request_id: 'r1', status: 'provisioning' };
            manager._handleProvisioningTimeout();
            expect(manager.currentRange.status).toBe('failed');
            expect(manager.currentRange.error_message).toBe('Provisioning timed out');
            expect(updateSpy).toHaveBeenCalled();
        });

        test('is safe when there is no current range', () => {
            manager.currentRange = null;
            expect(() => manager._handleProvisioningTimeout()).not.toThrow();
        });
    });

    describe('_fetchJson', () => {
        const okResponse = (body) => ({
            ok: true,
            redirected: false,
            url: '/range',
            status: 200,
            json: () => Promise.resolve(body),
        });

        test('returns parsed JSON on success', async () => {
            globalThis.fetch.mockResolvedValue(okResponse({ range: { status: 'ready' } }));
            const data = await manager._fetchJson('/range', 'err');
            expect(data).toEqual({ range: { status: 'ready' } });
        });

        test('returns null and redirects on an expired session', async () => {
            const sessionSpy = jest.spyOn(manager, '_handleSessionExpired').mockImplementation(() => {});
            globalThis.fetch.mockResolvedValue({
                ok: false,
                redirected: false,
                url: '',
                status: 401,
                json: () => Promise.resolve({}),
            });
            const data = await manager._fetchJson('/range', 'err');
            expect(data).toBeNull();
            expect(sessionSpy).toHaveBeenCalled();
        });

        test('returns null on a non-ok, non-auth response', async () => {
            globalThis.fetch.mockResolvedValue({
                ok: false,
                redirected: false,
                url: '',
                status: 500,
                json: () => Promise.resolve({}),
            });
            const data = await manager._fetchJson('/range', 'boom');
            expect(data).toBeNull();
        });

        test('treats a Failed to fetch TypeError as an expired session', async () => {
            const sessionSpy = jest.spyOn(manager, '_handleSessionExpired').mockImplementation(() => {});
            globalThis.fetch.mockRejectedValue(new TypeError('Failed to fetch'));
            const data = await manager._fetchJson('/range', 'err');
            expect(data).toBeNull();
            expect(sessionSpy).toHaveBeenCalled();
        });

        test('returns null on any other thrown error', async () => {
            globalThis.fetch.mockRejectedValue(new Error('kaboom'));
            const data = await manager._fetchJson('/range', 'err');
            expect(data).toBeNull();
        });
    });

    describe('_startStatusPolling stable-state detection', () => {
        test('adopts the polled range and closes when a stable state is polled', async () => {
            jest.useFakeTimers();
            manager.currentRange = { request_id: 'r1', status: 'provisioning' };
            const closeSpy = jest.spyOn(manager, '_closeStatusSocket');
            globalThis.fetch.mockResolvedValue({
                ok: true,
                redirected: false,
                url: '/range',
                status: 200,
                json: () =>
                    Promise.resolve({
                        range: { request_id: 'r1', status: 'ready' },
                        raes_projection: null,
                        raes_participant_runtime: null,
                    }),
            });

            manager._startStatusPolling();
            await jest.advanceTimersByTimeAsync(30000);

            expect(manager.currentRange.status).toBe('ready');
            expect(closeSpy).toHaveBeenCalled();
            jest.useRealTimers();
        });
    });
});
