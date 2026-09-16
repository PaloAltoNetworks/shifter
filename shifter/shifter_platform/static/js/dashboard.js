/**
 * Dashboard - range launch and management (top of the DashboardManager class
 * chain).
 *
 * Holds construction / event-wiring, initialization, and the range lifecycle
 * actions (launch, cancel, destroy, pause, resume, dismiss). The rest of the
 * behavior lives in the base classes it extends, split out for
 * SonarCloud javascript:S104:
 *   DashboardConnectionBase (dashboard-connection.js)
 *     -> DashboardTilesBase (dashboard-tiles.js)
 *       -> DashboardLaunchBase (dashboard-launch.js)
 *         -> DashboardManager (this file)
 * Load this file last; it publishes globalThis.DashboardManager.
 */

const DashboardLaunchBaseClass = globalThis.DashboardLaunchBase;

class DashboardManager extends DashboardLaunchBaseClass {
    constructor(options) {
        super();
        this.csrfToken = options.csrfToken;
        this.rangeUrl = options.rangeUrl;
        this.launchUrl = options.launchUrl;
        this.cancelUrl = options.cancelUrl;
        this.destroyUrl = options.destroyUrl;
        this.pauseUrl = options.pauseUrl;
        this.resumeUrl = options.resumeUrl;
        this.agentsUrl = options.agentsUrl;
        this.scenariosUrl = options.scenariosUrl;
        this.loginUrl = options.loginUrl || '/dashboard/';
        this.viewOnly = options.viewOnly || false;

        // State
        this.currentRange = null;
        // Secondary, read-only RAES operation projection (#1276). Absent/null for
        // legacy non-RAES ranges; never drives lifecycle, websocket, or polling.
        this.currentRaesProjection = null;
        // Secondary, read-only RAES participant/runtime + access-channel
        // projection (#1290). Sibling to currentRaesProjection: absent/null for
        // legacy non-RAES ranges; never drives lifecycle, websocket, or polling.
        this.currentRaesParticipantRuntime = null;
        this.statusSocket = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000; // Start with 1 second
        this.agents = []; // Cached agent list with os_slug

        // Provisioning timeout (from Django settings, fallback 60 min)
        this.provisioningTimeoutMs = options.provisioningTimeoutMs || 60 * 60 * 1000;
        this.provisioningTimer = null;

        // Status polling fallback (catches missed WebSocket updates)
        this.statusPollInterval = null;
        this.statusPollDelay = 30000; // 30 seconds

        // Launch UI elements (not present in viewOnly mode)
        if (!this.viewOnly) {
            // Scenario dropdown
            this.scenarioDropdown = document.getElementById('scenario-dropdown');
            this.scenarioSelect = document.getElementById('scenario-select-value');

            // OS selection (for from_agent scenarios)
            this.osSelectionSection = document.getElementById('os-selection-section');
            this.osDropdown = document.getElementById('os-dropdown');
            this.osSelect = document.getElementById('os-select-value');

            // General agent dropdown (filtered by OS selection)
            this.agentSection = document.getElementById('agent-section');
            this.agentDropdown = document.getElementById('agent-dropdown');
            this.agentSelect = document.getElementById('agent-select-value');
            this.agentItems = document.getElementById('agent-items');

            // Windows agent dropdown (for requires_windows scenarios)
            this.windowsAgentSection = document.getElementById('windows-agent-section');
            this.windowsAgentDropdown = document.getElementById('windows-agent-dropdown');
            this.windowsAgentSelect = document.getElementById('windows-agent-select-value');
            this.windowsAgentItems = document.getElementById('windows-agent-items');

            // Linux agent dropdown (for requires_linux scenarios)
            this.linuxAgentSection = document.getElementById('linux-agent-section');
            this.linuxAgentDropdown = document.getElementById('linux-agent-dropdown');
            this.linuxAgentSelect = document.getElementById('linux-agent-select-value');
            this.linuxAgentItems = document.getElementById('linux-agent-items');

            // Launch button
            this.launchBtn = document.getElementById('launch-btn');

            // Scenario requirements cache
            this.scenarioRequirements = {};

            // Scenario data cache (for info panel)
            this.scenarioData = {};

            // Scenario info panel elements
            this.scenarioInfoPanel = document.getElementById('scenario-info-panel');
            this.scenarioInfoTitle = document.getElementById('scenario-info-title');
            this.scenarioInfoDescription = document.getElementById('scenario-info-description');
        }

        // Range tiles
        this.launchTile = document.getElementById('launch-tile');
        this.rangeTiles = [
            document.getElementById('range-tile-1'),
            document.getElementById('range-tile-2'),
            document.getElementById('range-tile-3'),
        ];

        // Templates for range states
        this.provisioningTemplate = document.getElementById('provisioning-template');
        this.activeTemplate = document.getElementById('active-template');
        this.pausedTemplate = document.getElementById('paused-template');
        this.failedTemplate = document.getElementById('failed-template');

        this._bindEvents();
        this._bindCleanup();
    }

    _bindEvents() {
        // OS dropdown change - filter agents by selected OS
        if (this.osDropdown) {
            this.osDropdown.addEventListener('change', (e) => {
                this._onOsChange(e.detail?.value);
            });
        }

        // Agent dropdown change
        if (this.agentDropdown) {
            this.agentDropdown.addEventListener('change', () => {
                this._updateLaunchButtonState();
            });
        }

        // Windows agent dropdown change
        if (this.windowsAgentDropdown) {
            this.windowsAgentDropdown.addEventListener('change', () => {
                this._updateLaunchButtonState();
            });
        }

        // Linux agent dropdown change
        if (this.linuxAgentDropdown) {
            this.linuxAgentDropdown.addEventListener('change', () => {
                this._updateLaunchButtonState();
            });
        }

        // Scenario dropdown change
        if (this.scenarioDropdown) {
            this.scenarioDropdown.addEventListener('change', (e) => {
                this._onScenarioChange(e.detail?.value);
            });
        }

        // Launch button (always present in launch tile)
        if (this.launchBtn) {
            this.launchBtn.addEventListener('click', () => this.launchRange());
        }

        // Cancel button (provisioning state)
        if (this.cancelBtn) {
            this.cancelBtn.addEventListener('click', () => this.cancelRange());
        }

        // Destroy buttons
        if (this.destroyBtn) {
            this.destroyBtn.addEventListener('click', () => this.destroyRange());
        }
        if (this.destroyPausedBtn) {
            this.destroyPausedBtn.addEventListener('click', () => this.destroyRange());
        }

        // Pause button
        if (this.pauseBtn) {
            this.pauseBtn.addEventListener('click', () => this.pauseRange());
        }

        // Resume button
        if (this.resumeBtn) {
            this.resumeBtn.addEventListener('click', () => this.resumeRange());
        }

        // Dismiss error button
        if (this.dismissErrorBtn) {
            this.dismissErrorBtn.addEventListener('click', () => this.dismissError());
        }
    }

    async init() {
        if (this.viewOnly) {
            // CTF participants: only load range status, no launch UI
            await this.loadRange();
            return;
        }

        // Initialize dropdowns
        this._initScenarioDropdown();
        this._initDropdown(this.osDropdown);

        // Load scenarios first (needs to complete before agents for _onScenarioChange)
        // Then load agents and range status in parallel
        await this.loadScenarios();
        await Promise.all([
            this.loadAgents(),
            this.loadRange(),
        ]);
    }

    async loadRange() {
        const data = await this._fetchJson(this.rangeUrl, 'Failed to load range');
        if (!data) {
            return;
        }

        this.currentRange = data.range;
        this.currentRaesProjection = data.raes_projection || null;
        this.currentRaesParticipantRuntime = data.raes_participant_runtime || null;
        this._updateUI();

        // Connect WebSocket if in a transitional state
        if (this.currentRange && this._isTransitionalState(this.currentRange.status)) {
            this._connectStatusSocket(this.currentRange.request_id);
        }
    }

    async launchRange() {
        const scenario = this.scenarioSelect?.value || 'basic';
        const req = this.scenarioRequirements[scenario] || {}; // eslint-disable-line security/detect-object-injection

        // Build agents dict based on scenario requirements
        const agents = {};

        // Check for OS-picked agent (from_agent scenarios)
        if (this.osSelect?.value && this.agentSelect?.value) {
            const osType = this.osSelect.value;
            agents[osType] = Number.parseInt(this.agentSelect.value, 10); // eslint-disable-line security/detect-object-injection
        }

        // Check for fixed Windows agent requirement
        if (req.requires_windows && this.windowsAgentSelect?.value) {
            agents.windows = Number.parseInt(this.windowsAgentSelect.value, 10);
        }

        // Check for fixed Linux agent requirement
        if (req.requires_linux && this.linuxAgentSelect?.value) {
            agents.linux = Number.parseInt(this.linuxAgentSelect.value, 10);
        }

        // Validate we have required agents (scenarios without agent requirements can proceed)
        const requiresAgents = req.has_from_agent || req.requires_windows || req.requires_linux;
        if (requiresAgents && Object.keys(agents).length === 0) {
            return;
        }

        this.launchBtn.disabled = true;
        this.launchBtn.textContent = 'Launching...';

        // Build request body with new agents format
        const body = {
            agents: agents,
            scenario: scenario,
        };

        try {
            const response = await fetch(this.launchUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify(body),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to launch range');
            }

            this.currentRange = data.range;
            this.currentRaesProjection = data.raes_projection || null;
            this.currentRaesParticipantRuntime = data.raes_participant_runtime || null;
            this._updateUI();
            this._connectStatusSocket(data.range.request_id);

        } catch (error) {
            alert(error.message);
            // Sync UI with CMS state (handles "already has active range" case)
            await this.loadRange();
            this.launchBtn.disabled = false;
            this.launchBtn.textContent = 'Launch Range';
        }
    }

    async cancelRange() {
        if (!confirm('Are you sure you want to cancel range provisioning?')) {
            return;
        }

        try {
            const response = await fetch(this.cancelUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify({ request_id: this.currentRange.request_id }),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to cancel range');
            }

            this._closeStatusSocket();
            this.currentRange = null;
            this.currentRaesProjection = null;
            this.currentRaesParticipantRuntime = null;
            this._updateUI();

        } catch (error) {
            alert(error.message);
        }
    }

    async destroyRange() {
        if (!confirm('Are you sure you want to destroy this range? This cannot be undone.')) {
            return;
        }

        try {
            const response = await fetch(this.destroyUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify({ request_id: this.currentRange.request_id }),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to destroy range');
            }

            // Range is destroyed immediately - show no-range state
            this._closeStatusSocket();
            this.currentRange = null;
            this.currentRaesProjection = null;
            this.currentRaesParticipantRuntime = null;
            this._updateUI();

        } catch (error) {
            alert(error.message);
        }
    }

    async pauseRange() {
        if (!confirm('Are you sure you want to pause this range? Instances will be stopped.')) {
            return;
        }

        // Disable button to prevent double-clicks during request
        const pauseBtn = document.querySelector('#pause-btn');
        if (pauseBtn) {
            pauseBtn.disabled = true;
            pauseBtn.textContent = 'Pausing...';
        }

        try {
            const response = await fetch(this.pauseUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify({ request_id: this.currentRange.request_id }),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to pause range');
            }

            // Update local state to pausing and connect WebSocket for updates
            this.currentRange.status = 'pausing';
            this._updateUI();
            this._connectStatusSocket(this.currentRange.request_id);

        } catch (error) {
            alert(error.message);
            // Re-enable button on failure
            if (pauseBtn) {
                pauseBtn.disabled = false;
                pauseBtn.textContent = 'Pause';
            }
        }
    }

    async resumeRange() {
        if (!confirm('Are you sure you want to resume this range?')) {
            return;
        }

        // Disable button to prevent double-clicks during request
        const resumeBtn = document.querySelector('#resume-btn');
        if (resumeBtn) {
            resumeBtn.disabled = true;
            resumeBtn.textContent = 'Resuming...';
        }

        try {
            const response = await fetch(this.resumeUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify({ request_id: this.currentRange.request_id }),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to resume range');
            }

            // Update local state to resuming and connect WebSocket for updates
            this.currentRange.status = 'resuming';
            this._updateUI();
            this._connectStatusSocket(this.currentRange.request_id);

        } catch (error) {
            alert(error.message);
            // Re-enable button on failure
            if (resumeBtn) {
                resumeBtn.disabled = false;
                resumeBtn.textContent = 'Resume';
            }
        }
    }

    dismissError() {
        // Clear the current range and show no-range state
        this._closeStatusSocket();
        this.currentRange = null;
        this.currentRaesProjection = null;
        this.currentRaesParticipantRuntime = null;
        this._updateUI();
    }
}

// Export for use in templates
globalThis.DashboardManager = DashboardManager;
