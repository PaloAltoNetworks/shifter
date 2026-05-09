require('./dashboard.js');

describe('DashboardManager destroyRange', () => {
    let dashboard;
    let fetchMock;

    beforeEach(() => {
        document.body.innerHTML = `
            <div id="no-range-state"></div>
            <div id="provisioning-state"></div>
            <div id="active-range-state"></div>
            <div id="paused-range-state"></div>
            <div id="failed-state"></div>
        `;

        fetchMock = jest.fn().mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({}),
        });
        globalThis.fetch = fetchMock;
        globalThis.confirm = jest.fn().mockReturnValue(true);

        dashboard = new globalThis.DashboardManager({
            csrfToken: 'test-csrf-token',
            rangeUrl: '/range',
            launchUrl: '/launch',
            cancelUrl: '/cancel',
            destroyUrl: '/destroy',
            agentsUrl: '/agents',
        });

        dashboard.currentRange = { request_id: 'abc-123-def', status: 'ready' };
    });

    test('sends request_id in request body', async () => {
        await dashboard.destroyRange();

        expect(fetchMock).toHaveBeenCalledWith('/destroy', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': 'test-csrf-token',
            },
            body: JSON.stringify({ request_id: 'abc-123-def' }),
        });
    });

    test('does not call fetch if user cancels confirmation', async () => {
        globalThis.confirm.mockReturnValue(false);

        await dashboard.destroyRange();

        expect(fetchMock).not.toHaveBeenCalled();
    });
});

describe('DashboardManager dropdown initialization', () => {
    const buildScenarioMarkup = () => `
        <div class="shifter-dropdown" id="scenario-dropdown">
            <input type="hidden" id="scenario-select-value" value="basic">
        </div>
    `;

    beforeEach(() => {
        document.body.innerHTML = buildScenarioMarkup();
        globalThis.ShifterDropdown = { init: jest.fn() };
    });

    test('uses ShifterDropdown.init for explicit init', () => {
        const dashboard = new globalThis.DashboardManager({
            csrfToken: 'csrf',
            statusUrl: '/status',
            launchUrl: '/launch',
            cancelUrl: '/cancel',
            destroyUrl: '/destroy',
            agentsUrl: '/agents',
        });

        dashboard._initScenarioDropdown();

        expect(globalThis.ShifterDropdown.init).toHaveBeenCalledWith(dashboard.scenarioDropdown);
    });
});

describe('DashboardManager status polling', () => {
    let dashboard;
    let fetchMock;

    beforeEach(() => {
        jest.useFakeTimers();

        document.body.innerHTML = `
            <div id="no-range-state"></div>
            <div id="provisioning-state"></div>
            <div id="active-range-state"></div>
            <div id="paused-range-state"></div>
            <div id="failed-state"></div>
        `;

        fetchMock = jest.fn().mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ range: { range_id: 42, status: 'provisioning' } }),
        });
        globalThis.fetch = fetchMock;

        dashboard = new globalThis.DashboardManager({
            csrfToken: 'test-csrf-token',
            rangeUrl: '/range',
            launchUrl: '/launch',
            cancelUrl: '/cancel',
            destroyUrl: '/destroy',
            agentsUrl: '/agents',
        });

        dashboard.currentRange = { range_id: 42, status: 'provisioning' };
    });

    afterEach(() => {
        jest.useRealTimers();
        dashboard._stopStatusPolling();
    });

    test('_startStatusPolling creates interval', () => {
        expect(dashboard.statusPollInterval).toBeNull();

        dashboard._startStatusPolling();

        expect(dashboard.statusPollInterval).not.toBeNull();
    });

    test('_startStatusPolling does not create multiple intervals', () => {
        dashboard._startStatusPolling();
        const firstInterval = dashboard.statusPollInterval;

        dashboard._startStatusPolling();

        expect(dashboard.statusPollInterval).toBe(firstInterval);
    });

    test('_stopStatusPolling clears interval', () => {
        dashboard._startStatusPolling();
        expect(dashboard.statusPollInterval).not.toBeNull();

        dashboard._stopStatusPolling();

        expect(dashboard.statusPollInterval).toBeNull();
    });

    test('polling fetches range status at interval', async () => {
        dashboard._startStatusPolling();

        // Advance past the polling interval
        jest.advanceTimersByTime(30000);

        // Allow promises to resolve
        await Promise.resolve();

        expect(fetchMock).toHaveBeenCalledWith('/range', {
            headers: { 'Accept': 'application/json' },
        });
    });

    test('polling updates UI when stable state detected', async () => {
        fetchMock.mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ range: { range_id: 42, status: 'ready' } }),
        });

        dashboard._startStatusPolling();
        await jest.advanceTimersByTimeAsync(30000);

        expect(dashboard.currentRange.status).toBe('ready');
    });

    test('polling stops when stable state detected', async () => {
        fetchMock.mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ range: { range_id: 42, status: 'ready' } }),
        });

        dashboard._startStatusPolling();
        await jest.advanceTimersByTimeAsync(30000);

        expect(dashboard.statusPollInterval).toBeNull();
    });

    test('polling stops when no current range', async () => {
        dashboard._startStatusPolling();
        dashboard.currentRange = null;

        jest.advanceTimersByTime(30000);
        await Promise.resolve();

        expect(dashboard.statusPollInterval).toBeNull();
    });

    test('_closeStatusSocket stops polling', () => {
        dashboard._startStatusPolling();
        expect(dashboard.statusPollInterval).not.toBeNull();

        dashboard._closeStatusSocket();

        expect(dashboard.statusPollInterval).toBeNull();
    });
});
