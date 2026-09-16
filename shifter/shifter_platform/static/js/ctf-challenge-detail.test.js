// Tests for ctf-challenge-detail.js — CTF participant flag submission, hint
// reveal (with penalty confirmation), challenge-file download, and rating.
//
// The module reads config from a #ctf-challenge-detail-config json_script
// element, binds a click handler to every [data-download-url] link at load, and
// exposes submitFlag/useHint/rateChallenge on globalThis. Each scenario reloads
// the module against a fresh DOM fixture.

const CONFIG = {
    submitFlagUrl: '/submit',
    useHintUrl: '/hint',
    rateChallengeUrl: '/rate',
    challengePoints: 100,
    totalHintPenalty: 0,
};

function fixture(config) {
    const configScript =
        config === null
            ? ''
            : `<script id="ctf-challenge-detail-config" type="application/json">${JSON.stringify(
                  config
              )}</script>`;
    return `
        ${configScript}
        <form id="flag-form">
            <input id="flag-input" value="FLAG{x}">
            <button id="submit-btn">Submit</button>
        </form>
        <div id="submit-result" class="d-none"></div>
        <div id="rating-result" class="d-none"></div>
        <div class="btn-group">
            <button class="btn"></button>
            <button class="btn"></button>
            <button class="btn"></button>
            <button class="btn"></button>
            <button class="btn"></button>
        </div>
        <a href="#orig" data-download-url="/dl/1">file</a>
    `;
}

function loadModule(config = CONFIG) {
    jest.resetModules();
    document.body.innerHTML = fixture(config);
    require('./ctf-challenge-detail.js');
}

function clearCookies() {
    document.cookie.split(';').forEach((c) => {
        document.cookie = c.replace(/=.*/, '=;expires=' + new Date(0).toUTCString());
    });
}

function response({ status = 200, ok = true, data = {}, retryAfter = null }) {
    return {
        status,
        ok,
        headers: { get: jest.fn(() => retryAfter) },
        json: () => Promise.resolve(data),
    };
}

const flush = () => new Promise((r) => setTimeout(r, 0));
const submitResult = () => document.getElementById('submit-result');
const ratingResult = () => document.getElementById('rating-result');

describe('ctf-challenge-detail', () => {
    let fetchMock;
    let alertMock;
    let confirmMock;

    beforeEach(() => {
        clearCookies();
        fetchMock = jest.fn();
        globalThis.fetch = fetchMock;
        alertMock = jest.fn();
        globalThis.alert = alertMock;
        confirmMock = jest.fn(() => true);
        globalThis.confirm = confirmMock;
        jest.spyOn(console, 'error').mockImplementation(() => {});
    });

    afterEach(() => {
        jest.restoreAllMocks();
        jest.useRealTimers();
    });

    test('exposes handlers and tolerates a missing config element', () => {
        loadModule(null);
        expect(typeof globalThis.submitFlag).toBe('function');
        expect(typeof globalThis.useHint).toBe('function');
        expect(typeof globalThis.rateChallenge).toBe('function');
    });

    describe('submitFlag', () => {
        test('POSTs the flag with the CSRF token from the cookie', async () => {
            loadModule();
            document.cookie = 'csrftoken=tok-9';
            fetchMock.mockResolvedValue(response({ data: { correct: false } }));
            const evt = { preventDefault: jest.fn() };

            globalThis.submitFlag(evt);
            await flush();
            await flush();

            expect(evt.preventDefault).toHaveBeenCalled();
            const [url, opts] = fetchMock.mock.calls[0];
            expect(url).toBe('/submit');
            expect(opts.method).toBe('POST');
            expect(opts.headers['X-CSRFToken']).toBe('tok-9');
            expect(JSON.parse(opts.body)).toEqual({ flag: 'FLAG{x}' });
        });

        test('handles 429 rate limiting with a retry hint', async () => {
            loadModule();
            fetchMock.mockResolvedValue(
                response({ status: 429, ok: false, data: { retry_after_seconds: 30 } })
            );

            globalThis.submitFlag({ preventDefault: jest.fn() });
            await flush();
            await flush();

            const rd = submitResult();
            expect(rd.className).toBe('alert alert-warning mb-3');
            expect(rd.innerHTML).toContain('30 seconds');
            expect(document.getElementById('submit-btn').disabled).toBe(false);
        });

        test('handles 429 rate limiting without a retry value', async () => {
            loadModule();
            fetchMock.mockResolvedValue(response({ status: 429, ok: false, data: {} }));

            globalThis.submitFlag({ preventDefault: jest.fn() });
            await flush();
            await flush();

            const rd = submitResult();
            expect(rd.className).toBe('alert alert-warning mb-3');
            expect(rd.innerHTML).toContain('too quickly');
            expect(rd.innerHTML).not.toContain('Try again');
        });

        test('shows success, hides the form, and reloads on a correct flag', async () => {
            jest.useFakeTimers();
            loadModule();
            fetchMock.mockResolvedValue(
                response({ data: { correct: true, points_awarded: 50 } })
            );

            globalThis.submitFlag({ preventDefault: jest.fn() });
            await jest.advanceTimersByTimeAsync(0);

            const rd = submitResult();
            expect(rd.className).toBe('alert alert-success mb-3');
            expect(rd.innerHTML).toContain('50 points');
            expect(document.getElementById('flag-form').style.display).toBe('none');

            // Fire the deferred location.reload(); jsdom logs an
            // unimplemented-navigation notice which the console.error spy
            // silences. The call itself does not throw.
            await jest.advanceTimersByTimeAsync(1500);
        });

        test('shows the server message on an incorrect flag and clears the input', async () => {
            loadModule();
            fetchMock.mockResolvedValue(
                response({ data: { correct: false, message: 'Close, but no.' } })
            );

            globalThis.submitFlag({ preventDefault: jest.fn() });
            await flush();
            await flush();

            const rd = submitResult();
            expect(rd.className).toBe('alert alert-danger mb-3');
            expect(rd.innerHTML).toContain('Incorrect');
            expect(rd.innerHTML).toContain('Close, but no.');
            expect(document.getElementById('flag-input').value).toBe('');
        });

        test('shows a bare "Incorrect" when no message is returned', async () => {
            loadModule();
            fetchMock.mockResolvedValue(response({ data: { correct: false } }));

            globalThis.submitFlag({ preventDefault: jest.fn() });
            await flush();
            await flush();

            expect(submitResult().innerHTML).toContain('Incorrect');
        });

        test('shows the API error on a non-ok response', async () => {
            loadModule();
            fetchMock.mockResolvedValue(
                response({ status: 500, ok: false, data: { error: 'Server boom' } })
            );

            globalThis.submitFlag({ preventDefault: jest.fn() });
            await flush();
            await flush();

            const rd = submitResult();
            expect(rd.className).toBe('alert alert-danger mb-3');
            expect(rd.textContent).toBe('Server boom');
        });

        test('falls back to a generic error when the response has no error field', async () => {
            loadModule();
            fetchMock.mockResolvedValue(response({ status: 500, ok: false, data: {} }));

            globalThis.submitFlag({ preventDefault: jest.fn() });
            await flush();
            await flush();

            expect(submitResult().textContent).toBe('An error occurred. Please try again.');
        });

        test('shows a generic error when the fetch rejects', async () => {
            loadModule();
            fetchMock.mockRejectedValue(new Error('network down'));

            globalThis.submitFlag({ preventDefault: jest.fn() });
            await flush();
            await flush();

            const rd = submitResult();
            expect(rd.className).toBe('alert alert-danger mb-3');
            expect(rd.textContent).toBe('An error occurred. Please try again.');
            expect(document.getElementById('submit-btn').disabled).toBe(false);
        });
    });

    describe('useHint', () => {
        test('does not fetch when the user declines the confirmation', () => {
            loadModule();
            confirmMock.mockReturnValue(false);

            globalThis.useHint('hint-1', 10);

            expect(confirmMock).toHaveBeenCalled();
            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('POSTs the hint id and reloads when hint text is returned', async () => {
            loadModule();
            // location.reload() is exercised here; jsdom logs an
            // unimplemented-navigation notice which the console.error spy
            // silences. We assert the request shape instead of the reload sink.
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({ text: 'the hint' }) });

            globalThis.useHint('hint-1', 10);
            await flush();
            await flush();

            const [url, opts] = fetchMock.mock.calls[0];
            expect(url).toBe('/hint');
            expect(JSON.parse(opts.body)).toEqual({ hint_id: 'hint-1' });
        });

        test('alerts the error when the hint request fails logically', async () => {
            loadModule();
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({ error: 'no hint' }) });

            globalThis.useHint('hint-1', 10);
            await flush();
            await flush();

            expect(alertMock).toHaveBeenCalledWith('no hint');
        });

        test('alerts a generic error when the hint fetch rejects', async () => {
            loadModule();
            fetchMock.mockRejectedValue(new Error('network down'));

            globalThis.useHint('hint-1', 10);
            await flush();
            await flush();

            expect(alertMock).toHaveBeenCalledWith('An error occurred. Please try again.');
        });

        test('warns when the projected penalty caps the challenge at minimum value', () => {
            loadModule({ ...CONFIG, totalHintPenalty: 95 });
            confirmMock.mockReturnValue(false);

            globalThis.useHint('hint-1', 10);

            const msg = confirmMock.mock.calls[0][0];
            expect(msg).toContain('WARNING');
            expect(msg).toContain('minimum value');
        });

        test('omits the cost line for a free (zero-penalty) hint', () => {
            loadModule();
            confirmMock.mockReturnValue(false);

            globalThis.useHint('hint-1', 0);

            const msg = confirmMock.mock.calls[0][0];
            expect(msg).not.toContain('penalty');
            expect(msg).toContain('cannot be undone');
        });
    });

    describe('downloadFile (data-download-url links)', () => {
        test('navigates to the signed URL returned by the API', async () => {
            loadModule();
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({ url: '#downloaded' }) });
            const link = document.querySelector('[data-download-url]');

            link.click();
            await flush();
            await flush();

            expect(fetchMock).toHaveBeenCalledWith('/dl/1', {
                headers: { 'X-CSRFToken': null },
            });
            expect(alertMock).not.toHaveBeenCalled();
            expect(globalThis.location.hash).toBe('#downloaded');
        });

        test('alerts the API error when the download is refused', async () => {
            loadModule();
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({ error: 'denied' }) });

            document.querySelector('[data-download-url]').click();
            await flush();
            await flush();

            expect(alertMock).toHaveBeenCalledWith('denied');
        });

        test('alerts a download failure when the fetch rejects', async () => {
            loadModule();
            fetchMock.mockRejectedValue(new Error('network down'));

            document.querySelector('[data-download-url]').click();
            await flush();
            await flush();

            expect(alertMock).toHaveBeenCalledWith('Download failed.');
        });
    });

    describe('rateChallenge', () => {
        test('shows success and highlights the chosen rating button', async () => {
            loadModule();
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({}) });

            globalThis.rateChallenge(3);
            await flush();
            await flush();

            const rr = ratingResult();
            expect(rr.className).toBe('alert alert-success mb-3');
            expect(rr.textContent).toContain('Rated 3/5');
            const buttons = document.querySelectorAll('.btn-group .btn');
            expect(buttons[2].className).toBe('btn btn-warning btn-sm');
            expect(buttons[0].className).toBe('btn btn-outline-warning btn-sm');
        });

        test('shows the API error when rating is rejected', async () => {
            loadModule();
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({ error: 'already rated' }) });

            globalThis.rateChallenge(3);
            await flush();
            await flush();

            const rr = ratingResult();
            expect(rr.className).toBe('alert alert-danger mb-3');
            expect(rr.textContent).toBe('already rated');
        });

        test('shows a failure message when the rating fetch rejects', async () => {
            loadModule();
            fetchMock.mockRejectedValue(new Error('network down'));

            globalThis.rateChallenge(3);
            await flush();
            await flush();

            expect(ratingResult().textContent).toBe('Rating failed. Please try again.');
        });
    });
});
