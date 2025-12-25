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

        // UI Elements
        this.noRangeState = document.getElementById('no-range-state');
        this.provisioningState = document.getElementById('provisioning-state');
        this.activeRangeState = document.getElementById('active-range-state');
        this.pausedRangeState = document.getElementById('paused-range-state');
        this.failedState = document.getElementById('failed-state');

        this.agentDropdown = document.getElementById('agent-dropdown');
        this.agentSelect = document.getElementById('agent-select-value');
        this.agentItems = document.getElementById('agent-items');
        this.ngfwCheckbox = document.getElementById('ngfw-enabled');
        this.ngfwConfigGroup = document.getElementById('ngfw-config-group');
        this.ngfwConfigDropdown = document.getElementById('ngfw-config-dropdown');
        this.ngfwConfigSelect = document.getElementById('ngfw-config-select-value');
        this.ngfwConfigItems = document.getElementById('ngfw-config-items');
        this.ngfwConfigsUrl = options.ngfwConfigsUrl;
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
            this.agentDropdown.addEventListener('change', (e) => {
                this._updateLaunchButtonState();
            });
        }

        // NGFW checkbox toggle
        if (this.ngfwCheckbox) {
            this.ngfwCheckbox.addEventListener('change', () => {
                this._toggleNgfwConfigSection();
            });
        }

        // NGFW config dropdown change
        if (this.ngfwConfigDropdown) {
            this.ngfwConfigDropdown.addEventListener('change', () => {
                this._updateLaunchButtonState();
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

    async init() {
        // Load agents, NGFW configs, and current status in parallel
        await Promise.all([
            this.loadAgents(),
            this.loadNgfwConfigs(),
            this.loadStatus(),
        ]);
    }

    _toggleNgfwConfigSection() {
        if (this.ngfwConfigGroup) {
            this.ngfwConfigGroup.style.display = this.ngfwCheckbox?.checked ? 'block' : 'none';
        }
        this._updateLaunchButtonState();
    }

    _updateLaunchButtonState() {
        if (!this.launchBtn) return;

        const hasAgent = Boolean(this.agentSelect?.value);
        const ngfwEnabled = this.ngfwCheckbox?.checked ?? false;
        const hasNgfwConfig = Boolean(this.ngfwConfigSelect?.value);

        // Launch is enabled if: agent is selected AND (NGFW disabled OR NGFW config selected)
        this.launchBtn.disabled = !hasAgent || (ngfwEnabled && !hasNgfwConfig);
    }

    async loadNgfwConfigs() {
        if (!this.ngfwConfigsUrl || !this.ngfwConfigItems) return;

        try {
            const response = await fetch(this.ngfwConfigsUrl, {
                headers: { 'Accept': 'application/json' },
            });

            if (!response.ok) {
                console.error('Failed to load NGFW configs');
                return;
            }

            const data = await response.json();

            // Clear existing items
            this.ngfwConfigItems.innerHTML = '';

            if (!data.configs || data.configs.length === 0) {
                const li = document.createElement('li');
                li.className = 'xdr-dropdown-item disabled';
                li.textContent = 'No configs available';
                this.ngfwConfigItems.appendChild(li);
            } else {
                // Add config items
                for (const config of data.configs) {
                    const li = document.createElement('li');
                    li.className = 'xdr-dropdown-item';
                    li.dataset.value = config.id;
                    li.textContent = `${config.name} (${config.panorama_server})`;
                    this.ngfwConfigItems.appendChild(li);
                }
            }

            // Reinitialize dropdown after adding items
            if (this.ngfwConfigDropdown && window.XdrDropdown) {
                new window.XdrDropdown(this.ngfwConfigDropdown);
            }
        } catch (error) {
            console.error('Error loading NGFW configs:', error);
        }
    }

    async loadAgents() {
        try {
            const response = await fetch(this.agentsUrl, {
                headers: { 'Accept': 'application/json' },
            });

            if (!response.ok) {
                console.error('Failed to load agents');
                return;
            }

            const data = await response.json();

            // Clear existing items
            if (this.agentItems) {
                this.agentItems.innerHTML = '';

                // Add agent items
                for (const agent of data.agents) {
                    const li = document.createElement('li');
                    li.className = 'xdr-dropdown-item';
                    li.dataset.value = agent.id;
                    li.textContent = `${agent.name} (${agent.os_name})`;
                    this.agentItems.appendChild(li);
                }

                // Reinitialize dropdown after adding items
                if (this.agentDropdown && window.XdrDropdown) {
                    new window.XdrDropdown(this.agentDropdown);
                }
            }
        } catch (error) {
            console.error('Error loading agents:', error);
        }
    }

    async loadStatus() {
        try {
            const response = await fetch(this.statusUrl, {
                headers: { 'Accept': 'application/json' },
            });

            if (this._isSessionExpired(response)) {
                this._handleSessionExpired();
                return;
            }

            if (!response.ok) {
                console.error('Failed to load status');
                return;
            }

            const data = await response.json();
            this.currentRange = data.range;
            this._updateUI();

            // Start polling if in a transitional state
            if (this.currentRange && this._isTransitionalState(this.currentRange.status)) {
                this._startPolling();
            }
        } catch (error) {
            // Network errors during fetch can indicate CORS issues from auth redirects
            if (error instanceof TypeError && error.message.includes('Failed to fetch')) {
                console.warn('Fetch failed, likely session expired');
                this._handleSessionExpired();
                return;
            }
            console.error('Error loading status:', error);
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

        // Update NGFW details
        const ngfwDetails = document.getElementById('ngfw-details');
        if (ngfwDetails) {
            if (this.currentRange.ngfw_enabled) {
                ngfwDetails.style.display = 'block';
                const instanceId = document.getElementById('ngfw-instance-id');
                const untrustIp = document.getElementById('ngfw-untrust-ip');
                const trustIp = document.getElementById('ngfw-trust-ip');

                if (instanceId) {
                    instanceId.textContent = this.currentRange.ngfw_instance_id || '--';
                }
                if (untrustIp) {
                    untrustIp.textContent = this.currentRange.ngfw_untrust_ip || '--';
                }
                if (trustIp) {
                    trustIp.textContent = this.currentRange.ngfw_trust_ip || '--';
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

        const ngfwEnabled = this.ngfwCheckbox?.checked ?? false;
        const ngfwConfigId = this.ngfwConfigSelect?.value;

        // Validate NGFW config selection
        if (ngfwEnabled && !ngfwConfigId) {
            alert('Please select an NGFW configuration when NGFW is enabled.');
            return;
        }

        this.launchBtn.disabled = true;
        this.launchBtn.textContent = 'Launching...';

        const requestBody = {
            agent_id: parseInt(agentId),
            ngfw_enabled: ngfwEnabled,
        };

        if (ngfwEnabled && ngfwConfigId) {
            requestBody.ngfw_config_id = parseInt(ngfwConfigId);
        }

        try {
            const response = await fetch(this.launchUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify(requestBody),
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

        this.pollInterval = setInterval(async () => {
            try {
                const response = await fetch(this.statusUrl, {
                    headers: { 'Accept': 'application/json' },
                });

                // Check for session expiration first
                if (this._isSessionExpired(response)) {
                    this._handleSessionExpired();
                    return;
                }

                if (!response.ok) {
                    console.warn('Polling: response not ok', response.status);
                    this.pollErrorCount++;
                    if (this.pollErrorCount >= this.maxPollErrors) {
                        console.error('Too many polling errors, reloading page');
                        globalThis.location.reload();
                    }
                    return;
                }

                // Reset error count on success
                this.pollErrorCount = 0;

                const data = await response.json();
                const oldStatus = this.currentRange?.status;
                const newStatus = data.range?.status;
                this.currentRange = data.range;
                this._updateUI();

                // Log state transitions for debugging
                if (oldStatus !== newStatus) {
                    console.log(`Range status: ${oldStatus} → ${newStatus ?? 'null (no range)'}`);
                }

                // Stop polling if we've reached a stable state
                if (!this.currentRange || !this._isTransitionalState(this.currentRange.status)) {
                    this._stopPolling();

                    // Show notification for state transitions
                    if (oldStatus && this.currentRange) {
                        if (oldStatus === 'provisioning' && this.currentRange.status === 'ready') {
                            // Range is ready - could show a notification
                            console.log('Range is ready!');
                        }
                    }
                }
            } catch (error) {
                // Network errors during fetch can indicate CORS issues from auth redirects
                if (error instanceof TypeError && error.message.includes('Failed to fetch')) {
                    console.warn('Polling fetch failed, likely session expired');
                    this._handleSessionExpired();
                    return;
                }
                console.error('Polling error:', error);
            }
        }, this.pollIntervalMs);
    }

    _stopPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
    }
}

// Export for use in templates
window.DashboardManager = DashboardManager;
