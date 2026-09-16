// Tests for admin-challenge-detail.js — CTF admin add/remove for flags, files,
// prerequisites, and hints, plus challenge-file downloads.
//
// The module reads config from a #admin-challenge-detail-config json_script
// element, binds a click handler to every [data-download-url] link at load, and
// exposes the add*/remove* handlers on globalThis. Removal URLs embed a
// placeholder id that is swapped for the real object id at call time.

const PLACEHOLDER_ID = '00000000-0000-0000-0000-000000000000';

const CONFIG = {
    addFlagUrl: '/flags/add',
    removeFlagUrl: `/flags/${PLACEHOLDER_ID}/remove`,
    removeFileUrl: `/files/${PLACEHOLDER_ID}/remove`,
    addPrerequisiteUrl: '/prereqs/add',
    removePrerequisiteUrl: `/prereqs/${PLACEHOLDER_ID}/remove`,
    addHintUrl: '/hints/add',
    removeHintUrl: `/hints/${PLACEHOLDER_ID}/remove`,
};

function fixture(config) {
    const configScript =
        config === null
            ? ''
            : `<script id="admin-challenge-detail-config" type="application/json">${JSON.stringify(
                  config
              )}</script>`;
    return `
        ${configScript}
        <input id="new-flag-value" value="FLAG{a}">
        <select id="new-flag-type"><option value="static" selected>static</option></select>
        <select id="new-flag-case-sensitive"><option value="true" selected>true</option></select>
        <select id="prereq-challenge-select"><option value="chal-9" selected>c9</option></select>
        <input id="new-hint-text" value="Look closer">
        <input id="new-hint-penalty" value="25">
        <input id="new-hint-order" value="2">
        <a href="#orig" data-download-url="/dl/1">file</a>
    `;
}

function loadModule(config = CONFIG) {
    jest.resetModules();
    document.body.innerHTML = fixture(config);
    require('./admin-challenge-detail.js');
}

function clearCookies() {
    document.cookie.split(';').forEach((c) => {
        document.cookie = c.replace(/=.*/, '=;expires=' + new Date(0).toUTCString());
    });
}

const flush = () => new Promise((r) => setTimeout(r, 0));
const okJson = (data = {}) => ({ ok: true, json: () => Promise.resolve(data) });

describe('admin-challenge-detail', () => {
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
    });

    test('exposes handlers and tolerates a missing config element', () => {
        loadModule(null);
        for (const name of [
            'addFlag',
            'removeFlag',
            'removeFile',
            'addPrerequisite',
            'removePrerequisite',
            'addHint',
            'removeHint',
        ]) {
            expect(typeof globalThis[name]).toBe('function');
        }
    });

    describe('addFlag', () => {
        test('alerts and does not fetch when the flag value is blank', () => {
            loadModule();
            document.getElementById('new-flag-value').value = '   ';

            globalThis.addFlag();

            expect(alertMock).toHaveBeenCalledWith('Flag value is required');
            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('POSTs the flag payload and reloads on success', async () => {
            loadModule();
            document.cookie = 'csrftoken=tok-1';
            fetchMock.mockResolvedValue(okJson({}));

            globalThis.addFlag();
            await flush();
            await flush();

            const [url, opts] = fetchMock.mock.calls[0];
            expect(url).toBe('/flags/add');
            expect(opts.method).toBe('POST');
            expect(opts.headers['X-CSRFToken']).toBe('tok-1');
            expect(JSON.parse(opts.body)).toEqual({
                flag: 'FLAG{a}',
                flag_type: 'static',
                case_sensitive: true,
            });
        });

        test('alerts the returned error instead of reloading', async () => {
            loadModule();
            fetchMock.mockResolvedValue(okJson({ error: 'duplicate flag' }));

            globalThis.addFlag();
            await flush();
            await flush();

            expect(alertMock).toHaveBeenCalledWith('duplicate flag');
        });
    });

    describe('removeFlag / removeFile / removePrerequisite', () => {
        test('removeFlag returns early without fetch when not confirmed', () => {
            loadModule();
            confirmMock.mockReturnValue(false);

            globalThis.removeFlag('flag-7');

            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('removeFlag substitutes the id into the URL and sends no body', async () => {
            loadModule();
            fetchMock.mockResolvedValue(okJson({}));

            globalThis.removeFlag('flag-7');
            await flush();
            await flush();

            const [url, opts] = fetchMock.mock.calls[0];
            expect(url).toBe('/flags/flag-7/remove');
            expect(opts.method).toBe('POST');
            expect(opts.body).toBeUndefined();
        });

        test('removeFile substitutes the id into the URL', async () => {
            loadModule();
            fetchMock.mockResolvedValue(okJson({}));

            globalThis.removeFile('file-3');
            await flush();
            await flush();

            expect(fetchMock.mock.calls[0][0]).toBe('/files/file-3/remove');
        });

        test('removeFile does not fetch when not confirmed', () => {
            loadModule();
            confirmMock.mockReturnValue(false);

            globalThis.removeFile('file-3');

            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('removePrerequisite substitutes the id into the URL', async () => {
            loadModule();
            fetchMock.mockResolvedValue(okJson({}));

            globalThis.removePrerequisite('prereq-2');
            await flush();
            await flush();

            expect(fetchMock.mock.calls[0][0]).toBe('/prereqs/prereq-2/remove');
        });

        test('removePrerequisite does not fetch when not confirmed', () => {
            loadModule();
            confirmMock.mockReturnValue(false);

            globalThis.removePrerequisite('prereq-2');

            expect(fetchMock).not.toHaveBeenCalled();
        });
    });

    describe('addPrerequisite', () => {
        test('alerts and does not fetch when no challenge is selected', () => {
            loadModule();
            const select = document.getElementById('prereq-challenge-select');
            select.innerHTML = '<option value="" selected></option>';

            globalThis.addPrerequisite();

            expect(alertMock).toHaveBeenCalledWith('Select a challenge');
            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('POSTs the selected challenge id', async () => {
            loadModule();
            fetchMock.mockResolvedValue(okJson({}));

            globalThis.addPrerequisite();
            await flush();
            await flush();

            const [url, opts] = fetchMock.mock.calls[0];
            expect(url).toBe('/prereqs/add');
            expect(JSON.parse(opts.body)).toEqual({ required_challenge_id: 'chal-9' });
        });
    });

    describe('addHint', () => {
        test('alerts and does not fetch when the hint text is blank', () => {
            loadModule();
            document.getElementById('new-hint-text').value = '   ';

            globalThis.addHint();

            expect(alertMock).toHaveBeenCalledWith('Hint text is required.');
            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('POSTs the hint with parsed penalty and order', async () => {
            loadModule();
            fetchMock.mockResolvedValue(okJson({}));

            globalThis.addHint();
            await flush();
            await flush();

            const [url, opts] = fetchMock.mock.calls[0];
            expect(url).toBe('/hints/add');
            expect(JSON.parse(opts.body)).toEqual({
                text: 'Look closer',
                penalty: 25,
                order: 2,
            });
        });

        test('defaults penalty and order to 0 when the fields are non-numeric', async () => {
            loadModule();
            document.getElementById('new-hint-penalty').value = '';
            document.getElementById('new-hint-order').value = 'abc';
            fetchMock.mockResolvedValue(okJson({}));

            globalThis.addHint();
            await flush();
            await flush();

            expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
                text: 'Look closer',
                penalty: 0,
                order: 0,
            });
        });
    });

    describe('removeHint', () => {
        test('returns early without fetch when not confirmed', () => {
            loadModule();
            confirmMock.mockReturnValue(false);

            globalThis.removeHint('hint-4');

            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('reloads on an ok response', async () => {
            loadModule();
            fetchMock.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });

            globalThis.removeHint('hint-4');
            await flush();
            await flush();

            expect(fetchMock.mock.calls[0][0]).toBe('/hints/hint-4/remove');
            expect(alertMock).not.toHaveBeenCalled();
        });

        test('alerts the parsed error on a non-ok response', async () => {
            loadModule();
            fetchMock.mockResolvedValue({
                ok: false,
                json: () => Promise.resolve({ error: 'cannot remove' }),
            });

            globalThis.removeHint('hint-4');
            await flush();
            await flush();

            expect(alertMock).toHaveBeenCalledWith('cannot remove');
        });
    });

    describe('downloadFile (data-download-url links)', () => {
        test('navigates to the signed URL returned by the API', async () => {
            loadModule();
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({ url: '#downloaded' }) });

            document.querySelector('[data-download-url]').click();
            await flush();
            await flush();

            expect(fetchMock).toHaveBeenCalledWith('/dl/1', { headers: { 'X-CSRFToken': null } });
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
});
