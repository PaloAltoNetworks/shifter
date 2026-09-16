require('./dashboard-connection.js');
require('./dashboard-tiles.js');
require('./dashboard-launch.js');
require('./dashboard.js');
require('./dashboard-init.js');

/**
 * Coverage for dashboard-init.js: the DOMContentLoaded bootstrap that reads the
 * page-embedded #dashboard-config payload and constructs / initializes a
 * DashboardManager. The listener is registered at require() time, so tests drive
 * it by dispatching DOMContentLoaded against a controlled DOM.
 */
describe('dashboard-init bootstrap', () => {
    let initSpy;

    beforeEach(() => {
        jest.spyOn(console, 'log').mockImplementation(() => {});
        jest.spyOn(console, 'error').mockImplementation(() => {});
        globalThis.fetch = jest
            .fn()
            .mockResolvedValue({
                ok: true,
                redirected: false,
                url: '/range',
                status: 200,
                json: () => Promise.resolve({}),
            });
        // Neutralize init() so the bootstrap under test does not run the whole
        // load pipeline; we only assert it is invoked on the constructed manager.
        initSpy = jest
            .spyOn(globalThis.DashboardManager.prototype, 'init')
            .mockResolvedValue(undefined);
    });

    afterEach(() => {
        jest.restoreAllMocks();
        jest.clearAllMocks();
        document.body.innerHTML = '';
    });

    test('does nothing when #dashboard-config is absent', () => {
        document.body.innerHTML = '';
        document.dispatchEvent(new Event('DOMContentLoaded'));
        expect(initSpy).not.toHaveBeenCalled();
    });

    test('constructs a DashboardManager from the config payload and initializes it', () => {
        document.body.innerHTML =
            '<script id="dashboard-config" type="application/json">' +
            '{"viewOnly": true, "rangeUrl": "/range"}' +
            '</script>';

        document.dispatchEvent(new Event('DOMContentLoaded'));

        expect(initSpy).toHaveBeenCalledTimes(1);
        expect(initSpy.mock.instances[0]).toBeInstanceOf(globalThis.DashboardManager);
        expect(initSpy.mock.instances[0].rangeUrl).toBe('/range');
    });
});
