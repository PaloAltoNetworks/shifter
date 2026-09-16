/**
 * Dashboard range-tile rendering - paints the range tiles (provisioning,
 * active, paused, failed) and the read-only RAES projections.
 *
 * Split out of dashboard.js (SonarCloud javascript:S104). Extends
 * DashboardConnectionBase and is extended in turn by DashboardLaunchBase;
 * load after dashboard-connection.js.
 */
// SonarCloud S1192: extracted duplicated string literal.
const CANCEL_RANGE_BTN_SELECTOR = '.cancel-range-btn';

const DashboardConnectionBaseClass = globalThis.DashboardConnectionBase;

class DashboardTilesBase extends DashboardConnectionBaseClass {
    _updateUI() {
        // Reset all range tiles to empty state
        this._resetRangeTiles();

        if (!this.currentRange) {
            this._resetLaunchButton();
            return;
        }

        // Use first available tile for the current range
        const tile = this.rangeTiles[0];
        if (!tile) return;

        switch (this.currentRange.status) {
            case 'pending':
            case 'provisioning':
                this._renderProvisioningTile(tile);
                break;

            case 'ready':
                this._renderActiveTile(tile);
                break;

            case 'paused':
                this._renderPausedTile(tile);
                break;

            case 'pausing': {
                this._renderProvisioningTile(tile, 'Pausing Range', 'Stopping instances...');
                // Hide cancel button - pause cannot be cancelled
                const pauseCancelBtn = tile.querySelector(CANCEL_RANGE_BTN_SELECTOR);
                if (pauseCancelBtn) pauseCancelBtn.style.display = 'none';
                break;
            }

            case 'resuming': {
                this._renderProvisioningTile(tile, 'Resuming Range', 'Starting instances...');
                // Hide cancel button - resume cannot be cancelled
                const resumeCancelBtn = tile.querySelector(CANCEL_RANGE_BTN_SELECTOR);
                if (resumeCancelBtn) resumeCancelBtn.style.display = 'none';
                break;
            }

            case 'failed':
                this._renderFailedTile(tile);
                break;

            default:
                // destroyed or unknown - keep empty
                break;
        }
    }

    /**
     * Reset all range tiles to empty state.
     */
    _resetRangeTiles() {
        for (const tile of this.rangeTiles) {
            if (!tile) continue;
            tile.className = 'range-tile empty-tile';
            tile.innerHTML = '<span class="text-muted">No active range</span>';
        }
    }

    /**
     * Render a tile in provisioning state.
     */
    _renderProvisioningTile(tile, title = 'Provisioning Range', message = 'Setting up infrastructure...') {
        if (!this.provisioningTemplate) return;

        tile.className = 'range-tile provisioning-tile';
        tile.innerHTML = this.provisioningTemplate.innerHTML;

        // Update title and message
        const titleEl = tile.querySelector('.tile-title');
        if (titleEl) titleEl.textContent = title;

        const statusText = tile.querySelector('.status-text');
        if (statusText) statusText.textContent = message;

        // Bind cancel button
        const cancelBtn = tile.querySelector(CANCEL_RANGE_BTN_SELECTOR);
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => this.cancelRange());
        }
    }

    /**
     * Render a tile in active state.
     */
    _renderActiveTile(tile) {
        if (!this.activeTemplate) return;

        tile.className = 'range-tile active-tile';
        tile.innerHTML = this.activeTemplate.innerHTML;

        // Update agent name
        const agentEl = tile.querySelector('.range-agent');
        if (agentEl && this.currentRange.agent_name) {
            agentEl.textContent = this.currentRange.agent_name;
        }

        // Bind destroy button
        const destroyBtn = tile.querySelector('.destroy-btn');
        if (destroyBtn) {
            destroyBtn.addEventListener('click', () => this.destroyRange());
        }

        // Bind pause button
        const pauseBtn = tile.querySelector('#pause-btn');
        if (pauseBtn) {
            pauseBtn.addEventListener('click', () => this.pauseRange());
        }

        this._renderRaesProjection(tile);
        this._renderRaesParticipantRuntime(tile);
    }

    /**
     * Render a tile in paused state.
     */
    _renderPausedTile(tile) {
        if (!this.pausedTemplate) return;

        tile.className = 'range-tile paused-tile';
        tile.innerHTML = this.pausedTemplate.innerHTML;

        // Update paused at time
        const pausedAtEl = tile.querySelector('.range-paused-at');
        if (pausedAtEl && this.currentRange.paused_at) {
            pausedAtEl.textContent = this._formatDate(this.currentRange.paused_at);
        }

        // Update agent name
        const agentEl = tile.querySelector('.range-agent');
        if (agentEl && this.currentRange.agent_name) {
            agentEl.textContent = this.currentRange.agent_name;
        }

        // Bind destroy button
        const destroyBtn = tile.querySelector('.destroy-btn');
        if (destroyBtn) {
            destroyBtn.addEventListener('click', () => this.destroyRange());
        }

        // Bind resume button
        const resumeBtn = tile.querySelector('#resume-btn');
        if (resumeBtn) {
            resumeBtn.addEventListener('click', () => this.resumeRange());
        }

        this._renderRaesProjection(tile);
        this._renderRaesParticipantRuntime(tile);
    }

    /**
     * Render the secondary, read-only RAES operation projection into a tile (#1276).
     *
     * RAES-derived values are inserted with textContent only (never innerHTML),
     * and the section stays hidden for legacy / non-RAES ranges (null projection).
     * This is display-only: it does not affect range status, websocket, or polling.
     */
    _renderRaesProjection(tile) {
        const section = tile.querySelector('.raes-projection');
        if (!section) return;

        const projection = this.currentRaesProjection;
        if (!projection) {
            section.hidden = true;
            return;
        }

        const labelEl = section.querySelector('.raes-status-label');
        if (labelEl) labelEl.textContent = projection.status_label || '';

        const observedEl = section.querySelector('.raes-observed-at');
        if (observedEl) {
            observedEl.textContent = projection.observed_at
                ? `Observed ${this._formatDate(projection.observed_at)}`
                : '';
        }

        const snapshotEl = section.querySelector('.raes-snapshot-summary');
        if (snapshotEl) {
            const snapshot = projection.snapshot;
            snapshotEl.textContent = snapshot ? `Snapshot: ${snapshot.resource_count} resource(s)` : '';
        }

        section.hidden = false;
    }

    /**
     * Render the secondary, read-only RAES participant/runtime + access-channel
     * projection into a tile (#1290). Sibling to _renderRaesProjection:
     * RAES-derived values are inserted with textContent only (never innerHTML),
     * and the section stays hidden for legacy / non-RAES ranges (null
     * projection). This is display-only: it does not affect range status,
     * websocket, or polling.
     */
    _renderRaesParticipantRuntime(tile) {
        const section = tile.querySelector('.raes-participant-runtime');
        if (!section) return;

        const projection = this.currentRaesParticipantRuntime;
        if (!projection) {
            section.hidden = true;
            return;
        }

        const participantsEl = section.querySelector('.raes-participant-runtime-participants');
        if (participantsEl) {
            participantsEl.textContent = '';
            for (const participant of projection.participants || []) {
                const runtimeStatus = participant.runtime?.status ?? null;
                const implementationStatus = participant.implementation?.status ?? null;
                const status = runtimeStatus || implementationStatus || 'unknown';
                const line = document.createElement('div');
                line.textContent = `${participant.participant_ref}: ${status}`;
                participantsEl.appendChild(line);
            }
        }

        const channelsEl = section.querySelector('.raes-participant-runtime-channels');
        if (channelsEl) {
            const labels = (projection.access_channels || []).map((channel) => channel.channel);
            channelsEl.textContent = labels.join(', ');
        }

        section.hidden = false;
    }

    /**
     * Render a tile in failed state.
     */
    _renderFailedTile(tile) {
        if (!this.failedTemplate) return;

        tile.className = 'range-tile failed-tile';
        tile.innerHTML = this.failedTemplate.innerHTML;

        // Update error message
        const errorEl = tile.querySelector('.error-message');
        if (errorEl && this.currentRange.error_message) {
            errorEl.textContent = this.currentRange.error_message;
        }

        // Bind dismiss button
        const dismissBtn = tile.querySelector('.dismiss-error-btn');
        if (dismissBtn) {
            dismissBtn.addEventListener('click', () => this.dismissError());
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
}

globalThis.DashboardTilesBase = DashboardTilesBase;
