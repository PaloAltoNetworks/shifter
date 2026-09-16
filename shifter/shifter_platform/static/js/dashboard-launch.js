/**
 * Dashboard launch UI - scenario / OS / agent dropdowns and launch-button
 * gating, plus loading scenarios and agents.
 *
 * Split out of dashboard.js (SonarCloud javascript:S104). Extends
 * DashboardTilesBase and is extended in turn by DashboardManager;
 * load after dashboard-tiles.js.
 */
const DashboardTilesBaseClass = globalThis.DashboardTilesBase;

class DashboardLaunchBase extends DashboardTilesBaseClass {
    /**
     * Handle scenario dropdown change.
     * Shows/hides agent sections based on scenario requirements.
     */
    _onScenarioChange(scenario) {
        const req = this.scenarioRequirements[scenario] || {}; // eslint-disable-line security/detect-object-injection

        // Update scenario info panel
        this._updateScenarioInfoPanel(scenario);

        // Hide all agent sections first
        this._hideAllAgentSections();

        // Clear all agent selections
        this._clearAgentSelections();

        // Show appropriate sections based on requirements
        this._showAgentSectionsForRequirements(req);

        this._updateLaunchButtonState();
    }

    /** Show a section element if it exists. */
    _showSection(section) {
        if (section) {
            section.style.display = 'block';
        }
    }

    /** Reveal the agent/OS sections implied by a scenario's requirements. */
    _showAgentSectionsForRequirements(req) {
        if (req.has_from_agent && !req.requires_windows && !req.requires_linux) {
            // Only from_agent instances - show OS picker first; agent dropdown
            // is shown after OS selection.
            this._showSection(this.osSelectionSection);
            return;
        }

        // Fixed OS requirements
        if (req.requires_windows) {
            this._showSection(this.windowsAgentSection);
        }
        if (req.requires_linux) {
            this._showSection(this.linuxAgentSection);
        }
        // If has_from_agent AND fixed requirements, show OS picker too
        if (req.has_from_agent) {
            this._showSection(this.osSelectionSection);
        }
    }

    /**
     * Update the scenario info panel with the selected scenario's details.
     */
    _updateScenarioInfoPanel(scenarioId) {
        const scenario = this.scenarioData[scenarioId]; // eslint-disable-line security/detect-object-injection

        if (!this.scenarioInfoPanel) return;

        if (scenario) {
            if (this.scenarioInfoTitle) {
                this.scenarioInfoTitle.textContent = scenario.name;
            }
            if (this.scenarioInfoDescription) {
                this.scenarioInfoDescription.textContent = scenario.description || 'No description available.';
            }
            this.scenarioInfoPanel.classList.add('visible');
        } else {
            this.scenarioInfoPanel.classList.remove('visible');
        }
    }

    /**
     * Handle OS selection change.
     * Filters agent dropdown by selected OS and agent type (XDR only).
     */
    _onOsChange(osType) {
        if (!osType) return;

        // Show the agent section
        if (this.agentSection) {
            this.agentSection.style.display = 'block';
        }

        // Filter agents by OS and agent_type (only XDR agents for range creation)
        const filteredAgents = this.agents.filter(agent => {
            // Only show XDR agents in range creation dropdowns
            if (agent.agent_type !== 'xdr') {
                return false;
            }
            if (osType === 'windows') {
                return agent.os_slug === 'windows';
            }
            // linux includes ubuntu, kali, etc.
            return agent.os_slug !== 'windows';
        });

        // Populate filtered dropdown
        this._renderAgentItems(this.agentItems, filteredAgents);
        this._initDropdown(this.agentDropdown);

        // Clear previous selection
        if (this.agentSelect) {
            this.agentSelect.value = '';
        }
        this._resetDropdownDisplay(this.agentDropdown, '-- Select an XDR agent --');

        this._updateLaunchButtonState();
    }

    /**
     * Hide all agent-related sections.
     */
    _hideAllAgentSections() {
        if (this.osSelectionSection) {
            this.osSelectionSection.style.display = 'none';
        }
        if (this.agentSection) {
            this.agentSection.style.display = 'none';
        }
        if (this.windowsAgentSection) {
            this.windowsAgentSection.style.display = 'none';
        }
        if (this.linuxAgentSection) {
            this.linuxAgentSection.style.display = 'none';
        }
    }

    /**
     * Clear all agent selections.
     */
    _clearAgentSelections() {
        if (this.osSelect) this.osSelect.value = '';
        if (this.agentSelect) this.agentSelect.value = '';
        if (this.windowsAgentSelect) this.windowsAgentSelect.value = '';
        if (this.linuxAgentSelect) this.linuxAgentSelect.value = '';

        this._resetDropdownDisplay(this.osDropdown, '-- Select OS type --');
        this._resetDropdownDisplay(this.agentDropdown, '-- Select an agent --');
        this._resetDropdownDisplay(this.windowsAgentDropdown, '-- Select a Windows agent --');
        this._resetDropdownDisplay(this.linuxAgentDropdown, '-- Select a Linux agent --');
    }

    /**
     * Reset a dropdown to placeholder state.
     */
    _resetDropdownDisplay(dropdown, placeholder) {
        if (!dropdown) return;
        const trigger = dropdown.querySelector('.shifter-dropdown-value');
        if (trigger) {
            trigger.textContent = placeholder;
            trigger.classList.add('placeholder');
        }
        // Clear selected state
        const items = dropdown.querySelectorAll('.shifter-dropdown-item');
        items.forEach(item => item.classList.remove('selected'));
    }

    async loadScenarios() {
        // Scenarios are loaded via the scenarios endpoint
        // which includes agent_requirements for each scenario
        const scenariosUrl = this.scenariosUrl;
        if (!scenariosUrl) {
            // Fallback: assume basic has from_agent only
            this.scenarioRequirements = {
                basic: { has_from_agent: true, requires_windows: false, requires_linux: false },
                ad_attack_lab: { has_from_agent: true, requires_windows: false, requires_linux: false },
            };
            return;
        }

        const data = await this._fetchJson(scenariosUrl, 'Failed to load scenarios');
        if (!data?.scenarios) {
            return;
        }

        // Cache agent requirements and scenario data, then populate dropdown
        this._cacheScenarioData(data.scenarios);

        const scenarioItems = document.getElementById('scenario-items');
        if (scenarioItems && data.scenarios.length > 0) {
            this._populateScenarioDropdown(scenarioItems, data.scenarios);
            // Re-init dropdown to bind events to new items
            this._initDropdown(this.scenarioDropdown);
        }
    }

    /** Cache agent requirements and full scenario data keyed by scenario id. */
    _cacheScenarioData(scenarios) {
        for (const scenario of scenarios) {
            this.scenarioRequirements[scenario.id] = scenario.agent_requirements || {};
            this.scenarioData[scenario.id] = scenario;
        }
    }

    /** Build the scenario dropdown items and select the first scenario. */
    _populateScenarioDropdown(scenarioItems, scenarios) {
        scenarioItems.innerHTML = '';

        for (const scenario of scenarios) {
            // Create dropdown item - NAME ONLY (no description)
            const li = document.createElement('li');
            li.className = 'shifter-dropdown-item';
            li.dataset.value = scenario.id;
            li.textContent = scenario.name;

            scenarioItems.appendChild(li);
        }

        this._selectFirstScenario(scenarioItems, scenarios[0]);
    }

    /** Select the first scenario by default and update the dropdown display. */
    _selectFirstScenario(scenarioItems, firstScenario) {
        if (!firstScenario || !this.scenarioSelect) {
            return;
        }
        this.scenarioSelect.value = firstScenario.id;
        // Update dropdown display
        const trigger = this.scenarioDropdown?.querySelector('.shifter-dropdown-value');
        if (trigger) {
            trigger.textContent = firstScenario.name;
            trigger.classList.remove('placeholder');
        }
        // Mark first item as selected
        const firstItem = scenarioItems.querySelector('.shifter-dropdown-item');
        if (firstItem) {
            firstItem.classList.add('selected');
        }
        // Update scenario info panel
        this._updateScenarioInfoPanel(firstScenario.id);
    }

    _initScenarioDropdown() {
        // Initialize the scenario dropdown with Dropdown if available
        this._initDropdown(this.scenarioDropdown);
    }

    _updateLaunchButtonState() {
        if (!this.launchBtn) return;

        const scenario = this.scenarioSelect?.value || 'basic';
        const req = this.scenarioRequirements[scenario] || {}; // eslint-disable-line security/detect-object-injection

        let canLaunch = true;

        // Check if from_agent scenario needs OS + agent selection
        if (req.has_from_agent && !req.requires_windows && !req.requires_linux) {
            // Need OS selected AND agent selected
            const hasOs = Boolean(this.osSelect?.value);
            const hasAgent = Boolean(this.agentSelect?.value);
            canLaunch = hasOs && hasAgent;
        } else {
            // Check fixed requirements
            if (req.requires_windows) {
                canLaunch = canLaunch && Boolean(this.windowsAgentSelect?.value);
            }
            if (req.requires_linux) {
                canLaunch = canLaunch && Boolean(this.linuxAgentSelect?.value);
            }
            // If has_from_agent with fixed requirements, also need OS + agent
            if (req.has_from_agent) {
                const hasOs = Boolean(this.osSelect?.value);
                const hasAgent = Boolean(this.agentSelect?.value);
                canLaunch = canLaunch && hasOs && hasAgent;
            }
        }

        this.launchBtn.disabled = !canLaunch;
    }

    async loadAgents() {
        const data = await this._fetchJson(this.agentsUrl, 'Failed to load agents');
        if (!data) {
            return;
        }

        // Cache agents for later reference
        this.agents = data.agents || [];

        // Populate OS-specific dropdowns
        this._populateWindowsAgentDropdown(this.agents);
        this._populateLinuxAgentDropdown(this.agents);

        // Initialize current scenario's agent UI
        const scenario = this.scenarioSelect?.value || 'basic';
        this._onScenarioChange(scenario);
    }

    _initDropdown(dropdown) {
        if (!dropdown || !globalThis.ShifterDropdown) {
            return null;
        }

        if (typeof globalThis.ShifterDropdown.init === 'function') {
            return globalThis.ShifterDropdown.init(dropdown);
        }

        return new globalThis.ShifterDropdown(dropdown);
    }

    _populateWindowsAgentDropdown(agents) {
        if (!this.windowsAgentItems) {
            return;
        }

        // Filter to only XDR agents (not XDR Collector or Cloud Identity Engine)
        // and Windows OS
        const windowsAgents = agents.filter(agent =>
            agent.os_slug === 'windows' && agent.agent_type === 'xdr'
        );
        if (windowsAgents.length === 0) {
            this._renderEmptyDropdown(this.windowsAgentItems, 'No Windows XDR agents');
        } else {
            this._renderAgentItems(this.windowsAgentItems, windowsAgents);
        }

        this._initDropdown(this.windowsAgentDropdown);
    }

    _populateLinuxAgentDropdown(agents) {
        if (!this.linuxAgentItems) {
            return;
        }

        // Filter to only XDR agents (not XDR Collector or Cloud Identity Engine)
        // and Linux OS
        const linuxAgents = agents.filter(agent =>
            agent.os_slug !== 'windows' && agent.agent_type === 'xdr'
        );
        if (linuxAgents.length === 0) {
            this._renderEmptyDropdown(this.linuxAgentItems, 'No Linux XDR agents');
        } else {
            this._renderAgentItems(this.linuxAgentItems, linuxAgents);
        }

        this._initDropdown(this.linuxAgentDropdown);
    }

    _renderAgentItems(container, agents) {
        container.innerHTML = '';

        for (const agent of agents) {
            const li = document.createElement('li');
            li.className = 'shifter-dropdown-item';
            li.dataset.value = agent.id;
            li.textContent = `${agent.name} (${agent.os_name})`;
            container.appendChild(li);
        }
    }

    _renderEmptyDropdown(container, message) {
        container.innerHTML = '';
        const li = document.createElement('li');
        li.className = 'shifter-dropdown-item disabled';
        li.textContent = message;
        container.appendChild(li);
    }
}

globalThis.DashboardLaunchBase = DashboardLaunchBase;
