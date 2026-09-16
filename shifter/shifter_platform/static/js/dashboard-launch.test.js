require('./dashboard-connection.js');
require('./dashboard-tiles.js');
require('./dashboard-launch.js');
require('./dashboard.js');

/**
 * Coverage for the DashboardLaunchBase layer (dashboard-launch.js): scenario /
 * OS / agent dropdown wiring, section visibility gating, launch-button state,
 * and the loadScenarios / loadAgents fetch flows. Exercised through a full
 * DashboardManager instance so the DOM element handles the constructor caches
 * are all populated from the fixture markup below.
 */
describe('DashboardLaunchBase (via DashboardManager)', () => {
    let manager;

    const dropdown = (id, itemsId) => `
        <div class="shifter-dropdown" id="${id}">
            <span class="shifter-dropdown-value placeholder">-- Select --</span>
            <ul id="${itemsId}"></ul>
        </div>
    `;

    const buildMarkup = () => `
        ${dropdown('scenario-dropdown', 'scenario-items')}
        <input type="hidden" id="scenario-select-value" value="">

        <div id="os-selection-section" style="display:none;">
            ${dropdown('os-dropdown', 'os-items')}
        </div>
        <input type="hidden" id="os-select-value" value="">

        <div id="agent-section" style="display:none;">
            ${dropdown('agent-dropdown', 'agent-items')}
        </div>
        <input type="hidden" id="agent-select-value" value="">

        <div id="windows-agent-section" style="display:none;">
            ${dropdown('windows-agent-dropdown', 'windows-agent-items')}
        </div>
        <input type="hidden" id="windows-agent-select-value" value="">

        <div id="linux-agent-section" style="display:none;">
            ${dropdown('linux-agent-dropdown', 'linux-agent-items')}
        </div>
        <input type="hidden" id="linux-agent-select-value" value="">

        <button id="launch-btn">Launch Range</button>

        <div id="scenario-info-panel">
            <h3 id="scenario-info-title"></h3>
            <p id="scenario-info-description"></p>
        </div>
    `;

    const AGENTS = [
        { id: 1, name: 'Win XDR', os_slug: 'windows', os_name: 'Windows', agent_type: 'xdr' },
        { id: 2, name: 'Ubuntu XDR', os_slug: 'ubuntu', os_name: 'Ubuntu', agent_type: 'xdr' },
        { id: 3, name: 'Kali XDR', os_slug: 'kali', os_name: 'Kali', agent_type: 'xdr' },
        { id: 4, name: 'Win Collector', os_slug: 'windows', os_name: 'Windows', agent_type: 'collector' },
    ];

    const okResponse = (body) => ({
        ok: true,
        redirected: false,
        url: '/x',
        status: 200,
        json: () => Promise.resolve(body),
    });

    beforeEach(() => {
        document.body.innerHTML = buildMarkup();
        jest.spyOn(console, 'log').mockImplementation(() => {});
        jest.spyOn(console, 'error').mockImplementation(() => {});
        delete globalThis.ShifterDropdown;
        globalThis.fetch = jest.fn();
        manager = new globalThis.DashboardManager({ csrfToken: 'csrf' });
    });

    afterEach(() => {
        jest.restoreAllMocks();
        jest.clearAllMocks();
        delete globalThis.ShifterDropdown;
    });

    describe('_showSection', () => {
        test('shows an element and tolerates null', () => {
            manager._showSection(manager.agentSection);
            expect(manager.agentSection.style.display).toBe('block');
            expect(() => manager._showSection(null)).not.toThrow();
        });
    });

    describe('_showAgentSectionsForRequirements', () => {
        test('from_agent only reveals the OS picker', () => {
            manager._showAgentSectionsForRequirements({ has_from_agent: true });
            expect(manager.osSelectionSection.style.display).toBe('block');
            expect(manager.windowsAgentSection.style.display).toBe('none');
        });

        test('requires_windows reveals the Windows section', () => {
            manager._showAgentSectionsForRequirements({ requires_windows: true });
            expect(manager.windowsAgentSection.style.display).toBe('block');
        });

        test('requires_linux reveals the Linux section', () => {
            manager._showAgentSectionsForRequirements({ requires_linux: true });
            expect(manager.linuxAgentSection.style.display).toBe('block');
        });

        test('from_agent plus a fixed requirement reveals both', () => {
            manager._showAgentSectionsForRequirements({ has_from_agent: true, requires_windows: true });
            expect(manager.windowsAgentSection.style.display).toBe('block');
            expect(manager.osSelectionSection.style.display).toBe('block');
        });
    });

    describe('_onScenarioChange', () => {
        beforeEach(() => {
            manager.scenarioRequirements = {
                basic: { has_from_agent: true },
                winlab: { requires_windows: true },
            };
            manager.scenarioData = {
                basic: { name: 'Basic', description: 'Basic scenario' },
            };
        });

        test('drives info panel + section visibility from requirements', () => {
            manager._onScenarioChange('basic');
            expect(manager.scenarioInfoPanel.classList.contains('visible')).toBe(true);
            expect(manager.osSelectionSection.style.display).toBe('block');
        });

        test('uses an empty requirement object for unknown scenarios', () => {
            expect(() => manager._onScenarioChange('missing')).not.toThrow();
        });
    });

    describe('_updateScenarioInfoPanel', () => {
        beforeEach(() => {
            manager.scenarioData = {
                full: { name: 'Full', description: 'A description' },
                nodesc: { name: 'NoDesc' },
            };
        });

        test('populates title and description for a known scenario', () => {
            manager._updateScenarioInfoPanel('full');
            expect(manager.scenarioInfoTitle.textContent).toBe('Full');
            expect(manager.scenarioInfoDescription.textContent).toBe('A description');
            expect(manager.scenarioInfoPanel.classList.contains('visible')).toBe(true);
        });

        test('falls back to a default description when absent', () => {
            manager._updateScenarioInfoPanel('nodesc');
            expect(manager.scenarioInfoDescription.textContent).toBe('No description available.');
        });

        test('hides the panel for an unknown scenario', () => {
            manager.scenarioInfoPanel.classList.add('visible');
            manager._updateScenarioInfoPanel('unknown');
            expect(manager.scenarioInfoPanel.classList.contains('visible')).toBe(false);
        });

        test('returns early when there is no panel', () => {
            manager.scenarioInfoPanel = null;
            expect(() => manager._updateScenarioInfoPanel('full')).not.toThrow();
        });
    });

    describe('_onOsChange', () => {
        beforeEach(() => {
            manager.agents = AGENTS;
        });

        test('ignores an empty OS type', () => {
            manager._onOsChange('');
            expect(manager.agentSection.style.display).toBe('none');
        });

        test('windows filters to Windows XDR agents', () => {
            manager._onOsChange('windows');
            expect(manager.agentSection.style.display).toBe('block');
            const items = document.getElementById('agent-items').querySelectorAll('li');
            expect(items.length).toBe(1);
            expect(items[0].textContent).toContain('Win XDR');
        });

        test('linux filters to non-Windows XDR agents', () => {
            manager._onOsChange('linux');
            const items = document.getElementById('agent-items').querySelectorAll('li');
            expect(items.length).toBe(2);
        });
    });

    describe('_hideAllAgentSections / _clearAgentSelections', () => {
        test('hides every agent section', () => {
            manager.osSelectionSection.style.display = 'block';
            manager.agentSection.style.display = 'block';
            manager.windowsAgentSection.style.display = 'block';
            manager.linuxAgentSection.style.display = 'block';

            manager._hideAllAgentSections();

            expect(manager.osSelectionSection.style.display).toBe('none');
            expect(manager.agentSection.style.display).toBe('none');
            expect(manager.windowsAgentSection.style.display).toBe('none');
            expect(manager.linuxAgentSection.style.display).toBe('none');
        });

        test('clears every agent selection and resets displays', () => {
            manager.osSelect.value = 'windows';
            manager.agentSelect.value = '5';
            manager.windowsAgentSelect.value = '1';
            manager.linuxAgentSelect.value = '2';

            manager._clearAgentSelections();

            expect(manager.osSelect.value).toBe('');
            expect(manager.agentSelect.value).toBe('');
            expect(manager.windowsAgentSelect.value).toBe('');
            expect(manager.linuxAgentSelect.value).toBe('');
        });
    });

    describe('_resetDropdownDisplay', () => {
        test('resets the trigger to the placeholder and deselects items', () => {
            const dd = document.getElementById('agent-dropdown');
            const trigger = dd.querySelector('.shifter-dropdown-value');
            trigger.textContent = 'Chosen';
            trigger.classList.remove('placeholder');
            const li = document.createElement('li');
            li.className = 'shifter-dropdown-item selected';
            dd.querySelector('ul').appendChild(li);

            manager._resetDropdownDisplay(dd, '-- Reset --');

            expect(trigger.textContent).toBe('-- Reset --');
            expect(trigger.classList.contains('placeholder')).toBe(true);
            expect(li.classList.contains('selected')).toBe(false);
        });

        test('tolerates a null dropdown', () => {
            expect(() => manager._resetDropdownDisplay(null, 'x')).not.toThrow();
        });
    });

    describe('loadScenarios', () => {
        test('falls back to default requirements without a scenarios URL', async () => {
            manager.scenariosUrl = undefined;
            await manager.loadScenarios();
            expect(manager.scenarioRequirements.basic.has_from_agent).toBe(true);
            expect(manager.scenarioRequirements.ad_attack_lab.has_from_agent).toBe(true);
        });

        test('caches requirements and populates the dropdown from the API', async () => {
            manager.scenariosUrl = '/scenarios';
            globalThis.fetch.mockResolvedValue(
                okResponse({
                    scenarios: [
                        {
                            id: 'basic',
                            name: 'Basic',
                            description: 'Basic scenario',
                            agent_requirements: { has_from_agent: true },
                        },
                        {
                            id: 'winlab',
                            name: 'Windows Lab',
                            agent_requirements: { requires_windows: true },
                        },
                    ],
                })
            );

            await manager.loadScenarios();

            expect(manager.scenarioRequirements.basic.has_from_agent).toBe(true);
            expect(manager.scenarioData.winlab.name).toBe('Windows Lab');
            const items = document.getElementById('scenario-items').querySelectorAll('li');
            expect(items.length).toBe(2);
            expect(manager.scenarioSelect.value).toBe('basic');
            const trigger = document.querySelector('#scenario-dropdown .shifter-dropdown-value');
            expect(trigger.textContent).toBe('Basic');
        });

        test('returns early when the response has no scenarios', async () => {
            manager.scenariosUrl = '/scenarios';
            globalThis.fetch.mockResolvedValue(okResponse({}));
            await manager.loadScenarios();
            expect(document.getElementById('scenario-items').querySelectorAll('li').length).toBe(0);
        });
    });

    describe('_selectFirstScenario guard', () => {
        test('returns early without a first scenario or select element', () => {
            manager.scenarioSelect = null;
            expect(() =>
                manager._selectFirstScenario(document.getElementById('scenario-items'), null)
            ).not.toThrow();
        });
    });

    describe('_updateLaunchButtonState', () => {
        test('returns early when there is no launch button', () => {
            manager.launchBtn = null;
            expect(() => manager._updateLaunchButtonState()).not.toThrow();
        });

        test('from_agent scenario requires OS and agent selection', () => {
            manager.scenarioRequirements = { basic: { has_from_agent: true } };
            manager.scenarioSelect.value = 'basic';

            manager._updateLaunchButtonState();
            expect(manager.launchBtn.disabled).toBe(true);

            manager.osSelect.value = 'windows';
            manager.agentSelect.value = '3';
            manager._updateLaunchButtonState();
            expect(manager.launchBtn.disabled).toBe(false);
        });

        test('fixed windows and linux requirements gate on their selects', () => {
            manager.scenarioRequirements = { lab: { requires_windows: true, requires_linux: true } };
            manager.scenarioSelect.value = 'lab';

            manager._updateLaunchButtonState();
            expect(manager.launchBtn.disabled).toBe(true);

            manager.windowsAgentSelect.value = '1';
            manager.linuxAgentSelect.value = '2';
            manager._updateLaunchButtonState();
            expect(manager.launchBtn.disabled).toBe(false);
        });

        test('from_agent combined with a fixed requirement needs OS + agent too', () => {
            manager.scenarioRequirements = { mix: { has_from_agent: true, requires_windows: true } };
            manager.scenarioSelect.value = 'mix';
            manager.windowsAgentSelect.value = '1';

            manager._updateLaunchButtonState();
            expect(manager.launchBtn.disabled).toBe(true);

            manager.osSelect.value = 'windows';
            manager.agentSelect.value = '3';
            manager._updateLaunchButtonState();
            expect(manager.launchBtn.disabled).toBe(false);
        });
    });

    describe('loadAgents', () => {
        test('caches agents and populates the OS-specific dropdowns', async () => {
            manager.agentsUrl = '/agents';
            globalThis.fetch.mockResolvedValue(okResponse({ agents: AGENTS }));

            await manager.loadAgents();

            expect(manager.agents.length).toBe(4);
            const winItems = document.getElementById('windows-agent-items').querySelectorAll('li');
            const linuxItems = document.getElementById('linux-agent-items').querySelectorAll('li');
            expect(winItems.length).toBe(1);
            expect(winItems[0].textContent).toContain('Win XDR');
            expect(linuxItems.length).toBe(2);
        });

        test('renders empty-state items when no matching agents exist', async () => {
            manager.agentsUrl = '/agents';
            globalThis.fetch.mockResolvedValue(
                okResponse({ agents: [AGENTS[3]] }) // only a Windows collector
            );

            await manager.loadAgents();

            const winItems = document.getElementById('windows-agent-items').querySelectorAll('li');
            const linuxItems = document.getElementById('linux-agent-items').querySelectorAll('li');
            expect(winItems[0].textContent).toBe('No Windows XDR agents');
            expect(linuxItems[0].textContent).toBe('No Linux XDR agents');
        });

        test('returns early when the fetch yields no data', async () => {
            manager.agentsUrl = '/agents';
            jest.spyOn(manager, '_fetchJson').mockResolvedValue(null);
            await manager.loadAgents();
            expect(manager.agents).toEqual([]);
        });
    });

    describe('_populate*AgentDropdown guards', () => {
        test('return early without their item containers', () => {
            manager.windowsAgentItems = null;
            manager.linuxAgentItems = null;
            expect(() => manager._populateWindowsAgentDropdown(AGENTS)).not.toThrow();
            expect(() => manager._populateLinuxAgentDropdown(AGENTS)).not.toThrow();
        });
    });

    describe('_initDropdown', () => {
        test('returns null without a dropdown or without ShifterDropdown', () => {
            expect(manager._initDropdown(null)).toBeNull();
            expect(manager._initDropdown(manager.scenarioDropdown)).toBeNull();
        });

        test('delegates to ShifterDropdown.init when available', () => {
            globalThis.ShifterDropdown = { init: jest.fn(() => 'instance') };
            const result = manager._initDropdown(manager.scenarioDropdown);
            expect(globalThis.ShifterDropdown.init).toHaveBeenCalledWith(manager.scenarioDropdown);
            expect(result).toBe('instance');
        });

        test('constructs ShifterDropdown when there is no init helper', () => {
            globalThis.ShifterDropdown = function ShifterDropdown(el) {
                this.el = el;
            };
            const result = manager._initDropdown(manager.scenarioDropdown);
            expect(result).toBeInstanceOf(globalThis.ShifterDropdown);
        });
    });

    describe('_renderAgentItems / _renderEmptyDropdown', () => {
        test('renders one item per agent with the OS name', () => {
            const container = document.getElementById('agent-items');
            manager._renderAgentItems(container, [AGENTS[0]]);
            const items = container.querySelectorAll('li');
            expect(items.length).toBe(1);
            expect(items[0].dataset.value).toBe('1');
            expect(items[0].textContent).toBe('Win XDR (Windows)');
        });

        test('renders a single disabled placeholder item', () => {
            const container = document.getElementById('agent-items');
            manager._renderEmptyDropdown(container, 'No agents');
            const li = container.querySelector('li');
            expect(li.className).toContain('disabled');
            expect(li.textContent).toBe('No agents');
        });
    });

    describe('_initScenarioDropdown', () => {
        test('initializes the scenario dropdown via ShifterDropdown.init', () => {
            globalThis.ShifterDropdown = { init: jest.fn() };
            manager._initScenarioDropdown();
            expect(globalThis.ShifterDropdown.init).toHaveBeenCalledWith(manager.scenarioDropdown);
        });
    });
});
