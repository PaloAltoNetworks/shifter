/**
 * Mission Control NGFW detail page tests.
 *
 * Covers the refresh-status button (re-fetches the NGFW list then reloads) and
 * the CLI access button (exchanges a short-lived SSH URL and opens it in a new
 * tab, with popup-blocked and error handling). fetch, globalThis.open, confirm,
 * alert and AbortSignal.timeout are mocked; navigation calls are jsdom no-ops.
 */

require('./ngfw-detail.js');

const buildMarkup = ({ refresh = true, cli = true } = {}) => {
    let html = '';
    if (refresh) {
        html += '<button class="ngfw-refresh-btn" data-ngfw-list-url="/ngfw/list"><svg></svg></button>';
    }
    if (cli) {
        html += '<button id="ngfw-cli-btn" data-ssh-url="/ngfw/ssh"><span>Open CLI</span></button>';
    }
    return html;
};

function initPage(opts) {
    document.body.innerHTML = buildMarkup(opts);
    document.dispatchEvent(new Event('DOMContentLoaded'));
}

describe('ngfw-detail', () => {
    let fetchMock;
    let openMock;

    beforeEach(() => {
        jest.useFakeTimers();
        jest.spyOn(console, 'error').mockImplementation(() => {});

        fetchMock = jest.fn();
        globalThis.fetch = fetchMock;
        openMock = jest.fn();
        globalThis.open = openMock;
        globalThis.confirm = jest.fn().mockReturnValue(true);
        globalThis.alert = jest.fn();
        globalThis.AbortSignal = { timeout: jest.fn(() => ({})) };

        document.cookie = 'csrftoken=test-csrf';
    });

    afterEach(() => {
        jest.runOnlyPendingTimers();
        jest.useRealTimers();
        jest.restoreAllMocks();
    });

    test('no-ops when neither button is present', () => {
        expect(() => initPage({ refresh: false, cli: false })).not.toThrow();
    });

    describe('refresh button', () => {
        test('fetches the NGFW list and resets the icon/button afterward', async () => {
            fetchMock.mockResolvedValue({});
            initPage({ cli: false });
            const btn = document.querySelector('.ngfw-refresh-btn');
            const icon = btn.querySelector('svg');

            btn.click();
            expect(btn.disabled).toBe(true);
            expect(icon.style.transform).toBe('rotate(360deg)');

            await jest.advanceTimersByTimeAsync(600);

            expect(fetchMock).toHaveBeenCalledWith('/ngfw/list');
            expect(icon.style.transform).toBe('rotate(0deg)');
            expect(btn.disabled).toBe(false);
        });

        test('logs and still resets when the fetch fails', async () => {
            fetchMock.mockRejectedValue(new Error('boom'));
            initPage({ cli: false });
            const btn = document.querySelector('.ngfw-refresh-btn');

            btn.click();
            await jest.advanceTimersByTimeAsync(600);

            expect(console.error).toHaveBeenCalledWith('Refresh failed:', expect.any(Error));
            expect(btn.disabled).toBe(false);
        });
    });

    describe('CLI button', () => {
        function cliButton() {
            initPage({ refresh: false });
            return document.getElementById('ngfw-cli-btn');
        }

        test('exchanges the SSH URL and opens it in a new tab', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({ url: 'https://cli.example/session' }),
            });
            openMock.mockReturnValue({ closed: false });
            const btn = cliButton();
            const span = btn.querySelector('span');

            btn.click();
            expect(btn.disabled).toBe(true);
            expect(span.textContent).toBe('Opening CLI...');

            await jest.advanceTimersByTimeAsync(1100);

            expect(fetchMock).toHaveBeenCalledWith(
                '/ngfw/ssh',
                expect.objectContaining({
                    method: 'POST',
                    headers: expect.objectContaining({
                        'X-CSRFToken': 'test-csrf',
                        'Content-Type': 'application/json',
                    }),
                }),
            );
            expect(openMock).toHaveBeenCalledWith('https://cli.example/session', '_blank');
            expect(globalThis.confirm).not.toHaveBeenCalled();
            expect(btn.disabled).toBe(false);
            expect(span.textContent).toBe('Open CLI');
        });

        test('falls back to same-tab navigation when the popup is blocked and confirmed', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({ url: 'https://cli.example/session' }),
            });
            openMock.mockReturnValue(null);
            globalThis.confirm.mockReturnValue(true);
            const btn = cliButton();

            btn.click();
            await jest.advanceTimersByTimeAsync(1100);

            expect(globalThis.confirm).toHaveBeenCalled();
            expect(globalThis.alert).not.toHaveBeenCalled();
        });

        test('alerts when the popup is blocked and the user declines', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({ url: 'https://cli.example/session' }),
            });
            openMock.mockReturnValue(null);
            globalThis.confirm.mockReturnValue(false);
            const btn = cliButton();

            btn.click();
            await jest.advanceTimersByTimeAsync(1100);

            expect(globalThis.alert).toHaveBeenCalledWith(
                expect.stringContaining('Popup blocked by browser'),
            );
            expect(btn.disabled).toBe(false);
        });

        test('alerts the server error message on a non-OK response', async () => {
            fetchMock.mockResolvedValue({
                ok: false,
                statusText: 'Bad Request',
                json: () => Promise.resolve({ error: 'no session available' }),
            });
            const btn = cliButton();

            btn.click();
            await jest.advanceTimersByTimeAsync(1100);

            expect(globalThis.alert).toHaveBeenCalledWith(
                expect.stringContaining('no session available'),
            );
        });

        test('falls back to statusText when the error body is not JSON', async () => {
            fetchMock.mockResolvedValue({
                ok: false,
                statusText: 'Service Unavailable',
                json: () => Promise.reject(new Error('not json')),
            });
            const btn = cliButton();

            btn.click();
            await jest.advanceTimersByTimeAsync(1100);

            expect(globalThis.alert).toHaveBeenCalledWith(
                expect.stringContaining('Service Unavailable'),
            );
        });

        test('alerts when the server returns no URL', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({}),
            });
            const btn = cliButton();

            btn.click();
            await jest.advanceTimersByTimeAsync(1100);

            expect(globalThis.alert).toHaveBeenCalledWith(
                expect.stringContaining('Server returned invalid response'),
            );
        });

        test('maps timeouts to a friendly message', async () => {
            fetchMock.mockRejectedValue(Object.assign(new Error('aborted'), { name: 'TimeoutError' }));
            const btn = cliButton();

            btn.click();
            await jest.advanceTimersByTimeAsync(1100);

            expect(globalThis.alert).toHaveBeenCalledWith(
                expect.stringContaining('Request timed out'),
            );
        });

        test('maps network errors to a friendly message', async () => {
            fetchMock.mockRejectedValue(new Error('Failed to fetch'));
            const btn = cliButton();

            btn.click();
            await jest.advanceTimersByTimeAsync(1100);

            expect(globalThis.alert).toHaveBeenCalledWith(
                expect.stringContaining('Network error'),
            );
        });

        test('reads a null CSRF token when no cookie is set', async () => {
            // Expire the csrftoken cookie via the normal setter (no accessor
            // override) so document.cookie reports empty and getCookie returns null.
            document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
            expect(document.cookie).toBe('');
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({ url: 'https://cli.example/session' }),
            });
            openMock.mockReturnValue({ closed: false });
            const btn = cliButton();

            btn.click();
            await jest.advanceTimersByTimeAsync(1100);

            expect(fetchMock).toHaveBeenCalledWith(
                '/ngfw/ssh',
                expect.objectContaining({
                    headers: expect.objectContaining({ 'X-CSRFToken': null }),
                }),
            );
        });
    });
});
