require('./dashboard.js');

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
