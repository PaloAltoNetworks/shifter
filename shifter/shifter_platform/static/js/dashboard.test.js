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
        global.fetch = fetchMock;
        global.confirm = jest.fn().mockReturnValue(true);

        dashboard = new window.DashboardManager({
            csrfToken: 'test-csrf-token',
            rangeUrl: '/range',
            launchUrl: '/launch',
            cancelUrl: '/cancel',
            destroyUrl: '/destroy',
            agentsUrl: '/agents',
        });

        dashboard.currentRange = { id: 42, status: 'ready' };
    });

    test('sends range_id in request body', async () => {
        await dashboard.destroyRange();

        expect(fetchMock).toHaveBeenCalledWith('/destroy', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': 'test-csrf-token',
            },
            body: JSON.stringify({ range_id: 42 }),
        });
    });

    test('does not call fetch if user cancels confirmation', async () => {
        global.confirm.mockReturnValue(false);

        await dashboard.destroyRange();

        expect(fetchMock).not.toHaveBeenCalled();
    });
});

describe('DashboardManager dropdown initialization', () => {
    const buildScenarioMarkup = () => `
        <div class="xdr-dropdown" id="scenario-dropdown">
            <input type="hidden" id="scenario-select-value" value="basic">
        </div>
    `;

    beforeEach(() => {
        document.body.innerHTML = buildScenarioMarkup();
        window.XdrDropdown = { init: jest.fn() };
    });

    test('uses XdrDropdown.init for explicit init', () => {
        const dashboard = new window.DashboardManager({
            csrfToken: 'csrf',
            statusUrl: '/status',
            launchUrl: '/launch',
            cancelUrl: '/cancel',
            destroyUrl: '/destroy',
            agentsUrl: '/agents',
        });

        dashboard._initScenarioDropdown();

        expect(window.XdrDropdown.init).toHaveBeenCalledWith(dashboard.scenarioDropdown);
    });
});
