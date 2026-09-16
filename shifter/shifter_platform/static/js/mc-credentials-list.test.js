// Tests for mc-credentials-list.js — the Mission Control credentials list page:
// type filter tabs and per-row delete-with-confirmation.
//
// The module reads the CSRF token from a #mc-credentials-config json_script and
// wires the filter tabs and delete buttons on DOMContentLoaded. Each scenario
// builds a fresh DOM fixture, then requires the module and dispatches
// DOMContentLoaded.

function fixture({ withConfig = true } = {}) {
    const configScript = withConfig
        ? `<script id="mc-credentials-config" type="application/json">${JSON.stringify({
              csrfToken: 'tok-1',
          })}</script>`
        : '';
    return `
        ${configScript}
        <button class="filter-tab active" data-filter="all">All</button>
        <button class="filter-tab" data-filter="scm">SCM</button>
        <button class="filter-tab" data-filter="deployment_profile">Profiles</button>
        <table>
            <tbody>
                <tr data-type="scm"><td>SCM row</td>
                    <td><button data-action="delete" data-credential-id="1"
                                data-credential-name="SCM One">Delete</button></td></tr>
                <tr data-type="deployment_profile"><td>Profile row</td>
                    <td><button data-action="delete" data-credential-id="2"
                                data-credential-name="Profile Two">Delete</button></td></tr>
            </tbody>
        </table>
    `;
}

function loadModule(opts) {
    jest.resetModules();
    document.body.innerHTML = fixture(opts);
    require('./mc-credentials-list.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('mc-credentials-list', () => {
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
        // location.reload() triggers a jsdom navigation notice.
        errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    });

    afterEach(() => {
        jest.restoreAllMocks();
    });

    test('tolerates a missing config element (empty CSRF token)', () => {
        expect(() => loadModule({ withConfig: false })).not.toThrow();
    });

    describe('filter tabs', () => {
        test('filtering by type hides non-matching rows and marks the active tab', () => {
            loadModule();
            const scmTab = document.querySelector('[data-filter="scm"]');

            scmTab.click();

            expect(scmTab.classList.contains('active')).toBe(true);
            expect(document.querySelector('[data-filter="all"]').classList.contains('active')).toBe(false);
            const rows = document.querySelectorAll('tbody tr');
            expect(rows[0].style.display).toBe(''); // scm row shown
            expect(rows[1].style.display).toBe('none'); // profile row hidden
        });

        test('the "all" filter reveals every row again', () => {
            loadModule();
            document.querySelector('[data-filter="scm"]').click();

            document.querySelector('[data-filter="all"]').click();

            const rows = document.querySelectorAll('tbody tr');
            expect(rows[0].style.display).toBe('');
            expect(rows[1].style.display).toBe('');
        });
    });

    describe('delete buttons', () => {
        test('does not fetch when the user cancels the confirmation', () => {
            loadModule();
            confirmMock.mockReturnValue(false);

            document.querySelector('[data-credential-id="1"]').click();

            expect(confirmMock).toHaveBeenCalledWith(
                'Are you sure you want to delete "SCM One"? This cannot be undone.'
            );
            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('POSTs the delete and reloads on success', async () => {
            loadModule();
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({}) });

            document.querySelector('[data-credential-id="1"]').click();
            await flush();
            await flush();

            const [url, opts] = fetchMock.mock.calls[0];
            expect(url).toBe('/api/v1/mission-control/credentials/1/delete/');
            expect(opts.method).toBe('POST');
            expect(opts.headers['X-CSRFToken']).toBe('tok-1');
            expect(alertMock).not.toHaveBeenCalled();
        });

        test('alerts the server error when the delete is refused', async () => {
            loadModule();
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({ error: 'in use' }) });

            document.querySelector('[data-credential-id="2"]').click();
            await flush();
            await flush();

            expect(alertMock).toHaveBeenCalledWith('in use');
        });

        test('alerts a generic message when the delete fetch rejects', async () => {
            loadModule();
            fetchMock.mockRejectedValue(new Error('network down'));

            document.querySelector('[data-credential-id="1"]').click();
            await flush();
            await flush();

            expect(alertMock).toHaveBeenCalledWith('An error occurred. Please try again.');
        });
    });
});
