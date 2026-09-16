/**
 * Mission Control NGFW list page tests.
 *
 * Covers the per-card refresh button: the spin animation, the list re-fetch, the
 * conditional page reload when the NGFW is still present, error logging, and the
 * icon/button reset in the finally block. fetch is mocked; location.reload() is a
 * jsdom no-op that the console.error spy silences. The source self-runs
 * initNgfwList() on require (readyState is 'complete' under jsdom), so the DOM
 * fixture is built before each require and jest.resetModules() re-runs it per test.
 */

const LIST_URL = '/api/v1/mission-control/ngfw/';
const NGFW_ID = 'ngfw-7';

const buildMarkup = ({ grid = true, button = true } = {}) => {
    if (!grid) return '<div>no grid here</div>';
    let html = `<div class="ngfw-grid" data-ngfw-list-url="${LIST_URL}">`;
    if (button) {
        html += `<button class="ngfw-refresh-btn" data-ngfw-id="${NGFW_ID}"><svg></svg></button>`;
    }
    html += '</div>';
    return html;
};

function load(opts) {
    document.body.innerHTML = buildMarkup(opts);
    require('./ngfw-list.js');
}

describe('ngfw-list', () => {
    let fetchMock;

    beforeEach(() => {
        jest.resetModules();
        jest.useFakeTimers();
        jest.spyOn(console, 'error').mockImplementation(() => {});
        fetchMock = jest.fn();
        globalThis.fetch = fetchMock;
    });

    afterEach(() => {
        jest.runOnlyPendingTimers();
        jest.useRealTimers();
        jest.restoreAllMocks();
        document.body.innerHTML = '';
    });

    test('no-ops when the grid is absent', () => {
        expect(() => load({ grid: false })).not.toThrow();
    });

    test('spins the icon, fetches the list, and reloads when the NGFW is present', async () => {
        fetchMock.mockResolvedValue({
            json: () => Promise.resolve({ ngfws: [{ id: NGFW_ID }] }),
        });
        load();
        const btn = document.querySelector('.ngfw-refresh-btn');
        const icon = btn.querySelector('svg');

        btn.click();
        expect(btn.disabled).toBe(true);
        expect(icon.style.transform).toBe('rotate(360deg)');

        await jest.advanceTimersByTimeAsync(600);

        expect(fetchMock).toHaveBeenCalledWith(LIST_URL);
        // location.reload() is a jsdom navigation no-op; the finally block still
        // resets the icon and button.
        expect(icon.style.transform).toBe('rotate(0deg)');
        expect(btn.disabled).toBe(false);
    });

    test('does not reload when the NGFW is missing from the response', async () => {
        fetchMock.mockResolvedValue({
            json: () => Promise.resolve({ ngfws: [{ id: 'someone-else' }] }),
        });
        load();
        const btn = document.querySelector('.ngfw-refresh-btn');
        const icon = btn.querySelector('svg');

        btn.click();
        await jest.advanceTimersByTimeAsync(600);

        expect(fetchMock).toHaveBeenCalledWith(LIST_URL);
        expect(icon.style.transform).toBe('rotate(0deg)');
        expect(btn.disabled).toBe(false);
    });

    test('logs the error and still resets when the fetch fails', async () => {
        fetchMock.mockRejectedValue(new Error('network down'));
        load();
        const btn = document.querySelector('.ngfw-refresh-btn');
        const icon = btn.querySelector('svg');

        btn.click();
        await jest.advanceTimersByTimeAsync(600);

        expect(console.error).toHaveBeenCalledWith('Refresh failed:', expect.any(Error));
        expect(icon.style.transform).toBe('rotate(0deg)');
        expect(btn.disabled).toBe(false);
    });

    test('registers a DOMContentLoaded handler while the document is still loading', async () => {
        Object.defineProperty(document, 'readyState', {
            configurable: true,
            get: () => 'loading',
        });
        try {
            fetchMock.mockResolvedValue({
                json: () => Promise.resolve({ ngfws: [{ id: NGFW_ID }] }),
            });
            load();
            document.dispatchEvent(new Event('DOMContentLoaded'));

            const btn = document.querySelector('.ngfw-refresh-btn');
            btn.click();
            await jest.advanceTimersByTimeAsync(600);

            expect(fetchMock).toHaveBeenCalledWith(LIST_URL);
        } finally {
            Object.defineProperty(document, 'readyState', {
                configurable: true,
                get: () => 'complete',
            });
        }
    });
});
