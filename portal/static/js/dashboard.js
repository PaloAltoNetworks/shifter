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

        this.agentSelect = document.getElementById('agent-select');
        this.launchBtn = document.getElementById('launch-btn');
        this.cancelBtn = document.getElementById('cancel-btn');
        this.openWorkspaceBtn = document.getElementById('open-workspace-btn');
        this.pauseBtn = document.getElementById('pause-btn');
        this.destroyBtn = document.getElementById('destroy-btn');
        this.resumeBtn = document.getElementById('resume-btn');
        this.destroyPausedBtn = document.getElementById('destroy-paused-btn');
        this.dismissErrorBtn = document.getElementById('dismiss-error-btn');

        this._bindEvents();
        this._bindCleanup();
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
        // Agent select change
        if (this.agentSelect) {
            this.agentSelect.addEventListener('change', () => {
                this.launchBtn.disabled = !this.agentSelect.value;
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
        // Load agents and current status in parallel
        await Promise.all([
            this.loadAgents(),
            this.loadStatus(),
        ]);
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

            // Clear existing options (except placeholder)
            while (this.agentSelect.options.length > 1) {
                this.agentSelect.remove(1);
            }

            // Add agent options
            for (const agent of data.agents) {
                const option = document.createElement('option');
                option.value = agent.id;
                option.textContent = `${agent.name} (${agent.os_name})`;
                this.agentSelect.appendChild(option);
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
                this._updateProvisioningState('Resuming range...');
                break;

            case 'destroying':
                this.provisioningState.style.display = 'block';
                this._updateProvisioningState('Destroying range...');
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

    _updateProvisioningState(message = 'Setting up infrastructure...') {
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

        // Set workspace URL (validate protocol for defense-in-depth)
        if (this.openWorkspaceBtn && this.currentRange.chat_url) {
            if (this._isValidHttpUrl(this.currentRange.chat_url)) {
                this.openWorkspaceBtn.href = this.currentRange.chat_url;
                this.openWorkspaceBtn.target = '_blank';
            } else {
                this.openWorkspaceBtn.removeAttribute('href');
                this.openWorkspaceBtn.removeAttribute('target');
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

    async launchRange() {
        const agentId = this.agentSelect.value;
        if (!agentId) return;

        this.launchBtn.disabled = true;
        this.launchBtn.textContent = 'Launching...';

        try {
            const response = await fetch(this.launchUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify({ agent_id: parseInt(agentId) }),
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

            this.currentRange = data.range;
            this._updateUI();
            this._startPolling();

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

                if (!response.ok) {
                    console.warn('Polling: response not ok', response.status);
                    this.pollErrorCount++;
                    if (this.pollErrorCount >= this.maxPollErrors) {
                        console.error('Too many polling errors, reloading page');
                        window.location.reload();
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
