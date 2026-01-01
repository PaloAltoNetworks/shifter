/**
 * Dashboard - Range launch and management
 *
 * Handles:
 * - Loading agents for dropdown
 * - Launching ranges
 * - Polling for status updates
 * - Cancel/destroy actions
 */

class DashboardManager {
    constructor(options) {
        this.csrfToken = options.csrfToken;
        this.statusUrl = options.statusUrl;
        this.launchUrl = options.launchUrl;
        this.cancelUrl = options.cancelUrl;
        this.destroyUrl = options.destroyUrl;
        this.agentsUrl = options.agentsUrl;
        this.loginUrl = options.loginUrl || '/oidc/authenticate/';

        // State
        this.currentRange = null;
        this.pollInterval = null;
        this.pollIntervalMs = 2000; // Poll every 2 seconds
        this.pollErrorCount = 0;
        this.maxPollErrors = 5; // Force refresh after 5 consecutive errors
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
        this._stopPolling();
        globalThis.location.href = this.loginUrl;
    }

    _bindCleanup() {
        // Clean up polling on page unload to prevent memory leaks
        window.addEventListener('beforeunload', () => {
            this._stopPolling();
        });

        // Also clean up on visibility change (tab hidden)
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this._stopPolling();
            } else if (this.currentRange && this._isTransitionalState(this.currentRange.status)) {
                // Resume polling when tab becomes visible again if in transitional state
                // Do an immediate status check since state may have changed while hidden
                this.loadStatus();
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
            this.loadStatus(),
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

    async loadStatus() {
        const data = await this._fetchJson(this.statusUrl, 'Failed to load status');
        if (!data) {
            return;
        }

        this.currentRange = data.range;
        this._updateUI();

        // Start polling if in a transitional state
        if (this.currentRange && this._isTransitionalState(this.currentRange.status)) {
            this._startPolling();
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
        const rangeStarted = document.getElementById('range-started');
        const rangeAgent = document.getElementById('range-agent');

        if (rangeStarted && this.currentRange.ready_at) {
            rangeStarted.textContent = this._formatDate(this.currentRange.ready_at);
        }
        if (rangeAgent && this.currentRange.agent_name) {
            rangeAgent.textContent = this.currentRange.agent_name;
        }

        // Update NGFW details - show link to NGFW detail page if range has linked NGFW
        const ngfwDetails = document.getElementById('ngfw-details');
        if (ngfwDetails) {
            if (this.currentRange.ngfw_id) {
                ngfwDetails.style.display = 'block';
                const ngfwLink = document.getElementById('ngfw-detail-link');
                if (ngfwLink) {
                    ngfwLink.href = `/mission-control/assets/ngfw/${this.currentRange.ngfw_id}/`;
                }
            } else {
                ngfwDetails.style.display = 'none';
            }
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
            this._startPolling();

        } catch (error) {
            alert(error.message);
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
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to cancel range');
            }

            this._stopPolling();
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
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to destroy range');
            }

            // Range is destroyed immediately - show no-range state
            this._stopPolling();
            this.currentRange = null;
            this._updateUI();

        } catch (error) {
            alert(error.message);
        }
    }

    dismissError() {
        // Clear the current range and show no-range state
        this.currentRange = null;
        this._updateUI();
    }

    _startPolling() {
        if (this.pollInterval) return;

        this.pollInterval = setInterval(() => {
            this._pollStatus();
        }, this.pollIntervalMs);
    }

    _stopPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
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

    async _pollStatus() {
        const response = await this._fetchStatusResponse();
        if (!response) {
            return;
        }

        if (!response.ok) {
            this._handlePollError(response.status);
            return;
        }

        this.pollErrorCount = 0;
        const data = await response.json();
        const oldStatus = this._applyRangeUpdate(data.range, true);
        this._stopPollingIfStable(oldStatus);
    }

    async _fetchStatusResponse() {
        try {
            const response = await fetch(this.statusUrl, {
                headers: { 'Accept': 'application/json' },
            });

            if (this._isSessionExpired(response)) {
                this._handleSessionExpired();
                return null;
            }

            return response;
        } catch (error) {
            if (error instanceof TypeError && error.message.includes('Failed to fetch')) {
                console.warn('Polling fetch failed, likely session expired');
                this._handleSessionExpired();
                return null;
            }
            console.error('Polling error:', error);
            return null;
        }
    }

    _handlePollError(status) {
        console.warn('Polling: response not ok', status);
        this.pollErrorCount++;
        if (this.pollErrorCount >= this.maxPollErrors) {
            console.error('Too many polling errors, reloading page');
            globalThis.location.reload();
        }
    }

    _applyRangeUpdate(range, logTransition) {
        const oldStatus = this.currentRange?.status;
        const newStatus = range?.status;
        this.currentRange = range;
        this._updateUI();

        if (logTransition && oldStatus !== newStatus) {
            console.log(`Range status: ${oldStatus} → ${newStatus ?? 'null (no range)'}`);
        }

        return oldStatus;
    }

    _stopPollingIfStable(oldStatus) {
        if (this.currentRange && this._isTransitionalState(this.currentRange.status)) {
            return;
        }

        this._stopPolling();

        if (oldStatus && this.currentRange) {
            if (oldStatus === 'provisioning' && this.currentRange.status === 'ready') {
                console.log('Range is ready!');
            }
        }
    }
}

// Export for use in templates
window.DashboardManager = DashboardManager;
