// Tests for mc-credentials-detail.js — the Mission Control credential detail
// page: delete a stored credential, then redirect to the same-origin list URL.
//
// The module reads config (CSRF token + list URL) from a
// #mc-credentials-detail-config json_script and binds a click handler to
// #delete-btn on DOMContentLoaded. Each scenario builds a fresh DOM fixture,
// then requires the module and dispatches DOMContentLoaded.

const CONFIG = {
    csrfToken: 'tok-1',
    listUrl: '/mission-control/credentials/',
};

function fixture({ withButton = true, config = CONFIG } = {}) {
    const configScript =
        config === null
            ? ''
            : `<script id="mc-credentials-detail-config" type="application/json">${JSON.stringify(
                  config
              )}</script>`;
    const button = withButton
        ? `<button id="delete-btn" data-credential-id="9" data-credential-name="My Cred">Delete</button>`
        : '';
    return `${configScript}${button}`;
}

function loadModule(opts) {
    jest.resetModules();
    document.body.innerHTML = fixture(opts);
    require('./mc-credentials-detail.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('mc-credentials-detail', () => {
    let fetchMock;
    let alertMock;
    let confirmMock;
    let errSpy;

    beforeEach(() => {
        fetchMock = jest.fn();
        globalThis.fetch = fetchMock;
        alertMock = jest.fn();
        globalThis.alert = alertMock;
        confirmMock = jest.fn(() => true);
        globalThis.confirm = confirmMock;
        // location.href assignment triggers a jsdom navigation notice.
        errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    });

    afterEach(() => {
        jest.restoreAllMocks();
    });

    test('does nothing when the delete button is absent', () => {
        expect(() => loadModule({ withButton: false })).not.toThrow();
    });

    test('does not fetch when the user cancels the confirmation', () => {
        loadModule();
        confirmMock.mockReturnValue(false);

        document.getElementById('delete-btn').click();

        expect(confirmMock).toHaveBeenCalledWith(
            'Are you sure you want to delete "My Cred"? This cannot be undone.'
        );
        expect(fetchMock).not.toHaveBeenCalled();
    });

    test('POSTs the delete and redirects to the list on success', async () => {
        loadModule();
        fetchMock.mockResolvedValue({ json: () => Promise.resolve({}) });

        document.getElementById('delete-btn').click();
        await flush();
        await flush();

        const [url, opts] = fetchMock.mock.calls[0];
        expect(url).toBe('/api/v1/mission-control/credentials/9/delete/');
        expect(opts.method).toBe('POST');
        expect(opts.headers['X-CSRFToken']).toBe('tok-1');
        expect(alertMock).not.toHaveBeenCalled();
    });

    test('alerts the server error and does not redirect on a logical failure', async () => {
        loadModule();
        fetchMock.mockResolvedValue({ json: () => Promise.resolve({ error: 'in use' }) });

        document.getElementById('delete-btn').click();
        await flush();
        await flush();

        expect(alertMock).toHaveBeenCalledWith('in use');
    });

    test('alerts a generic message when the delete fetch rejects', async () => {
        loadModule();
        fetchMock.mockRejectedValue(new Error('network down'));

        document.getElementById('delete-btn').click();
        await flush();
        await flush();

        expect(alertMock).toHaveBeenCalledWith('An error occurred. Please try again.');
    });
});
