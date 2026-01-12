/**
 * Dashboard - Range launch and management
 *
 * Handles:
 * - Loading agents for dropdown
 * - Launching ranges
 * - Real-time status updates via WebSocket
 * - Cancel/destroy actions
 */

class DashboardManager {
    constructor(options) {
        this.csrfToken = options.csrfToken;
        this.rangeUrl = options.rangeUrl;
        this.launchUrl = options.launchUrl;
        this.cancelUrl = options.cancelUrl;
        this.destroyUrl = options.destroyUrl;
        this.pauseUrl = options.pauseUrl;
        this.resumeUrl = options.resumeUrl;
        this.agentsUrl = options.agentsUrl;
        this.scenariosUrl = options.scenariosUrl;
        this.loginUrl = options.loginUrl || '/oidc/authenticate/';

        // State
        this.currentRange = null;
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

        // UI Elements
        this.noRangeState = document.getElementById('no-range-state');
        this.provisioningState = document.getElementById('provisioning-state');
        this.activeRangeState = document.getElementById('active-range-state');
        this.pausedRangeState = document.getElementById('paused-range-state');
        this.failedState = document.getElementById('failed-state');

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

        // Buttons
        this.launchBtn = document.getElementById('launch-btn');
        this.cancelBtn = document.getElementById('cancel-btn');
        this.pauseBtn = document.getElementById('pause-btn');
        this.destroyBtn = document.getElementById('destroy-btn');
        this.resumeBtn = document.getElementById('resume-btn');
        this.destroyPausedBtn = document.getElementById('destroy-paused-btn');
        this.dismissErrorBtn = document.getElementById('dismiss-error-btn');

        // Scenario requirements cache
        this.scenarioRequirements = {};

        this._bindEvents();
        this._bindCleanup();
    }

    /**
     * Check if a fetch response indicates session expiration.
     * This happens when the server redirects to Cognito for re-auth.
     */
    _isSessionExpired(response) {
        // If we got redirected to a different origin (Cognito), session expired
        if (response.redirected && response.url.includes('cognito')) {
            return true;
        }
        // Also check for 401/403 which might indicate auth issues
        if (response.status === 401 || response.status === 403) {
            return true;
        }
        return false;
    }

    /**
     * Redirect to login page when session expires.
     */
    _handleSessionExpired() {
        console.log('Session expired, redirecting to login...');
        this._closeStatusSocket();
        globalThis.location.href = this.loginUrl;
    }

    _bindCleanup() {
        // Clean up WebSocket on page unload to prevent memory leaks
        window.addEventListener('beforeunload', () => {
            this._closeStatusSocket();
        });

        // Also clean up on visibility change (tab hidden)
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this._closeStatusSocket();
            } else if (this.currentRange && this._isTransitionalState(this.currentRange.status)) {
                // Reconnect WebSocket when tab becomes visible again if in transitional state
                this._connectStatusSocket(this.currentRange.request_id);
            }
        });
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

        // Launch button
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

    /**
     * Handle scenario dropdown change.
     * Shows/hides agent sections based on scenario requirements.
     */
    _onScenarioChange(scenario) {
        const req = this.scenarioRequirements[scenario] || {};

        // Hide all agent sections first
        this._hideAllAgentSections();

        // Clear all agent selections
        this._clearAgentSelections();

        // Show appropriate sections based on requirements
        if (req.has_from_agent && !req.requires_windows && !req.requires_linux) {
            // Only from_agent instances - show OS picker first
            if (this.osSelectionSection) {
                this.osSelectionSection.style.display = 'block';
            }
            // Agent dropdown shown after OS selection
        } else {
            // Fixed OS requirements
            if (req.requires_windows) {
                if (this.windowsAgentSection) {
                    this.windowsAgentSection.style.display = 'block';
                }
            }
            if (req.requires_linux) {
                if (this.linuxAgentSection) {
                    this.linuxAgentSection.style.display = 'block';
                }
            }
            // If has_from_agent AND fixed requirements, show OS picker too
            if (req.has_from_agent) {
                if (this.osSelectionSection) {
                    this.osSelectionSection.style.display = 'block';
                }
            }
        }

        this._updateLaunchButtonState();
    }

    /**
     * Handle OS selection change.
     * Filters agent dropdown by selected OS.
     */
    _onOsChange(osType) {
        if (!osType) return;

        // Show the agent section
        if (this.agentSection) {
            this.agentSection.style.display = 'block';
        }

        // Filter agents by OS
        const filteredAgents = this.agents.filter(agent => {
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
        this._resetDropdownDisplay(this.agentDropdown, '-- Select an agent --');

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
        const trigger = dropdown.querySelector('.xdr-dropdown-value');
        if (trigger) {
            trigger.textContent = placeholder;
            trigger.classList.add('placeholder');
        }
        // Clear selected state
        const items = dropdown.querySelectorAll('.xdr-dropdown-item');
        items.forEach(item => item.classList.remove('selected'));
    }

    async init() {
        // Initialize dropdowns
        this._initScenarioDropdown();
        this._initDropdown(this.osDropdown);

        // Load scenarios, agents and current status in parallel
        await Promise.all([
            this.loadScenarios(),
            this.loadAgents(),
            this.loadRange(),
        ]);
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
        if (!data || !data.scenarios) {
            return;
        }

        // Cache agent requirements by scenario ID
        for (const scenario of data.scenarios) {
            this.scenarioRequirements[scenario.id] = scenario.agent_requirements || {};
        }
    }

    _initScenarioDropdown() {
        // Initialize the scenario dropdown with XdrDropdown if available
        this._initDropdown(this.scenarioDropdown);
    }

    _updateLaunchButtonState() {
        if (!this.launchBtn) return;

        const scenario = this.scenarioSelect?.value || 'basic';
        const req = this.scenarioRequirements[scenario] || {};

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

    async loadRange() {
        const data = await this._fetchJson(this.rangeUrl, 'Failed to load range');
        if (!data) {
            return;
        }

        this.currentRange = data.range;
        this._updateUI();

        // Connect WebSocket if in a transitional state
        if (this.currentRange && this._isTransitionalState(this.currentRange.status)) {
            this._connectStatusSocket(this.currentRange.request_id);
        }
    }

    _isTransitionalState(status) {
        return ['pending', 'provisioning', 'pausing', 'resuming'].includes(status);
    }

    _updateUI() {
        // Hide all states first
        this.noRangeState.style.display = 'none';
        this.provisioningState.style.display = 'none';
        this.activeRangeState.style.display = 'none';
        this.pausedRangeState.style.display = 'none';
        if (this.failedState) {
            this.failedState.style.display = 'none';
        }

        if (!this.currentRange) {
            this.noRangeState.style.display = 'block';
            this._resetLaunchButton();
            return;
        }

        switch (this.currentRange.status) {
            case 'pending':
            case 'provisioning':
                this.provisioningState.style.display = 'block';
                this._updateProvisioningState();
                break;

            case 'ready':
                this.activeRangeState.style.display = 'block';
                this._updateActiveState();
                break;

            case 'paused':
                this.pausedRangeState.style.display = 'block';
                this._updatePausedState();
                break;

            case 'pausing':
                this.provisioningState.style.display = 'block';
                this._updateProvisioningState('Pausing Range', 'Stopping instances...');
                break;

            case 'resuming':
                this.provisioningState.style.display = 'block';
                this._updateProvisioningState('Resuming Range', 'Starting instances...');
                break;

            case 'failed':
                if (this.failedState) {
                    this.failedState.style.display = 'block';
                    this._updateFailedState();
                } else {
                    // Fallback to no-range state if failed state doesn't exist
                    this.noRangeState.style.display = 'block';
                    alert(`Range provisioning failed: ${this.currentRange.error_message}`);
                }
                break;

            default:
                // destroyed or unknown - show no range
                this.noRangeState.style.display = 'block';
        }
    }

    _updateProvisioningState(title = 'Provisioning Range', message = 'Setting up infrastructure...') {
        const cardTitle = this.provisioningState.querySelector('.card-title');
        if (cardTitle) {
            cardTitle.textContent = title;
        }
        const statusText = this.provisioningState.querySelector('.status span:last-child');
        if (statusText) {
            statusText.textContent = message;
        }
    }

    _updateActiveState() {
        const rangeAgent = document.getElementById('range-agent');

        if (rangeAgent && this.currentRange.agent_name) {
            rangeAgent.textContent = this.currentRange.agent_name;
        }
    }

    _isValidHttpUrl(urlString) {
        try {
            const url = new URL(urlString);
            return url.protocol === 'http:' || url.protocol === 'https:';
        } catch {
            return false;
        }
    }

    _updatePausedState() {
        const pausedAt = document.getElementById('range-paused-at');
        const pausedAgent = document.getElementById('paused-range-agent');

        if (pausedAt && this.currentRange.paused_at) {
            pausedAt.textContent = this._formatDate(this.currentRange.paused_at);
        }
        if (pausedAgent && this.currentRange.agent_name) {
            pausedAgent.textContent = this.currentRange.agent_name;
        }
    }

    _updateFailedState() {
        const errorMessage = document.getElementById('error-message');
        if (errorMessage && this.currentRange.error_message) {
            errorMessage.textContent = this.currentRange.error_message;
        }
    }

    _formatDate(isoString) {
        const date = new Date(isoString);
        return date.toLocaleString();
    }

    _resetLaunchButton() {
        if (this.launchBtn) {
            this.launchBtn.textContent = 'Launch Range';
            this._updateLaunchButtonState();
        }
    }

    async launchRange() {
        const scenario = this.scenarioSelect?.value || 'basic';
        const req = this.scenarioRequirements[scenario] || {};

        // Build agents dict based on scenario requirements
        const agents = {};

        // Check for OS-picked agent (from_agent scenarios)
        if (this.osSelect?.value && this.agentSelect?.value) {
            const osType = this.osSelect.value;
            agents[osType] = Number.parseInt(this.agentSelect.value, 10);
        }

        // Check for fixed Windows agent requirement
        if (req.requires_windows && this.windowsAgentSelect?.value) {
            agents.windows = Number.parseInt(this.windowsAgentSelect.value, 10);
        }

        // Check for fixed Linux agent requirement
        if (req.requires_linux && this.linuxAgentSelect?.value) {
            agents.linux = Number.parseInt(this.linuxAgentSelect.value, 10);
        }

        // Validate we have at least one agent
        if (Object.keys(agents).length === 0) {
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
            this._updateUI();

        } catch (error) {
            alert(error.message);
        }
    }

    async pauseRange() {
        if (!confirm('Are you sure you want to pause this range? Instances will be stopped.')) {
            return;
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
        }
    }

    async resumeRange() {
        if (!confirm('Are you sure you want to resume this range?')) {
            return;
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
        }
    }

    dismissError() {
        // Clear the current range and show no-range state
        this._closeStatusSocket();
        this.currentRange = null;
        this._updateUI();
    }

    /**
     * Build WebSocket URL for range status updates.
     * Uses wss:// for https:// pages, ws:// for http://.
     * @param {string} requestId - UUID of the request
     */
    _buildWebSocketUrl(requestId) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${window.location.host}/ws/range-status/${requestId}/`;
    }

    /**
     * Connect to WebSocket for real-time range status updates.
     * @param {string} requestId - UUID of the request
     * @param {boolean} isReconnect - Whether this is a reconnect attempt (preserves retry counters)
     */
    _connectStatusSocket(requestId, isReconnect = false) {
        // Close existing connection if any, but preserve retry counters on reconnect
        this._closeStatusSocket(!isReconnect);

        const wsUrl = this._buildWebSocketUrl(requestId);
        console.log(`Connecting to WebSocket: ${wsUrl}`);

        this.statusSocket = new WebSocket(wsUrl);

        // Start provisioning timeout timer
        this.provisioningTimer = setTimeout(() => {
            this._handleProvisioningTimeout();
        }, this.provisioningTimeoutMs);

        // Start polling fallback for missed WebSocket updates
        this._startStatusPolling();

        this.statusSocket.onopen = () => {
            console.log('WebSocket connected for range status');
            this.reconnectAttempts = 0;
            this.reconnectDelay = 1000;
        };

        this.statusSocket.onmessage = (event) => {
            this._handleStatusMessage(event);
        };

        this.statusSocket.onclose = (event) => {
            this._handleSocketClose(event, requestId);
        };

        this.statusSocket.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    /**
     * Handle incoming WebSocket message with status update.
     */
    _handleStatusMessage(event) {
        try {
            const data = JSON.parse(event.data);

            if (data.type === 'status') {
                const newStatus = data.status;
                console.log(`Range status received: ${newStatus}`);

                // Update current range status
                if (this.currentRange) {
                    this.currentRange.status = newStatus;
                    if (data.error_message) {
                        this.currentRange.error_message = data.error_message;
                    }
                }

                this._updateUI();

                // Close socket if we've reached a stable state
                if (!this._isTransitionalState(newStatus)) {
                    console.log('Range reached stable state, closing WebSocket');
                    this._clearProvisioningTimer();
                    this._closeStatusSocket();
                }
            }
        } catch (error) {
            console.error('Error parsing WebSocket message:', error);
        }
    }

    /**
     * Handle WebSocket close - attempt reconnect if appropriate.
     * @param {CloseEvent} event - WebSocket close event
     * @param {string} requestId - UUID of the request for reconnection
     */
    _handleSocketClose(event, requestId) {
        console.log(`WebSocket closed: code=${event.code}, reason=${event.reason}`);

        // Don't reconnect if intentionally closed or auth failed
        if (event.code === 1000 || event.code === 4001 || event.code === 4003) {
            return;
        }

        // Don't reconnect if we're no longer in a transitional state
        if (!this.currentRange || !this._isTransitionalState(this.currentRange.status)) {
            return;
        }

        // Attempt reconnect with exponential backoff
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`Reconnecting (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${this.reconnectDelay}ms`);

            setTimeout(() => {
                if (this.currentRange && this._isTransitionalState(this.currentRange.status)) {
                    this._connectStatusSocket(requestId, true);
                }
            }, this.reconnectDelay);

            // Exponential backoff: 1s, 2s, 4s, 8s, 16s
            this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
        } else {
            console.error('Max reconnect attempts reached, falling back to page reload');
            globalThis.location.reload();
        }
    }

    /**
     * Close WebSocket connection cleanly.
     * @param {boolean} resetRetry - Whether to reset reconnect counters (default true)
     */
    _closeStatusSocket(resetRetry = true) {
        this._clearProvisioningTimer();
        this._stopStatusPolling();
        if (this.statusSocket) {
            this.statusSocket.onclose = null; // Prevent reconnect attempt
            this.statusSocket.close(1000, 'Client closing');
            this.statusSocket = null;
        }
        if (resetRetry) {
            this.reconnectAttempts = 0;
            this.reconnectDelay = 1000;
        }
    }

    /**
     * Clear the provisioning timeout timer.
     */
    _clearProvisioningTimer() {
        if (this.provisioningTimer) {
            clearTimeout(this.provisioningTimer);
            this.provisioningTimer = null;
        }
    }

    /**
     * Start periodic polling for range status as fallback for missed WebSocket updates.
     * Polling continues even when tab is hidden to ensure status is fresh when user returns.
     */
    _startStatusPolling() {
        // Don't start if already polling
        if (this.statusPollInterval) return;

        this.statusPollInterval = setInterval(async () => {
            // Skip if no current range or not in transitional state
            if (!this.currentRange || !this._isTransitionalState(this.currentRange.status)) {
                this._stopStatusPolling();
                return;
            }

            const data = await this._fetchJson(this.rangeUrl, 'Status poll failed');
            if (!data || !data.range) return;

            const polledStatus = data.range.status;

            // If we discovered a stable state via poll (missed WebSocket update)
            if (!this._isTransitionalState(polledStatus)) {
                console.log(`Poll detected stable state: ${polledStatus}`);
                this.currentRange = data.range;
                this._updateUI();
                this._closeStatusSocket(); // This also stops polling
            }
        }, this.statusPollDelay);
    }

    /**
     * Stop periodic status polling.
     */
    _stopStatusPolling() {
        if (this.statusPollInterval) {
            clearInterval(this.statusPollInterval);
            this.statusPollInterval = null;
        }
    }

    /**
     * Handle provisioning timeout - show failed state.
     */
    _handleProvisioningTimeout() {
        console.error('Provisioning timed out');
        this._closeStatusSocket();
        if (this.currentRange) {
            this.currentRange.status = 'failed';
            this.currentRange.error_message = 'Provisioning timed out';
        }
        this._updateUI();
    }

    _initDropdown(dropdown) {
        if (!dropdown || !window.XdrDropdown) {
            return null;
        }

        if (typeof window.XdrDropdown.init === 'function') {
            return window.XdrDropdown.init(dropdown);
        }

        return new window.XdrDropdown(dropdown);
    }

    _populateWindowsAgentDropdown(agents) {
        if (!this.windowsAgentItems) {
            return;
        }

        const windowsAgents = agents.filter(agent => agent.os_slug === 'windows');
        if (windowsAgents.length === 0) {
            this._renderEmptyDropdown(this.windowsAgentItems, 'No Windows agents');
        } else {
            this._renderAgentItems(this.windowsAgentItems, windowsAgents);
        }

        this._initDropdown(this.windowsAgentDropdown);
    }

    _populateLinuxAgentDropdown(agents) {
        if (!this.linuxAgentItems) {
            return;
        }

        const linuxAgents = agents.filter(agent => agent.os_slug !== 'windows');
        if (linuxAgents.length === 0) {
            this._renderEmptyDropdown(this.linuxAgentItems, 'No Linux agents');
        } else {
            this._renderAgentItems(this.linuxAgentItems, linuxAgents);
        }

        this._initDropdown(this.linuxAgentDropdown);
    }

    _renderAgentItems(container, agents) {
        container.innerHTML = '';

        for (const agent of agents) {
            const li = document.createElement('li');
            li.className = 'xdr-dropdown-item';
            li.dataset.value = agent.id;
            li.textContent = `${agent.name} (${agent.os_name})`;
            container.appendChild(li);
        }
    }

    _renderEmptyDropdown(container, message) {
        container.innerHTML = '';
        const li = document.createElement('li');
        li.className = 'xdr-dropdown-item disabled';
        li.textContent = message;
        container.appendChild(li);
    }

    async _fetchJson(url, errorMessage) {
        try {
            const response = await fetch(url, {
                headers: { 'Accept': 'application/json' },
            });

            if (this._isSessionExpired(response)) {
                this._handleSessionExpired();
                return null;
            }

            if (!response.ok) {
                console.error(errorMessage);
                return null;
            }

            return await response.json();
        } catch (error) {
            if (error instanceof TypeError && error.message.includes('Failed to fetch')) {
                console.warn('Fetch failed, likely session expired');
                this._handleSessionExpired();
                return null;
            }
            console.error(errorMessage, error);
            return null;
        }
    }
}

// Export for use in templates
window.DashboardManager = DashboardManager;
