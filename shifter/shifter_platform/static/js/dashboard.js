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
        this.agentsUrl = options.agentsUrl;
        this.loginUrl = options.loginUrl || '/oidc/authenticate/';

        // State
        this.currentRange = null;
        this.statusSocket = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000; // Start with 1 second
        this.agents = []; // Cached agent list with os_slug

        // UI Elements
        this.noRangeState = document.getElementById('no-range-state');
        this.provisioningState = document.getElementById('provisioning-state');
        this.activeRangeState = document.getElementById('active-range-state');
        this.pausedRangeState = document.getElementById('paused-range-state');
        this.failedState = document.getElementById('failed-state');

        this.agentDropdown = document.getElementById('agent-dropdown');
        this.agentSelect = document.getElementById('agent-select-value');
        this.agentItems = document.getElementById('agent-items');
        this.scenarioDropdown = document.getElementById('scenario-dropdown');
        this.scenarioSelect = document.getElementById('scenario-select-value');
        this.dcAgentSection = document.getElementById('dc-agent-section');
        this.dcAgentDropdown = document.getElementById('dc-agent-dropdown');
        this.dcAgentSelect = document.getElementById('dc-agent-select-value');
        this.dcAgentItems = document.getElementById('dc-agent-items');
        this.launchBtn = document.getElementById('launch-btn');
        this.cancelBtn = document.getElementById('cancel-btn');
        this.pauseBtn = document.getElementById('pause-btn');
        this.destroyBtn = document.getElementById('destroy-btn');
        this.resumeBtn = document.getElementById('resume-btn');
        this.destroyPausedBtn = document.getElementById('destroy-paused-btn');
        this.dismissErrorBtn = document.getElementById('dismiss-error-btn');

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
                this._connectStatusSocket(this.currentRange.id);
            }
        });
    }

    _bindEvents() {
        // Agent dropdown change
        if (this.agentDropdown) {
            this.agentDropdown.addEventListener('change', () => {
                this._updateLaunchButtonState();
            });
        }

        // DC Agent dropdown change
        if (this.dcAgentDropdown) {
            this.dcAgentDropdown.addEventListener('change', () => {
                this._updateLaunchButtonState();
            });
        }

        // Scenario dropdown change
        if (this.scenarioDropdown) {
            this.scenarioDropdown.addEventListener('change', (e) => {
                this._onScenarioChange(e.detail.value);
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

        // Dismiss error button
        if (this.dismissErrorBtn) {
            this.dismissErrorBtn.addEventListener('click', () => this.dismissError());
        }
    }

    /**
     * Handle scenario dropdown change.
     * AD scenario uses same agent for DC and victim (no separate DC agent needed).
     */
    _onScenarioChange(_scenario) {
        // DC agent section is not needed - same agent used for DC and victim
        // Keep it hidden for all scenarios
        if (this.dcAgentSection) {
            this.dcAgentSection.style.display = 'none';
        }
        if (this.dcAgentSelect) {
            this.dcAgentSelect.value = '';
        }
        this._updateLaunchButtonState();
    }

    /**
     * Reset DC agent dropdown to placeholder state.
     */
    _resetDcAgentDropdown() {
        if (this.dcAgentDropdown) {
            const trigger = this.dcAgentDropdown.querySelector('.xdr-dropdown-value');
            if (trigger) {
                trigger.textContent = '-- Select a Windows agent --';
                trigger.classList.add('placeholder');
            }
            // Clear selected state
            const items = this.dcAgentDropdown.querySelectorAll('.xdr-dropdown-item');
            items.forEach(item => item.classList.remove('selected'));
        }
    }

    async init() {
        // Initialize scenario dropdown
        this._initScenarioDropdown();

        // Load agents and current status in parallel
        await Promise.all([
            this.loadAgents(),
            this.loadRange(),
        ]);
    }

    _initScenarioDropdown() {
        // Initialize the scenario dropdown with XdrDropdown if available
        this._initDropdown(this.scenarioDropdown);
    }

    _updateLaunchButtonState() {
        if (!this.launchBtn) return;

        const hasAgent = Boolean(this.agentSelect?.value);
        // Launch is enabled if agent is selected
        this.launchBtn.disabled = !hasAgent;
    }

    async loadAgents() {
        const data = await this._fetchJson(this.agentsUrl, 'Failed to load agents');
        if (!data) {
            return;
        }

        // Cache agents for later reference
        this.agents = data.agents || [];

        this._populateAgentDropdown(this.agents);
        this._populateDcAgentDropdown(this.agents);
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
            this._connectStatusSocket(this.currentRange.id);
        }
    }

    _isTransitionalState(status) {
        return ['pending', 'provisioning', 'resuming', 'destroying'].includes(status);
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

            case 'resuming':
                this.provisioningState.style.display = 'block';
                this._updateProvisioningState('Resuming Range', 'Starting instances...');
                break;

            case 'destroying':
                this.provisioningState.style.display = 'block';
                this._updateProvisioningState('Destroying Range', 'Cleaning up resources...');
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
        const agentId = this.agentSelect?.value;
        if (!agentId) return;

        const scenario = this.scenarioSelect?.value || 'basic';

        this.launchBtn.disabled = true;
        this.launchBtn.textContent = 'Launching...';

        // Build request body - backend handles dc_agent for AD scenarios
        const body = {
            agent_id: parseInt(agentId),
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
            this._connectStatusSocket(data.range.id);

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
                body: JSON.stringify({ range_id: this.currentRange.id }),
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
                body: JSON.stringify({ range_id: this.currentRange.id }),
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

    dismissError() {
        // Clear the current range and show no-range state
        this._closeStatusSocket();
        this.currentRange = null;
        this._updateUI();
    }

    /**
     * Build WebSocket URL for range status updates.
     * Uses wss:// for https:// pages, ws:// for http://.
     */
    _buildWebSocketUrl(rangeId) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${window.location.host}/ws/range-status/${rangeId}/`;
    }

    /**
     * Connect to WebSocket for real-time range status updates.
     */
    _connectStatusSocket(rangeId) {
        // Close existing connection if any
        this._closeStatusSocket();

        const wsUrl = this._buildWebSocketUrl(rangeId);
        console.log(`Connecting to WebSocket: ${wsUrl}`);

        this.statusSocket = new WebSocket(wsUrl);

        this.statusSocket.onopen = () => {
            console.log('WebSocket connected for range status');
            this.reconnectAttempts = 0;
            this.reconnectDelay = 1000;
        };

        this.statusSocket.onmessage = (event) => {
            this._handleStatusMessage(event);
        };

        this.statusSocket.onclose = (event) => {
            this._handleSocketClose(event, rangeId);
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
                    this._closeStatusSocket();
                }
            }
        } catch (error) {
            console.error('Error parsing WebSocket message:', error);
        }
    }

    /**
     * Handle WebSocket close - attempt reconnect if appropriate.
     */
    _handleSocketClose(event, rangeId) {
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
                    this._connectStatusSocket(rangeId);
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
     */
    _closeStatusSocket() {
        if (this.statusSocket) {
            this.statusSocket.onclose = null; // Prevent reconnect attempt
            this.statusSocket.close(1000, 'Client closing');
            this.statusSocket = null;
        }
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;
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

    _populateAgentDropdown(agents) {
        if (!this.agentItems) {
            return;
        }

        this._renderAgentItems(this.agentItems, agents);
        this._initDropdown(this.agentDropdown);
    }

    _populateDcAgentDropdown(agents) {
        if (!this.dcAgentItems) {
            return;
        }

        const windowsAgents = agents.filter(agent => agent.os_slug === 'windows');
        if (windowsAgents.length === 0) {
            this._renderEmptyDropdown(this.dcAgentItems, 'No Windows agents uploaded');
        } else {
            this._renderAgentItems(this.dcAgentItems, windowsAgents);
        }

        this._initDropdown(this.dcAgentDropdown);
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
