/**
 * CTF Range Management
 *
 * Handles:
 * - Bulk provisioning all participant ranges
 * - Individual participant range provisioning
 * - Individual participant range destruction
 * - Individual participant range stop/start/restart
 * - Individual participant range recovery (rebuild/reassign-spare, issue #1018)
 * - Event spare-range pool management (issue #1018)
 * - Status polling after provisioning
 */

// SonarCloud S1192: extracted duplicated string literals.
const API_PARTICIPANTS_BASE = '/ctf/api/participants/';

class CTFRangeManager {
    constructor(options) {
        this.csrfToken = options.csrfToken;
        this.provisionAllUrl = options.provisionAllUrl;
        this.rangeListUrl = options.rangeListUrl;
        this.spareProvisionUrl = options.spareProvisionUrl;
        this.statusPollDelay = options.statusPollDelay || 10000;
        this.statusPollInterval = null;
    }

    init() {
        this._bindProvisionAll();
        this._bindPerParticipantButtons();
        this._bindSparePool();
    }

    _bindProvisionAll() {
        let btn = document.getElementById('btn-provision-all');
        if (!btn) return;
        btn.addEventListener('click', () => this.provisionAll());
    }

    _bindPerParticipantButtons() {
        const bindAction = (selector, handler) => {
            document.querySelectorAll(selector).forEach((btn) => {
                btn.addEventListener('click', () => {
                    handler(btn.dataset.participantId, btn);
                });
            });
        };

        bindAction('.btn-provision', (id, btn) => this.provisionOne(id, btn));
        bindAction('.btn-destroy', (id, btn) => this.destroyOne(id, btn));
        bindAction('.btn-stop', (id, btn) => this.stopOne(id, btn));
        bindAction('.btn-start', (id, btn) => this.startOne(id, btn));
        bindAction('.btn-restart', (id, btn) => this.restartOne(id, btn));
        bindAction('.btn-recover', (id, btn) => this.recoverOne(id, btn));
    }

    _bindSparePool() {
        let btn = document.getElementById('btn-set-spare-pool');
        if (!btn) return;
        btn.addEventListener('click', () => this.setSparePool());
    }

    async provisionAll() {
        if (!confirm('Provision ranges for all unassigned participants?')) return;

        let btn = document.getElementById('btn-provision-all');
        this._setButtonLoading(btn, 'Queuing...');

        try {
            let response = await fetch(this.provisionAllUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                },
            });

            let data = await response.json();

            if (!response.ok) {
                alert('Error: ' + (data.error || 'Provisioning failed'));
                return;
            }

            // Provisioning now runs in the background; show live progress
            // instead of blocking on a synchronous result.
            this._showProgress('Provisioning queued. Tracking progress...');
            this.startProgressPolling();
        } catch (err) {
            alert('Error provisioning ranges: ' + err.message);
        } finally {
            this._clearButtonLoading(btn, 'Provision All Ranges');
        }
    }

    startProgressPolling() {
        if (this.statusPollInterval) return;
        this.statusPollInterval = setInterval(() => this._pollProgress(), this.statusPollDelay);
        this._pollProgress();
    }

    _stopProgressPolling() {
        if (this.statusPollInterval) {
            clearInterval(this.statusPollInterval);
            this.statusPollInterval = null;
        }
    }

    async _pollProgress() {
        let response;
        try {
            response = await fetch(this.rangeListUrl, {
                method: 'GET',
                headers: { 'X-CSRFToken': this.csrfToken },
            });
        } catch {
            return; // transient; keep polling
        }
        if (!response.ok) return;

        let data = await response.json();
        let progress = data.progress || {};
        let counts = progress.counts || {};
        let task = progress.task || null;

        this._renderProgress(counts, task);

        // Done once no spin-up task is queued/running and nothing is mid-provision.
        let provisioning = counts.provisioning || 0;
        if (!task && provisioning <= 0) {
            this._stopProgressPolling();
            this._reload();
        }
    }

    _showProgress(message) {
        let el = document.getElementById('provision-progress');
        if (!el) return;
        el.textContent = message;
        el.style.display = '';
    }

    _renderProgress(counts, task) {
        let status = task ? task.status : 'idle';
        this._showProgress(
            'Status: ' + status +
            ' — ready ' + (counts.ready || 0) +
            ', provisioning ' + (counts.provisioning || 0) +
            ', error ' + (counts.error || 0) +
            ', not assigned ' + (counts.not_assigned || 0) +
            ' / ' + (counts.total || 0)
        );
    }

    async provisionOne(participantId, btn) {
        if (!confirm('Provision a range for this participant?')) return;

        this._setButtonLoading(btn, 'Provisioning...');

        try {
            let url = API_PARTICIPANTS_BASE + participantId + '/range/provision/';
            let response = await fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                },
            });

            let data = await response.json();

            if (!response.ok) {
                alert('Error: ' + (data.error || 'Provisioning failed'));
                this._clearButtonLoading(btn, 'Provision');
                return;
            }

            this._reload();
        } catch (err) {
            alert('Error provisioning range: ' + err.message);
            this._clearButtonLoading(btn, 'Provision');
        }
    }

    async destroyOne(participantId, btn) {
        if (!confirm('Destroy this participant\'s range? This cannot be undone.')) return;

        this._setButtonLoading(btn, 'Destroying...');

        try {
            let url = API_PARTICIPANTS_BASE + participantId + '/range/destroy/';
            let response = await fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                },
            });

            let data = await response.json();

            if (!response.ok) {
                alert('Error: ' + (data.error || 'Destruction failed'));
                this._clearButtonLoading(btn, 'Destroy');
                return;
            }

            this._reload();
        } catch (err) {
            alert('Error destroying range: ' + err.message);
            this._clearButtonLoading(btn, 'Destroy');
        }
    }

    async stopOne(participantId, btn) {
        if (!confirm('Stop this participant\'s range?')) return;
        await this._rangeAction(participantId, btn, 'stop', 'Stopping...', 'Stop');
    }

    async startOne(participantId, btn) {
        if (!confirm('Start this participant\'s range?')) return;
        await this._rangeAction(participantId, btn, 'start', 'Starting...', 'Start');
    }

    async restartOne(participantId, btn) {
        if (!confirm('Restart this participant\'s range?')) return;
        await this._rangeAction(participantId, btn, 'restart', 'Restarting...', 'Restart');
    }

    async recoverOne(participantId, btn) {
        let strategySelect = document.querySelector('.recovery-strategy[data-participant-id="' + participantId + '"]');
        let strategy = strategySelect ? strategySelect.value : '';

        if (!confirm('Recover this participant\'s range? This replaces it and tears down the old range. This cannot be undone.')) return;

        this._setButtonLoading(btn, 'Recovering...');

        try {
            let url = API_PARTICIPANTS_BASE + participantId + '/range/recover/';
            let response = await fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ strategy: strategy }),
            });

            let data = await response.json();

            if (!response.ok) {
                alert('Error: ' + (data.error || 'Recovery failed'));
                this._clearButtonLoading(btn, 'Recover');
                return;
            }

            this._reload();
        } catch (err) {
            alert('Error recovering range: ' + err.message);
            this._clearButtonLoading(btn, 'Recover');
        }
    }

    async setSparePool() {
        let input = document.getElementById('spare-pool-count');
        let btn = document.getElementById('btn-set-spare-pool');
        if (!input) return;

        let count = Number.parseInt(input.value, 10);
        if (Number.isNaN(count)) {
            alert('Error: pool size must be a number');
            return;
        }

        this._setButtonLoading(btn, 'Updating...');

        try {
            let response = await fetch(this.spareProvisionUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ count: count }),
            });

            let data = await response.json();

            if (!response.ok) {
                alert('Error: ' + (data.error || 'Could not update spare pool'));
                return;
            }

            this._renderSparePoolSummary(data);
        } catch (err) {
            alert('Error updating spare pool: ' + err.message);
        } finally {
            this._clearButtonLoading(btn, 'Update');
        }
    }

    _renderSparePoolSummary(summary) {
        let el = document.getElementById('spare-pool-summary');
        if (!el) return;
        el.textContent = 'Target ' + summary.target_count +
            ', provisioned ' + summary.created + ' new, ' + summary.existing + ' already in the pool.';
    }

    async _rangeAction(participantId, btn, action, loadingText, fallbackText) {
        this._setButtonLoading(btn, loadingText);

        try {
            let url = API_PARTICIPANTS_BASE + participantId + '/range/' + action + '/';
            let response = await fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                },
            });

            let data = await response.json();

            if (!response.ok) {
                alert('Error: ' + (data.error || action + ' failed'));
                this._clearButtonLoading(btn, fallbackText);
                return;
            }

            this._reload();
        } catch (err) {
            alert('Error: ' + err.message);
            this._clearButtonLoading(btn, fallbackText);
        }
    }

    _reload() {
        location.reload();
    }

    _setButtonLoading(btn, text) {
        if (!btn) return;
        btn.disabled = true;
        btn.dataset.originalText = btn.textContent;
        btn.textContent = text;
    }

    _clearButtonLoading(btn, fallbackText) {
        if (!btn) return;
        btn.disabled = false;
        btn.textContent = btn.dataset.originalText || fallbackText;
    }
}

if (typeof globalThis !== 'undefined') {
    globalThis.CTFRangeManager = CTFRangeManager;
}
