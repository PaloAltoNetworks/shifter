/**
 * Dashboard connection layer - WebSocket status stream, polling fallback,
 * provisioning timeout, and session-expiry handling.
 *
 * Split out of dashboard.js (SonarCloud javascript:S104). This is the root of
 * the DashboardManager class chain: DashboardConnectionBase -> DashboardTilesBase
 * -> DashboardLaunchBase -> DashboardManager. Each layer is a plain (non-module)
 * script that publishes its class on globalThis so the browser script tags and
 * the jest `require` harness both resolve them; load this file first.
 */
class DashboardConnectionBase {
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
        // Only navigate to a same-origin target: loginUrl is a server-rendered
        // path, but validating it blocks a javascript:/cross-origin value from
        // ever reaching location.href (DOM-sourced redirect hardening).
        const loginTarget = new URL(this.loginUrl, globalThis.location.origin);
        if (loginTarget.origin === globalThis.location.origin) {
            globalThis.location.href = loginTarget.href;
        }
    }

    _bindCleanup() {
        // Clean up WebSocket on page unload to prevent memory leaks
        globalThis.addEventListener('beforeunload', () => {
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

    _isTransitionalState(status) {
        return ['pending', 'provisioning', 'pausing', 'resuming'].includes(status);
    }

    /**
     * Build WebSocket URL for range status updates.
     * Uses wss:// for https:// pages, ws:// for http://.
     * @param {string} requestId - UUID of the request
     */
    _buildWebSocketUrl(requestId) {
        const protocol = globalThis.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${globalThis.location.host}/ws/range-status/${requestId}/`;
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
            if (!data?.range) return;

            const polledStatus = data.range.status;

            // If we discovered a stable state via poll (missed WebSocket update)
            if (!this._isTransitionalState(polledStatus)) {
                console.log(`Poll detected stable state: ${polledStatus}`);
                this.currentRange = data.range;
                this.currentRaesProjection = data.raes_projection || null;
                this.currentRaesParticipantRuntime = data.raes_participant_runtime || null;
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

globalThis.DashboardConnectionBase = DashboardConnectionBase;
